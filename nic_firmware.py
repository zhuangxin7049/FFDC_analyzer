"""Collect NIC firmware evidence without inferring upgrade results from BMU status.

Shared PLDM/MCTP and BMU logs are supporting evidence, not an adapter identity
or a successful NIC update. Nested support archives are read with strict bounds;
only selected text is materialized so existing raw-evidence tools can read it.
"""
import fnmatch
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import tarfile


MAX_DISCOVERED_FILES = 20000
MAX_LOG_SOURCES = 64
MAX_TEXT_BYTES = 512 * 1024
MAX_TOTAL_TEXT_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 80
MAX_EVENTS_PER_SOURCE = 12
MAX_EVIDENCE_CHARS = 600
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_NESTED_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_TOTAL_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 256
MAX_ARCHIVE_DEPTH = 3

# Suffix matching permits the FFDC's outer collection directory.
EXPECTED_SOURCES = (
    ("pstorage/flash/flash_history.log*", "flash_history"),
    ("pstorage/persist/fm/flash_history.log*", "flash_history"),
    ("tmp/fm.log*", "firmware_manager"),
    ("tmp/mctp_trace.log*", "mctp"),
    ("var/log/pldm.log*", "pldm"),
    ("tmp/ibmulog/bmu_fwrpm.log", "bmu"),
    ("tmp/ffdc_live_dbg/tracebuffer/IBMU.tgz", "bmu_archive"),
    ("tmp/ibmulog/lenovobmu.tgz", "bmu_archive"),
    ("tmp/ibmulog/*_fw*_nic_*.log", "vendor_nic"),
)
_GENERATED_DIR = "_nic_firmware"
# Vendor names alone also describe RAID/HBA/FC products. Shared log lines need
# explicit network identity; *_nic_* filenames already establish NIC scope.
_NIC_RE = re.compile(
    r"\b(?:nic|ethernet|network\s+(?:adapter|card|interface)|connectx(?:-\d+)?|"
    r"bnxt(?:_en)?|mlx[45]_(?:en|core))\b", re.I)
_RELEVANT_RE = re.compile(
    r"\b(?:firmware|flash\w*|updat\w*|upgrad\w*|pldm|mctp|eid|tid|bmu|ibmu|nic|ethernet|"
    r"brcm|bnxt|broadcom|mellanox|connectx|error\w*|fail\w*|success\w*|complet\w*|"
    r"timeout|abort\w*|progress|unsupported|version)\b", re.I)
_SENSITIVE_RE = re.compile(
    r"\b(?:password|passwd|authorization|bearer|api[_ -]?key|access[_ -]?token|"
    r"private[_ -]?key|secret|cookie)\b", re.I)


class _LimitExceeded(Exception):
    pass


class _BoundedArchiveReader:
    """Count expanded bytes before tarfile can skip a large/irrelevant member."""

    def __init__(self, reader, shared_budget):
        self.reader = reader
        self.shared_budget = shared_budget
        self.used = 0

    def read(self, size=-1):
        remaining = min(MAX_ARCHIVE_EXPANDED_BYTES - self.used,
                        MAX_TOTAL_EXPANDED_BYTES - self.shared_budget[0])
        if remaining <= 0:
            raise _LimitExceeded("archive expanded-byte limit reached")
        requested = remaining + 1 if size < 0 else min(size, remaining + 1)
        data = self.reader.read(requested)
        self.used += len(data)
        self.shared_budget[0] += len(data)
        if len(data) > remaining:
            raise _LimitExceeded("archive expanded-byte limit reached")
        return data


def _matches(path, pattern):
    path, pattern = path.lower(), pattern.lower()
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, "*/" + pattern)


def _category(path):
    for pattern, category in EXPECTED_SOURCES:
        if _matches(path, pattern):
            return category
    return None


def _safe_member(name):
    # Backslashes and drive prefixes are rejected even on POSIX for portable safety.
    if not name or "\\" in name or "\x00" in name or re.match(r"^[A-Za-z]:", name):
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _selected_member(name):
    lower = name.lower()
    return (PurePosixPath(lower).name == "ibmu.log"
            or _matches(lower, "var/log/lenovo_support/*.log")
            or fnmatch.fnmatchcase(PurePosixPath(lower).name, "*_fw*_nic_*.log"))


def _is_archive(name):
    return name.lower().endswith((".tar", ".tgz", ".tar.gz"))


