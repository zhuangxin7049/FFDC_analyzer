"""Exercise SnapDump HTTP contracts using an isolated service and fake provider."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import zipfile

import ffdc_snapdump as api


def archive(files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, content in (files or {"Summary.txt": "Outstanding IOs: 0\nPending IOs: 0\nActive TM Count: 0"}).items():
            zipped.writestr(name, content)
    return output.getvalue()


def multipart(filename="sample.zip", data=None):
    data = archive() if data is None else data
    boundary = "snapdump-unit-test-boundary"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class SnapdumpHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path == "/snapdump":
                    cookie = self.server.service.ensure_session(self)
                    self.send_response(200)
                    self.send_header("Set-Cookie", cookie)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif not self.server.service.handle_get(self, parsed):
                    self.send_error(404)

            def do_POST(self):
                if not self.server.service.handle_post(self, urlsplit(self.path), self.server.provider):
                    self.send_error(404)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.now = 1000.0
        self.service = api.SnapdumpService(clock=lambda: self.now)
        self.server.service = self.service
        self.requests = []

        def provider(messages, prompt):
            self.requests.append((messages, prompt))
            return "The snapshot shows no pending I/O [S1]."

        self.server.provider = provider

    def request(self, method, path, *, cookie="", body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        request_headers = dict(headers or {})
        if cookie:
            request_headers["Cookie"] = cookie
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        reply_headers = dict(response.getheaders())
        connection.close()
        content = (json.loads(raw) if reply_headers.get("Content-Type", "").startswith("application/json")
                   else raw.decode("utf-8"))
        return response.status, content, reply_headers

    def session(self, **kwargs):
        status, _, headers = self.request("GET", "/snapdump", **kwargs)
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_avenger_enrichment_is_public_and_raw_sources_stay_session_scoped(self):
        cookie = self.session()
        status, result, _ = self.upload(cookie, data=archive({
            "Summary.txt": "SNAPDUMPI_FAILURE_TYPE_ONDEMAND\nFwMode: IOPI_FW_OPMODE_PERFIT\n",
            "CrashDump.txt": "Ver Name: 8.19\ncurrent personality 0\nOEM/ProfileIdentifier: 1/3\n",
            "RingBuffer.bin": b"\x00\x01",
        }))
        self.assertEqual(status, 200)
        self.assertEqual(result["operating_mode"]["name"], "PerfIT")
        self.assertEqual(len(result["intake"]["unparsed_entries"]), 1)
        self.assertNotIn("_file_text", result)
        source = result["operating_mode"]["evidence"][0]
        status, raw, _ = self.request("GET", result["file_urls"][source["name"]], cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(source["excerpt"], raw)
        status, _, _ = self.request("GET", result["file_urls"][source["name"]], cookie=self.session())
        self.assertEqual(status, 404)

    def test_verified_mapping_answer_keeps_session_boundary_and_diagnosis_provider(self):
        from test_snapdump_avenger import TABLE, ROW, pd
        cookie = self.session()
        _, result, _ = self.upload(cookie, data=archive({
            "Summary.txt": "SNAPDUMPI_FAILURE_TYPE_ONDEMAND\nFwMode: IOPI_FW_OPMODE_PERFIT\n",
            "CrashDump.txt": "Ver Name: 8.19\nChipName: SAS5032W\n",
            "DevPrst.txt": TABLE + ROW, "Pd.txt": pd(),
        }))
        status, answer, _ = self.ask(cookie, result["analysis_id"], question="PD 0x105 的槽位和型号是什么？")
        self.assertEqual(status, 200)
        self.assertIn("ExampleDisk", answer["answer"])
        self.assertIn("0x111 (273 decimal)", answer["answer"])
        self.assertTrue(answer["sources"])
        self.assertEqual(self.requests, [])
        self.assertEqual(self.ask(self.session(), result["analysis_id"], question="PD 0x105 的槽位是什么？")[0], 404)
        status, _, _ = self.ask(cookie, result["analysis_id"], question="PD 0x105 槽位上的盘有什么故障？")
        self.assertEqual(status, 200)
        self.assertEqual(len(self.requests), 1)

    def upload(self, cookie, filename="sample.zip", data=None):
        body, content_type = multipart(filename, data)
        return self.request("POST", "/api/snapdump/analyze", cookie=cookie,
                            body=body, headers={"Content-Type": content_type})

    def ask(self, cookie, analysis_id, **kwargs):
        payload = {"analysis_id": analysis_id, "question": "What are the I/O counters?", **kwargs}
        return self.request("POST", "/api/snapdump/ask", cookie=cookie,
                            body=json.dumps(payload), headers={"Content-Type": "application/json"})

    def test_page_creates_opaque_http_only_session_with_tls_aware_cookie(self):
        _, _, headers = self.request("GET", "/snapdump")
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Secure", cookie)
        self.assertRegex(cookie, r"ffdc_snapdump_session=[A-Za-z0-9_-]{43};")
        _, _, headers = self.request("GET", "/snapdump", headers={"X-Forwarded-Proto": "https"})
        self.assertIn("; Secure", headers["Set-Cookie"])

    def test_api_never_creates_session_and_requires_page_first(self):
        status, _, headers = self.upload("")
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(self.request("GET", "/api/snapdump/file?id=x&name=y")[0], 401)
        self.assertEqual(self.ask("", "anything")[0], 401)
        self.assertFalse(self.service.sessions)

    def test_upload_and_file_preserve_exact_text_without_leaking_other_logs(self):
        cookie = self.session()
        status, result, headers = self.upload(cookie, data=archive({"nested/log file.txt": "private raw evidence\n"}))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("_file_text", result)
        url = result["file_urls"]["nested/log file.txt"]
        self.assertIn("%20", url)
        status, text, headers = self.request("GET", url, cookie=cookie)
        self.assertEqual((status, text), (200, "private raw evidence\n"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_two_browsers_cannot_read_or_question_each_others_analysis(self):
        first, second = self.session(), self.session()
        _, result, _ = self.upload(first)
        self.assertEqual(self.request("GET", result["file_urls"]["Summary.txt"], cookie=second)[0], 404)
        self.assertEqual(self.ask(second, result["analysis_id"])[0], 404)
        self.assertEqual(self.requests, [])

    def test_ask_returns_sources_and_only_current_owned_evidence(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        status, answer, _ = self.ask(cookie, result["analysis_id"], history=[
            {"role": "system", "content": "SYSTEM-INJECTION"},
            {"role": "user", "content": "Prior question"}])
        self.assertEqual(status, 200)
        self.assertEqual(answer["analysis_id"], result["analysis_id"])
        self.assertTrue(answer["sources"])
        self.assertIn("Outstanding IOs: 0", json.dumps(self.requests[0][0]))
        self.assertNotIn("SYSTEM-INJECTION", json.dumps(self.requests))
        self.assertIn("Prior question", json.dumps(self.requests))

    def test_replacement_invalidates_old_file_and_question(self):
        cookie = self.session()
        _, old, _ = self.upload(cookie)
        _, new, _ = self.upload(cookie, "second.txt", b"Pending IOs: 3")
        self.assertNotEqual(old["analysis_id"], new["analysis_id"])
        self.assertEqual(self.request("GET", old["file_urls"]["Summary.txt"], cookie=cookie)[0], 404)
        self.assertEqual(self.ask(cookie, old["analysis_id"])[0], 404)

    def test_result_expires_even_when_session_remains_active(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        self.now += api.SESSION_TTL - 1
        self.session(cookie=cookie)
        self.now += 2
        self.assertEqual(self.ask(cookie, result["analysis_id"])[0], 404)

    def test_expired_session_cannot_be_revived_by_api(self):
        cookie = self.session()
        self.now += api.SESSION_TTL + 1
        self.assertEqual(self.upload(cookie)[0], 401)
        renewed = self.session(cookie=cookie)
        self.assertNotEqual(cookie, renewed)

    def test_damaged_zip_and_unsupported_extension_are_rejected(self):
        cookie = self.session()
        self.assertEqual(self.upload(cookie, data=b"not-a-zip")[0], 400)
        self.assertEqual(self.upload(cookie, filename="trace.bin", data=b"data")[0], 400)

    def test_oversize_is_rejected_before_body_read(self):
        cookie = self.session()
        status, _, headers = self.request("POST", "/api/snapdump/analyze", cookie=cookie, body=b"x",
            headers={"Content-Type": "multipart/form-data; boundary=a", "Content-Length": str(api.MAX_MULTIPART_BYTES + 1)})
        self.assertEqual(status, 413)
        self.assertEqual(headers["Connection"], "close")

    def test_json_types_empty_question_and_overlong_question_are_rejected(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        for question in ("", 123, "x" * 4001):
            self.assertEqual(self.ask(cookie, result["analysis_id"], question=question)[0], 400)
        for body in ("[]", "broken", "null"):
            status, _, _ = self.request("POST", "/api/snapdump/ask", cookie=cookie, body=body,
                                        headers={"Content-Type": "application/json"})
            self.assertEqual(status, 400)

    def test_rate_limits_do_not_clear_on_page_refresh_and_reset_after_window(self):
        self.service.limits.update(analyze=1, ask=1)
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        self.session(cookie=cookie)
        self.assertEqual(self.upload(cookie)[0], 429)
        self.assertEqual(self.ask(cookie, result["analysis_id"])[0], 200)
        self.assertEqual(self.ask(cookie, result["analysis_id"])[0], 429)
        self.now += 3601
        self.assertEqual(self.ask(cookie, result["analysis_id"])[0], 200)

    def test_cross_site_upload_and_ask_are_rejected(self):
        cookie = self.session()
        body, content_type = multipart()
        for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            status, _, _ = self.request("POST", "/api/snapdump/analyze", cookie=cookie, body=body,
                headers={"Content-Type": content_type, **headers})
            self.assertEqual(status, 403)
        self.assertIsNone(next(iter(self.service.sessions.values()))["result"])

    def test_provider_error_is_redacted_and_retry_succeeds(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        for error, status in [(RuntimeError("secret-token-value"), 502), (TimeoutError(), 504)]:
            def failing(messages, prompt):
                raise error
            self.server.provider = failing
            reply_status, content, _ = self.ask(cookie, result["analysis_id"])
            self.assertEqual(reply_status, status)
            self.assertNotIn("secret-token-value", json.dumps(content))
        self.server.provider = lambda messages, prompt: {"answer": "Recovered"}
        self.assertEqual(self.ask(cookie, result["analysis_id"])[1]["answer"], "Recovered")
        self.assertEqual(self.service.active_counts["ask"], 0)

    def test_concurrent_ask_is_rejected_and_replaced_result_never_returns_answer(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        entered, release = threading.Event(), threading.Event()
        response = []

        def blocking(messages, prompt):
            entered.set()
            release.wait(5)
            return "STALE SECRET ANSWER"

        self.server.provider = blocking
        thread = threading.Thread(target=lambda: response.append(self.ask(cookie, result["analysis_id"])))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.ask(cookie, result["analysis_id"])[0], 409)
            self.assertEqual(self.upload(cookie, "new.txt", b"Outstanding IOs: 12")[0], 200)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(response[0][0], 404)
        self.assertNotIn("STALE SECRET", json.dumps(response))

    def test_session_bound_evicts_oldest_and_invalidates_its_evidence(self):
        self.service.max_sessions = 2
        first = self.session()
        self.upload(first)
        self.session()
        self.session()
        self.assertEqual(len(self.service.sessions), 2)
        self.assertEqual(self.upload(first)[0], 401)

    def test_cache_bound_evicts_oldest_result_but_retains_session(self):
        first, second = self.session(), self.session()
        _, result, _ = self.upload(first, "one.txt", b"a" * 100)
        self.service.max_cache_bytes = int(next(item["size"] for item in self.service.sessions.values() if item["result"]) * 1.5)
        self.now += 1
        self.assertEqual(self.upload(second, "two.txt", b"b" * 100)[0], 200)
        self.assertEqual(self.ask(first, result["analysis_id"])[0], 404)
        self.assertEqual(len(self.service.sessions), 2)
        self.assertLessEqual(sum(s["size"] for s in self.service.sessions.values()), self.service.max_cache_bytes)

    def test_single_result_cannot_exceed_cache_bound(self):
        self.service.max_cache_bytes = 100
        cookie = self.session()
        self.assertEqual(self.upload(cookie, "one.txt", b"a" * 100)[0], 413)
        self.assertIsNone(next(iter(self.service.sessions.values()))["result"])

    def test_non_snapdump_routes_are_not_intercepted(self):
        self.assertFalse(self.service.handle_get(None, urlsplit("/api/other")))
        self.assertFalse(self.service.handle_post(None, urlsplit("/api/other"), None))

    def test_controlled_shared_provider_limit_retains_status(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        def busy(messages, prompt):
            raise api.RequestError(429, "The shared AI provider is busy.")
        self.server.provider = busy
        self.assertEqual(self.ask(cookie, result["analysis_id"])[0], 429)
        self.assertEqual(self.service.active_counts["ask"], 0)

    def test_global_concurrency_bound_applies_across_browsers(self):
        self.service.active_limits["ask"] = 1
        first, second = self.session(), self.session()
        _, first_result, _ = self.upload(first)
        _, second_result, _ = self.upload(second)
        entered, release = threading.Event(), threading.Event()
        replies = []
        def blocking(messages, prompt):
            entered.set()
            release.wait(5)
            return "One answer"
        self.server.provider = blocking
        thread = threading.Thread(target=lambda: replies.append(self.ask(first, first_result["analysis_id"])))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.ask(second, second_result["analysis_id"])[0], 429)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(replies[0][0], 200)
        self.assertEqual(self.service.active_counts["ask"], 0)

    def test_expiring_session_during_provider_request_suppresses_answer(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        def expire(messages, prompt):
            self.now += api.SESSION_TTL + 1
            return "Expired answer"
        self.server.provider = expire
        status, content, _ = self.ask(cookie, result["analysis_id"])
        self.assertEqual(status, 404)
        self.assertNotIn("Expired answer", json.dumps(content))

    def test_malformed_multipart_and_missing_file_are_rejected(self):
        cookie = self.session()
        for body, content_type in ((b"invalid", "multipart/form-data; boundary=wrong"),
                                   (b"--empty--\r\n", "multipart/form-data; boundary=empty")):
            status, _, _ = self.request("POST", "/api/snapdump/analyze", cookie=cookie, body=body,
                                       headers={"Content-Type": content_type})
            self.assertEqual(status, 400)

    def test_actual_file_limit_is_checked_separately_from_multipart_limit(self):
        cookie = self.session()
        with patch.object(api, "MAX_UPLOAD_BYTES", 5):
            self.assertEqual(self.upload(cookie, "x.txt", b"123456")[0], 413)

    def test_transfer_encoded_requests_are_rejected(self):
        cookie = self.session()
        body, content_type = multipart()
        status, _, _ = self.request("POST", "/api/snapdump/analyze", cookie=cookie, body=body,
            headers={"Content-Type": content_type, "Transfer-Encoding": "chunked"})
        self.assertEqual(status, 400)


class SnapdumpApplicationIntegrationTests(unittest.TestCase):
    """Keep app.py's real routing, page wrapping and provider adapter in the loop."""
    request = SnapdumpHTTPTests.request
    session = SnapdumpHTTPTests.session
    upload = SnapdumpHTTPTests.upload
    ask = SnapdumpHTTPTests.ask

    @classmethod
    def setUpClass(cls):
        import app
        cls.app = app
        class QuietHandler(app.Handler):
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.service = api.SnapdumpService()
        for target, replacement in (("ensure_session", self.service.ensure_session),
                                    ("handle_get", self.service.handle_get),
                                    ("handle_post", self.service.handle_post)):
            patcher = patch.object(api, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mocks = {}
        for name, options in {
            "record_usage": {},
            "load_ai_config": {"return_value": ("https://provider.example/v1", "test-key-not-real", "test-model")},
            "post_json": {"return_value": {"choices": [{"message": {"content": "Integrated answer [S1]"}}]}},
            "acquire_workspace_chat_slot": {"return_value": True},
            "release_workspace_chat_slot": {},
            "wait_for_ai_request_start": {},
            "get_jira_session": {"side_effect": AssertionError("SnapDump must not require Jira")},
            "get_jira_session_credentials": {"side_effect": AssertionError("SnapDump must not read Jira credentials")},
        }.items():
            patcher = patch.object(self.app, name, **options)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def test_real_page_route_sets_cookie_and_has_single_shell_with_workspace_query(self):
        for path in ("/snapdump", "/snapdump?view=workspace"):
            status, page, headers = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertEqual(page.count('class="workspace-subpage-shell"'), 1)
            self.assertEqual(page.count("<main"), 1)
            self.assertIn("ffdc_snapdump_session=", headers["Set-Cookie"])
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn('href="/snapdump" class="active"', page)

    def test_real_routes_upload_read_and_ask_using_ffdc_provider_without_jira(self):
        cookie = self.session()
        status, result, _ = self.upload(cookie)
        self.assertEqual(status, 200)
        status, text, _ = self.request("GET", result["file_urls"]["Summary.txt"], cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Outstanding IOs: 0", text)
        status, answer, _ = self.ask(cookie, result["analysis_id"])
        self.assertEqual(status, 200)
        self.assertEqual(answer["answer"], "Integrated answer [S1]")
        self.assertTrue(answer["sources"])
        self.mocks["load_ai_config"].assert_called_once()
        self.mocks["release_workspace_chat_slot"].assert_called_once()
        args = self.mocks["post_json"].call_args.args
        self.assertEqual(args[:2], ("https://provider.example/v1/chat/completions", "test-key-not-real"))
        self.assertEqual(args[2]["messages"][0]["role"], "system")
        self.assertIn("Outstanding IOs", json.dumps(args[2]["messages"]))
        self.assertNotIn("test-key-not-real", json.dumps(answer))

    def test_ffdc_shared_provider_busy_maps_to_retryable_429(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        self.mocks["acquire_workspace_chat_slot"].return_value = False
        status, answer, _ = self.ask(cookie, result["analysis_id"])
        self.assertEqual(status, 429)
        self.assertIn("busy", answer["error"])
        self.mocks["post_json"].assert_not_called()
        self.mocks["release_workspace_chat_slot"].assert_not_called()

    def test_ffdc_provider_failure_releases_slot_and_hides_configuration(self):
        cookie = self.session()
        _, result, _ = self.upload(cookie)
        self.mocks["post_json"].side_effect = RuntimeError("test-key-not-real private-provider-url")
        status, answer, _ = self.ask(cookie, result["analysis_id"])
        self.assertEqual(status, 502)
        self.assertNotIn("test-key-not-real", json.dumps(answer))
        self.assertNotIn("private-provider", json.dumps(answer))
        self.mocks["release_workspace_chat_slot"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
