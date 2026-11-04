"""Browser-isolated, bounded SnapDump APIs for the FFDC HTTP server.

Only the SnapDump HTML route creates sessions. Evidence stays in process memory;
no report directory, Jira credentials or Knowledge Hub database is accessed.
"""
from __future__ import annotations

from collections import OrderedDict
from email import policy
from email.parser import BytesParser
from http.cookies import CookieError, SimpleCookie
import json
from pathlib import PurePosixPath
import re
import secrets
import ssl
import sys
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit

from snapdump import MAX_UPLOAD_BYTES, analyze_snapdump, public_result
from snapdump_chat import build_snapdump_chat, verified_snapdump_answer

COOKIE_NAME = "ffdc_snapdump_session"
SESSION_TTL = 2 * 60 * 60
MAX_SESSIONS = 1024
MAX_CACHE_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024
MAX_MULTIPART_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024


def _result_size(value, seen=None):
    """Estimate retained Python object bytes, counting shared objects once.

    ASCII firmware logs use compact one-byte strings in CPython; charging every
    character four bytes wrongly rejected real 30 MiB PL module exports. Wide
    Unicode and structured result objects must still count towards the cache.
    """
    if seen is None:
        seen = set()
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(_result_size(k, seen) + _result_size(v, seen) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        size += sum(_result_size(item, seen) for item in value)
    return size


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _respond(handler, data, status=200, content_type="application/json; charset=utf-8"):
    raw = (json.dumps(data, ensure_ascii=False).encode("utf-8")
           if content_type.startswith("application/json") else data.encode("utf-8", errors="replace"))
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    if getattr(handler, "close_connection", False):
        handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(raw)


def _read_body(handler, maximum):
    if handler.headers.get("Transfer-Encoding"):
        raise RequestError(400, "Transfer-Encoding is not supported for SnapDump requests.")
    lengths = handler.headers.get_all("Content-Length", [])
    if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0].strip()):
        raise RequestError(400, "A valid Content-Length is required.")
    length = int(lengths[0])
    if length <= 0:
        raise RequestError(400, "The request body is empty.")
    if length > maximum:
        raise RequestError(413, "The request body is too large.")
    # Bound slow/incomplete clients as well as allocation; restore server policy.
    connection = getattr(handler, "connection", None)
    old_timeout = connection.gettimeout() if connection else None
    try:
        if connection:
            connection.settimeout(30)
        raw = handler.rfile.read(length)
    except (TimeoutError, OSError) as exc:
        raise RequestError(408, "The upload did not finish. Please try again.") from exc
    finally:
        if connection:
            connection.settimeout(old_timeout)
    if len(raw) != length:
        raise RequestError(400, "The request body is incomplete.")
    return raw