def _materialize(root, outer_source, origin, data):
    """Write deterministic flat names without following attacker-created links."""
    bucket = hashlib.sha256(outer_source.encode("utf-8")).hexdigest()[:16]
    basename = re.sub(r"[^A-Za-z0-9._-]", "_", origin.rsplit("!", 1)[-1].rsplit("/", 1)[-1])[-100:]
    filename = hashlib.sha256(origin.encode("utf-8")).hexdigest()[:20] + "_" + basename
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(str(root), flags)
    generated_fd = bucket_fd = None
    try:
        try:
            os.mkdir(_GENERATED_DIR, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        generated_fd = os.open(_GENERATED_DIR, flags, dir_fd=root_fd)
        try:
            os.mkdir(bucket, mode=0o700, dir_fd=generated_fd)
        except FileExistsError:
            pass
        bucket_fd = os.open(bucket, flags, dir_fd=generated_fd)
        # Refuse hardlinks as well as symlinks. Existing ordinary generated text
        # may be refreshed by a repeated parse of the same collection.
        try:
            existing = os.stat(filename, dir_fd=bucket_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
            raise OSError("unsafe existing materialized evidence file")
        temporary = filename + "." + secrets.token_hex(8) + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=bucket_fd)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
            os.replace(temporary, filename, src_dir_fd=bucket_fd, dst_dir_fd=bucket_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=bucket_fd)
            except FileNotFoundError:
                pass
    finally:
        for fd in (bucket_fd, generated_fd, root_fd):
            if fd is not None:
                os.close(fd)
    return PurePosixPath(_GENERATED_DIR, bucket, filename).as_posix()


def collect_nic_firmware_evidence(extract_dir, files=None):
    """Return sources, bounded observations, missing coverage, and archive origins.

    ``source`` paths are relative to extract_dir. Event sources are readable text
    paths; archive source entries have ``kind='archive'``. All statuses remain
    Observed because a path map is not a verified vendor result grammar.
    """
    root = Path(extract_dir).resolve()
    result = {"log_sources": [], "events": [], "limitations": [],
              "expected_sources": [], "archive_members": {}}
    limitations = result["limitations"]
    source_by_path = {}
    found_paths = set()
    text_budget = [0]
    expanded_budget = [0]
    member_budget = [0]

    def limit(message):
        if message not in limitations:
            limitations.append(message)

    def add_source(source, category, *, origin=None, available=True, kind="text", **fields):
        entry = {"source": source, "category": category, "origin": origin or source,
                 "available": available, "kind": kind, **fields}
        if source not in source_by_path:
            result["log_sources"].append(entry)
            source_by_path[source] = entry
        else:
            source_by_path[source].update(entry)
        return source_by_path[source]

    def record_text(data, source, category, origin, truncated=False):
        entry = add_source(source, category, origin=origin, truncated=truncated)
        text_budget[0] += len(data)
        if truncated:
            limit(f"Text evidence truncated at the byte limit: {origin}")
        text = data.decode("utf-8-sig", errors="replace")
        emitted = 0
        for line_number, raw in enumerate(text.splitlines(), 1):
            if not raw.strip() or _SENSITIVE_RE.search(raw):
                continue
            if line_number > 4 and not _RELEVANT_RE.search(raw):
                continue
            if len(result["events"]) >= MAX_EVENTS or emitted >= MAX_EVENTS_PER_SOURCE:
                limit("Event excerpts are bounded; omitted lines must be checked in the source logs.")
                break
            evidence = raw.strip()
            if len(evidence) > MAX_EVIDENCE_CHARS:
                evidence = evidence[:MAX_EVIDENCE_CHARS] + "…"
                limit("Long event lines are truncated; read the cited source for the full line.")
            scope = ("nic_firmware" if category == "vendor_nic" or _NIC_RE.search(raw)
                     else "bmu_support" if category in {"bmu", "bmu_archive"}
                     else "firmware_transport")
            result["events"].append({"source": source, "line": line_number, "evidence": evidence,
                                     "scope": scope, "status": "Observed"})
            emitted += 1
        entry["bytes_read"] = len(data)

    def read_allowance():
        return max(0, min(MAX_TEXT_BYTES, MAX_TOTAL_TEXT_BYTES - text_budget[0]))

    def process_archive(raw, origin, outer_source, depth=0):
        if depth >= MAX_ARCHIVE_DEPTH:
            limit(f"Nested archive depth limit reached: {origin}")
            return
        wrapper = None
        try:
            # gzip decompression is wrapped before tarfile, so skipped members
            # and tar headers/PAX metadata consume the same expanded-byte budget.
            if origin.lower().endswith((".tgz", ".tar.gz")):
                wrapper = gzip.GzipFile(fileobj=raw, mode="rb")
            reader = _BoundedArchiveReader(wrapper or raw, expanded_budget)
            seen_members = set()
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for member in archive:
                    member_budget[0] += 1
                    if member_budget[0] > MAX_ARCHIVE_MEMBERS:
                        raise _LimitExceeded("archive member-count limit reached")
                    member_origin = origin + "!" + member.name
                    if not _safe_member(member.name):
                        limit(f"Unsafe archive member skipped: {member_origin}")
                        continue
                    if member.isdir():
                        continue
                    if not member.isfile() or getattr(member, "sparse", None):
                        limit(f"Non-regular archive member skipped: {member_origin}")
                        continue
                    if member.name in seen_members:
                        limit(f"Duplicate archive member skipped: {member_origin}")
                        continue
                    seen_members.add(member.name)
                    nested = _is_archive(member.name)
                    if not nested and not _selected_member(member.name):
                        continue
                    if len(source_by_path) >= MAX_LOG_SOURCES:
                        raise _LimitExceeded("log-source count limit reached")
                    if nested:
                        if member.size > MAX_NESTED_ARCHIVE_BYTES:
                            limit(f"Nested archive byte limit exceeded: {member_origin}")
                            continue
                        with archive.extractfile(member) as member_file:
                            content = member_file.read(MAX_NESTED_ARCHIVE_BYTES + 1)
                        process_archive(io.BytesIO(content), member_origin, outer_source, depth + 1)
                    else:
                        allowance = read_allowance()
                        if not allowance:
                            raise _LimitExceeded("total text-byte limit reached")
                        with archive.extractfile(member) as member_file:
                            content = member_file.read(min(member.size, allowance))
                        try:
                            source = _materialize(root, outer_source, member_origin, content)
                        except OSError as exc:
                            limit(f"Unable to materialize archive evidence: {member_origin} ({type(exc).__name__})")
                            continue
                        result["archive_members"][source] = member_origin
                        category = "vendor_nic" if "_nic_" in member.name.lower() else "bmu_archive"
                        record_text(content, source, category, member_origin, member.size > allowance)
        except (tarfile.TarError, OSError, EOFError, ValueError, _LimitExceeded) as exc:
            detail = str(exc) if isinstance(exc, _LimitExceeded) else type(exc).__name__
            limit(f"Archive evidence incomplete or unreadable: {origin} ({detail})")
        finally:
            if wrapper is not None:
                wrapper.close()

    candidates = set()
    if isinstance(files, dict):
        preferred = files.values()
    else:
        preferred = files or []
    for value in preferred:
        if isinstance(value, (str, os.PathLike)):
            path = Path(value)
            candidates.add(path if path.is_absolute() else root / path)
    try:
        count = 0
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name != _GENERATED_DIR
                             and not (Path(directory) / name).is_symlink())
            for name in sorted(names):
                count += 1
                if count > MAX_DISCOVERED_FILES:
                    limit("File discovery limit reached; additional firmware logs may be present.")
                    break
                path = Path(directory) / name
                if _category(path.relative_to(root).as_posix()):
                    candidates.add(path)
            if count > MAX_DISCOVERED_FILES:
                break
    except OSError as exc:
        limit(f"Firmware log discovery incomplete ({type(exc).__name__}).")

    for path in sorted(candidates, key=lambda item: str(item)):
        source = None
        try:
            relative = path.relative_to(root)
            source = relative.as_posix()
            if _GENERATED_DIR in relative.parts or ".." in relative.parts:
                continue
            category = _category(source)
            if category is None:
                continue
            # Every component must be a real path inside the extracted collection.
            if any((root.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
                limit(f"Symlinked firmware source skipped: {source}")
                continue
            if path.resolve().is_relative_to(root) is False or not path.is_file():
                continue
            if len(source_by_path) >= MAX_LOG_SOURCES:
                limit("Log-source count limit reached; additional sources may be present.")
                break
            found_paths.add(source)
            if category == "bmu_archive":
                entry = add_source(source, category, kind="archive")
                if path.stat().st_size > MAX_ARCHIVE_BYTES:
                    entry["readable"] = False
                    limit(f"Compressed archive byte limit exceeded: {source}")
                    continue
                before = len(result["archive_members"])
                with path.open("rb") as raw:
                    process_archive(raw, source, source)
                entry["selected_members"] = len(result["archive_members"]) - before
                if not entry["selected_members"]:
                    limit(f"No readable selected support logs found in archive: {source}")
            else:
                entry = add_source(source, category)
                allowance = read_allowance()
                if not allowance:
                    add_source(source, category, readable=False)
                    limit("Total text-byte limit reached; additional sources were not read.")
                    continue
                with path.open("rb") as raw:
                    content = raw.read(allowance + 1)
                record_text(content[:allowance], source, category, source, len(content) > allowance)
        except (OSError, ValueError) as exc:
            if source in source_by_path:
                source_by_path[source]["readable"] = False
            limit(f"Firmware source could not be read: {path.name} ({type(exc).__name__})")

    for pattern, category in EXPECTED_SOURCES:
        available = any(_matches(path, pattern) for path in found_paths)
        result["expected_sources"].append({"pattern": pattern, "category": category, "available": available})
        if not available:
            add_source(pattern, category, available=False, kind="archive" if category == "bmu_archive" else "text")
    limit("Log paths vary by FFDC generation; missing sources are evidence gaps, not detected faults.")
    limit("BMU script completion and shared PLDM/MCTP activity do not establish a NIC firmware update result or adapter identity.")
    limit("Collected lines are observations; verified vendor-specific result patterns and device correlation are required to determine update success or failure.")
    return result