def _read_json(handler):
    if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise RequestError(400, "Content-Type must be application/json.")
    try:
        payload = json.loads(_read_body(handler, MAX_JSON_BYTES).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestError(400, "The JSON body is invalid.") from exc
    if not isinstance(payload, dict):
        raise RequestError(400, "The JSON body must be an object.")
    return payload


def _read_upload(handler):
    content_type = handler.headers.get("Content-Type", "")
    if content_type.split(";", 1)[0].strip().lower() != "multipart/form-data":
        raise RequestError(400, "SnapDump uploads must use multipart/form-data.")
    raw = _read_body(handler, MAX_MULTIPART_BYTES)
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
    if not message.is_multipart() or message.defects:
        raise RequestError(400, "The multipart upload is invalid.")
    parts = [part for part in message.iter_parts()
             if part.get_param("name", header="content-disposition") == "file"]
    if len(parts) != 1 or not parts[0].get_filename() or parts[0].is_multipart():
        raise RequestError(400, "Choose one SnapDump ZIP or text file.")
    filename = PurePosixPath(parts[0].get_filename().replace("\\", "/")).name
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename).strip()[:240]
    if PurePosixPath(filename).suffix.lower() not in {".zip", ".txt", ".log"}:
        raise RequestError(400, "SnapDump supports .zip, .txt or .log files only.")
    data = parts[0].get_payload(decode=True) or b""
    if not data:
        raise RequestError(400, "The SnapDump file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise RequestError(413, "The SnapDump file exceeds 50 MiB.")
    return filename, data


class SnapdumpService:
    def __init__(self, *, clock=time.monotonic, session_ttl=SESSION_TTL,
                 max_sessions=MAX_SESSIONS, max_cache_bytes=MAX_CACHE_BYTES,
                 analyze_limit=20, ask_limit=60, max_analyzing=2, max_asking=4):
        self.clock = clock
        self.session_ttl = session_ttl
        self.max_sessions = max_sessions
        self.max_cache_bytes = max_cache_bytes
        self.limits = {"analyze": analyze_limit, "ask": ask_limit}
        self.active_limits = {"analyze": max_analyzing, "ask": max_asking}
        self.active_counts = {"analyze": 0, "ask": 0}
        self.sessions = OrderedDict()
        self.lock = threading.RLock()

    def _prune(self):
        now = self.clock()
        for token, session in list(self.sessions.items()):
            if now - session["last_seen"] >= self.session_ttl:
                del self.sessions[token]
            elif session["result"] and now - session["created_at"] >= self.session_ttl:
                session["result"] = None
                session["size"] = 0

    def _token(self, handler):
        try:
            cookie = SimpleCookie(handler.headers.get("Cookie", ""))
            item = cookie.get(COOKIE_NAME)
            return item.value if item and re.fullmatch(r"[A-Za-z0-9_-]{43}", item.value) else ""
        except CookieError:
            return ""

    def ensure_session(self, handler):
        """Called by GET /snapdump; return a Set-Cookie value for that HTML response."""
        token = self._token(handler)
        now = self.clock()
        with self.lock:
            self._prune()
            if token not in self.sessions:
                token = secrets.token_urlsafe(32)
                while len(self.sessions) >= self.max_sessions:
                    self.sessions.popitem(last=False)
                self.sessions[token] = {"last_seen": now, "created_at": now, "result": None,
                                        "size": 0, "events": {"analyze": [], "ask": []}, "active": set()}
            self.sessions[token]["last_seen"] = now
            self.sessions.move_to_end(token)
        secure = isinstance(getattr(handler, "connection", None), ssl.SSLSocket)
        secure = secure or handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower() == "https"
        return (f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={self.session_ttl}"
                + ("; Secure" if secure else ""))

    def _session(self, handler):
        with self.lock:
            self._prune()
            token = self._token(handler)
            session = self.sessions.get(token)
            if session is None:
                raise RequestError(401, "Open the SnapDump page, then upload the file again to start a new session.")
            session["last_seen"] = self.clock()
            self.sessions.move_to_end(token)
            return token, session

    def _current(self, token, session, result=None):
        self._prune()
        return self.sessions.get(token) is session and (result is None or session["result"] is result)

    def _begin(self, session, action):
        with self.lock:
            if action in session["active"]:
                raise RequestError(409, "A SnapDump request is already running. Please wait for it to finish.")
            if self.active_counts[action] >= self.active_limits[action]:
                raise RequestError(429, "SnapDump is busy. Please try again shortly.")
            now = self.clock()
            events = [stamp for stamp in session["events"][action] if stamp > now - 3600]
            session["events"][action] = events
            if len(events) >= self.limits[action]:
                raise RequestError(429, "Too many SnapDump requests. Please try again later.")
            events.append(now)
            session["active"].add(action)
            self.active_counts[action] += 1

    def _end(self, session, action):
        with self.lock:
            session["active"].discard(action)
            self.active_counts[action] -= 1

    @staticmethod
    def _check_origin(handler):
        if handler.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            raise RequestError(403, "SnapDump requests must come from this site.")
        origin = handler.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != handler.headers.get("Host", "").lower():
                raise RequestError(403, "SnapDump requests must come from this site.")

    def handle_get(self, handler, parsed):
        if parsed.path != "/api/snapdump/file":
            return False
        try:
            token, session = self._session(handler)
            query = parse_qs(parsed.query)
            analysis_id = query.get("id", [""])[0]
            name = query.get("name", [""])[0]
            with self.lock:
                result = session["result"]
                if not result or not self._current(token, session, result) or result["analysis_id"] != analysis_id:
                    raise RequestError(404, "The SnapDump analysis has expired or is unavailable.")
                text = result.get("_file_text", {}).get(name)
                if text is None:
                    raise RequestError(404, "The SnapDump file does not exist.")
            _respond(handler, text, content_type="text/plain; charset=utf-8")
        except RequestError as exc:
            _respond(handler, {"error": str(exc)}, exc.status)
        return True

    def _analyze(self, handler, token, session):
        self._begin(session, "analyze")
        try:
            filename, data = _read_upload(handler)
            result = analyze_snapdump(filename, data)
            result["analysis_id"] = secrets.token_urlsafe(24)
            size = _result_size(result)
            if size > self.max_cache_bytes:
                raise RequestError(413, "The decoded SnapDump is too large for the evidence cache.")
            with self.lock:
                if not self._current(token, session):
                    raise RequestError(401, "The SnapDump session expired. Open the page and try again.")
                session.update(result=result, size=size, created_at=self.clock())
                # Retain session identities/rate windows when evicting older evidence.
                for old in sorted(self.sessions.values(), key=lambda item: item["created_at"]):
                    if sum(item["size"] for item in self.sessions.values()) <= self.max_cache_bytes:
                        break
                    if old is not session:
                        old.update(result=None, size=0)
            payload = public_result(result)
            payload["file_urls"] = {
                item["name"]: f"/api/snapdump/file?id={quote(result['analysis_id'])}&name={quote(item['name'], safe='')}"
                for item in payload.get("files", [])}
            _respond(handler, payload)
        finally:
            self._end(session, "analyze")

    def _ask(self, handler, token, session, ask_provider):
        payload = _read_json(handler)
        analysis_id = payload.get("analysis_id")
        if not isinstance(analysis_id, str) or not analysis_id or len(analysis_id) > 100:
            raise RequestError(400, "A valid SnapDump analysis ID is required.")
        with self.lock:
            result = session["result"]
            if not result or not self._current(token, session, result) or result["analysis_id"] != analysis_id:
                raise RequestError(404, "This SnapDump analysis has expired or is unavailable. Analyze the file again.")
        self._begin(session, "ask")
        try:
            messages, prompt, sources = build_snapdump_chat(result, payload.get("question"), payload.get("history", []))
            try:
                answer = verified_snapdump_answer(result, payload["question"], sources)
                if answer is None:
                    answer = ask_provider(messages, prompt)
            except RequestError:
                # The FFDC adapter may report a controlled shared-provider limit.
                raise
            except TimeoutError as exc:
                raise RequestError(504, "Davy took too long to answer. Please try again.") from exc
            except Exception as exc:
                # Provider/config errors may contain endpoints or credentials.
                raise RequestError(502, "Davy is unavailable. Please try again later.") from exc
            if isinstance(answer, dict):
                answer = answer.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise RequestError(502, "Davy returned an empty answer. Please try again.")
            with self.lock:
                if not self._current(token, session, result):
                    raise RequestError(404, "This SnapDump analysis expired or was replaced. Analyze the file again.")
            _respond(handler, {"analysis_id": analysis_id, "answer": answer, "sources": sources})
        finally:
            self._end(session, "ask")

    def handle_post(self, handler, parsed, ask_provider):
        if parsed.path not in {"/api/snapdump/analyze", "/api/snapdump/ask"}:
            return False
        try:
            self._check_origin(handler)
            token, session = self._session(handler)
            if parsed.path.endswith("/analyze"):
                self._analyze(handler, token, session)
            else:
                self._ask(handler, token, session, ask_provider)
        except (RequestError, ValueError) as exc:
            # A rejected request may leave unread bytes; never reuse its connection.
            handler.close_connection = True
            _respond(handler, {"error": str(exc)}, exc.status if isinstance(exc, RequestError) else 400)
        return True


_service = SnapdumpService()
ensure_session = _service.ensure_session
handle_get = _service.handle_get
handle_post = _service.handle_post
