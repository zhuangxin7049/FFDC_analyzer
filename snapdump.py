"""Bounded, evidence-based SnapDump text parser for the FFDC workspace."""
from __future__ import annotations

import io
import re
import zipfile
import zlib
from typing import Any

from snapdump_avenger import enrich, operating_mode

MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_STANDALONE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_FILES = 250
TEXT_SUFFIXES = (".txt", ".log", ".text", ".out")
_TEXT_BYTES = bytes([9, 10, 12, 13, *range(32, 256)])


def _text(data: bytes) -> str:
    # TTY exports can contain sparse NULs around discarded ring-buffer text.
    # Permit those in otherwise textual logs, but reject binary payloads even
    # when their names carry a text suffix.
    controls = len(data.translate(None, _TEXT_BYTES))
    if controls > len(data) // 100:
        raise ValueError("Binary content is not supported; upload decoded text logs.")
    return data.decode("utf-8", errors="replace").replace("\x00", "\ufffd")


def _first(pattern: str, text: str, flags: int = re.I | re.M, default: str = "") -> str:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else default


def _all_numbers(pattern: str, text: str, base: int = 10) -> list[int]:
    values = []
    for match in re.finditer(pattern, text, re.I | re.M):
        raw = match.group(1)
        try:
            values.append(int(raw, 16 if raw.lower().startswith("0x") else base))
        except ValueError:
            pass
    return values


def _number(pattern: str, text: str, default: int | None = None, base: int = 10) -> int | None:
    values = _all_numbers(pattern, text, base)
    # A repeated zero must not hide a nonzero counter for another IOC/port.
    return max(values) if values else default


def _status(severity: str, title: str, detail: str, evidence: str = "") -> dict[str, str]:
    return {"severity": severity, "title": title, "detail": detail, "evidence": evidence}


def _read_files(filename: str, data: bytes, inventory: list | None = None) -> dict[str, str]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("SnapDump uploads must not exceed 50 MiB.")
    files: dict[str, str] = {}
    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = [item for item in archive.infolist() if not item.is_dir()]
                if len(entries) > MAX_FILES:
                    raise ValueError("The SnapDump archive contains too many files (maximum 250).")
                total = 0
                for item in entries:
                    name = item.filename.replace("\\", "/").lstrip("/")
                    safe = bool(name and ".." not in name.split("/"))
                    supported = name.lower().endswith(TEXT_SUFFIXES)
                    if inventory is not None:
                        inventory.append({"name": name[:1024], "bytes": item.file_size,
                                          "status": "decoded text" if safe and supported else "unsupported path" if not safe else "collected; not decoded"})
                    if not safe or not supported:
                        continue
                    if item.file_size > MAX_FILE_BYTES:
                        raise ValueError("A text entry exceeds the 40 MiB decompression limit.")
                    if total + item.file_size > MAX_TOTAL_BYTES:
                        raise ValueError("SnapDump text exceeds the 64 MiB total decompression limit.")
                    # Never extract archive paths; bound the actual read as well as metadata.
                    with archive.open(item) as stream:
                        raw = stream.read(min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total) + 1)
                    if len(raw) > MAX_FILE_BYTES or total + len(raw) > MAX_TOTAL_BYTES:
                        raise ValueError("SnapDump exceeds the decompression limit.")
                    total += len(raw)
                    files[name] = _text(raw)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError,
                RuntimeError, NotImplementedError, zlib.error) as exc:
            raise ValueError("Cannot read the SnapDump ZIP: it is damaged, encrypted, or unsupported.") from exc
    else:
        if len(data) > min(MAX_FILE_BYTES, MAX_STANDALONE_BYTES):
            raise ValueError("Standalone text logs must not exceed 16 MiB.")
        files[filename or "SnapDump.txt"] = _text(data)
    if not files or not any(value.strip() for value in files.values()):
        raise ValueError("No supported text logs were found in the SnapDump.")
    return files


def _find(files: dict[str, str], name: str) -> str:
    for key, value in files.items():
        if key.replace("\\", "/").rsplit("/", 1)[-1].lower() == name.lower():
            return value
    return ""


def _event_summary(text: str) -> dict[str, Any]:
    patterns = {
        "firmware_init": r"Firmware initialization started",
        "firmware_complete": r"Firmware initialization completed",
        "nonproduction": r"not intended for production",
        "driver_loaded": r"Host driver is loaded and operational",
        "shutdown": r"Shutdown activity for IOC",
        "enclosure_restore": r"Enclosure PD .*communication restored",
        "snapdump": r"Snapdump (?:having Id|Available Id)",
        "offline": r"\b(?:VD|LD|virtual drive|logical drive)\b[^\r\n]*\bOFFLINE\b",
        "degraded": r"\b(?:VD|LD|virtual drive|logical drive)\b[^\r\n]*\bDEGRADED\b",
        "drive_failure": r"\b(?:PD|physical drive|physical disk)\b[^\r\n]*\b(?:FAILED|failure)\b",
        "timeout": r"\b(?:timeout|timed out)\b",
    }
    counts = {key: len(re.findall(pattern, text, re.I)) for key, pattern in patterns.items()}
    events = []
    event_re = re.compile(
        r"EVT#[0-9]+-(\d{1,2}/\d{1,2}/\d{2}\s+\d{1,2}:\d{2}:\d{2}|T\d+(?:\.\d+)?):"
        r"\s*(?:\w+\s*:\s*)?\d+=([^\r\n]+)", re.M,
    )
    for match in event_re.finditer(text):
        events.append({"time": match.group(1), "message": match.group(2).strip()})
    return {"counts": counts, "events": events[-80:], "total_count": len(events)}


def _legacy_section(text: str, name: str) -> str:
    return _first(r"===SnapDump " + re.escape(name) + r" Info Start===([\s\S]*?)"
                  r"===SnapDump " + re.escape(name) + r" Info End===", text)


def _reset_counter(text: str) -> str | None:
    direct = _first(r"^CtrlResetCount[ \t]+((?:0x)?[0-9a-f]+)\b", text)
    if direct:
        return direct
    # Some NVRAM exporters print the named scalar as exactly one hex dword.
    # Do not interpret multiword structs, ellipsis, or a neighbouring field.
    return _first(r"^CtrlResetCount[ \t]*:[ \t]*\r?\n[ \t]*[0-9a-f]+:[ \t]+"
                  r"([0-9a-f]{8})[ \t]*(?:\.{4})?[ \t]*\r?$", text) or None


def _physical_drives(text: str) -> list[dict[str, Any]]:
    drives = []
    hex_value = r"((?:0x)?[0-9a-f]+)\b"
    for match in re.finditer(r"^PD\s*=\s*([0-9a-f]+)\b([\s\S]*?)(?=^PD\s*=|\Z)", text, re.I | re.M):
        block = match.group(2)
        if _number(r"\bscsiType\s*=\s*" + hex_value, block, base=16) != 0:
            continue
        drives.append({"id": match.group(1),
                       "state": _first(r"\bstate\s*=\s*[0-9a-f]+\s*\(([^)]+)\)", block),
                       "media_errors": _number(r"\bmediaErrCount\s*=\s*" + hex_value, block, base=16),
                       "other_errors": _number(r"\botherErrCount\s*=\s*" + hex_value, block, base=16),
                       "predictive_failures": _number(r"\bpredFailCount\s*=\s*" + hex_value, block, base=16)})
    return drives


def _legacy_pcie(text: str) -> dict[str, Any]:
    # Decode only the explicitly labelled host PCI configuration block. These
    # are standard PCIe register bit fields, not firmware link-rate enums.
    # Definitions: Linux include/uapi/linux/pci_regs.h PCI_EXP_LNKCAP/LNKSTA.
    config = _first(r"<=PCIE Config start=>([\s\S]*?)(?:<=PCIE Config end=>|\Z)", text)

    def reg(name: str) -> int | None:
        return _number(r"^\s*[0-9a-f]+:\s*([0-9a-f]{8})\s+" + name + r"\s*$", config, base=16)

    cap, control = reg("PCI_LINK_CAP"), reg("PCI_LINK_STATUS_CTRL")
    status = control >> 16 if control is not None else None
    dev = reg("PCI_DEV_STATUS_CTRL")
    # Reserved / unknown speed codes remain undecoded.
    speeds = {1: 2.5, 2: 5, 3: 8, 4: 16, 5: 32, 6: 64}
    max_code = cap & 0xf if cap is not None else None
    current_code = status & 0xf if status is not None else None
    return {"max_speed_code": str(max_code) if max_code is not None else "",
            "current_speed_code": str(current_code) if current_code is not None else "",
            "max_speed_gts": speeds.get(max_code), "current_speed_gts": speeds.get(current_code),
            "max_width": (cap >> 4) & 0x3f if cap is not None else None,
            "current_width": (status >> 4) & 0x3f if status is not None else None,
            "device_error_bits": ((dev >> 16) & 0xf) if dev is not None else None,
            "correctable_error_status": reg("PCI_C_ERR_STATUS"),
            "uncorrectable_error_status": reg("PCI_UC_ERR_STATUS"),
            "source": "HWREG.txt / host PCIe configuration registers"}


def _analyze_legacy(filename: str, files: dict[str, str], standalone: str) -> dict[str, Any]:
    """Parse the module-style MegaRAID export using its own labelled fields.

    Controller/PD numeric fields explicitly use hexadecimal in this format.
    Raw trigger and NVRAM codes are kept undecoded; history never supplies the
    current firmware identity or current drive state.
    """
    crash = _find(files, "crashDump.txt") or standalone
    pl = _find(files, "PL_MODULE.txt") or standalone
    nvram = _find(files, "NVRAM_MODULE.txt") or standalone
    events = _find(files, "event_dump.txt")
    pcie = _legacy_pcie(_find(files, "HWREG.txt") or standalone)
    generic = _legacy_section(crash, "Generic")
    controller = generic.split("===Controller Information===", 1)[-1] if generic else crash
    hex_value = r"((?:0x)?[0-9a-f]+)\b"

    def counter(label: str) -> int | None:
        return _number(r"\b" + re.escape(label) + r"\s*=\s*" + hex_value, controller, base=16)

    def source(name: str) -> str:
        return next((key for key in files if key.rsplit("/", 1)[-1].lower() == name.lower()),
                    filename if standalone else name)

    firmware = {
        "version": _first(r"^Firmware version[ \t]+(\S+)", crash),
        "package": _first(r'\bFW packageVersion="([^"\r\n]*)"', controller),
        "driver": _first(r"\bdriverVersion[ \t]*=[ \t]*([^\r\n]*)", generic or crash),
        "build_date": _first(r"^Firmware version[^\r\n]*? built on[ \t]+([^\r\n]+)", crash),
        "release_level": "",
        "board": _first(r"\bproductName=([^,\r\n]+)", controller),
        "personality": "", "operation_mode": "", "runtime_lines": [],
    }
    if firmware["driver"].upper() in ("--NA--", "N/A", "NA"):
        firmware["driver"] = ""
    marker = re.search(r"(?:^|[-_.])(TEST|ALPHA|BETA)(?:$|[-_.])", firmware["version"], re.I)
    if marker:
        firmware["release_level"] = marker.group(1).upper() + " (version marker)"

    logical_drives = []
    for match in re.finditer(r"^Ld\s*=\s*([0-9a-f]+)\b([\s\S]*?)(?=^Ld\s*=|\Z)",
                             _legacy_section(crash, "LD"), re.I | re.M):
        block = match.group(2)
        logical_drives.append({"id": match.group(1),
                               "raid_level": _first(r"^\s*Level[ \t]+([^\r\n]+)", block),
                               "state": _first(r"^\s*Status\s+[0-9a-f]+\s*\(([^)]+)\)", block)
                               or _first(r"\bstate\s*=\s*[0-9a-f]+\s*\(([^)]+)\)", block)})
    physical_drives = _physical_drives(_legacy_section(crash, "PD"))
    snapshot = {key: None for key in (
        "outstanding_io", "pending_io", "active_tm", "failed_io", "topology_error", "topology_critical",
        "hw_errors", "hard_resets", "discovery_errors", "failed_por", "failed_hip", "mapped_slots")}
    snapshot.update({"ioc_faults": [], "cpu_no_fault": False, "pd_state": "",
                     "outstanding_io": _number(r"Total Outstanding IOs:\s*(\d+)", pl),
                     "pending_io": _number(r"Total Outstanding IOs:\s*\d+,\s*Pending IOs:\s*(\d+)", pl),
                     "discovery_errors": _number(r"SAS Device Discovery Error Event Counter\s*:\s*(\d+)", pl),
                     "controller_resets": _reset_counter(nvram)})
    for field, label in {
        "ld_present": "ldPresentCount", "ld_degraded": "ldDegradedCount", "ld_offline": "ldOfflineCount",
        "pd_disks": "pdDiskPresentCount", "pd_failed": "pdDiskFailedCount", "pd_predictive": "pdDiskPredFailureCount",
        "mem_correctable": "memCorrectableErrorCount", "mem_uncorrectable": "memUnCorrectableErrorCount",
    }.items():
        snapshot[field] = counter(label)

    trigger = _first(r"^(SnapDump for faultingModule[^\r\n]+)", crash)
    s = snapshot

    def show(value: Any) -> str:
        return str(value) if value is not None else "Not reported"

    def status_values(*values: Any) -> str:
        return "ok" if all(value == 0 for value in values) else "info"

    ld_states = {item["state"].upper() for item in logical_drives}
    pd_states = {item["state"].upper() for item in physical_drives}
    ld_detail = "; ".join(f"LD {item['id']}: RAID {item['raid_level'] or '?'} {item['state'] or 'Not reported'}"
                          for item in logical_drives[:32])
    reset_nonzero = int(s["controller_resets"], 16) != 0 if s["controller_resets"] is not None else False
    checks = [
        _status(status_values(s["outstanding_io"], s["pending_io"]), "I/O queues",
                f"Outstanding {show(s['outstanding_io'])} · Pending {show(s['pending_io'])}. "
                "Queue activity alone does not establish an I/O fault.", source("PL_MODULE.txt")),
        _status("critical" if s["ld_offline"] or "OFFLINE" in ld_states else
                "warn" if s["ld_degraded"] or "DEGRADED" in ld_states else
                status_values(s["ld_degraded"], s["ld_offline"]), "Logical drive state",
                f"Present {show(s['ld_present'])} · Degraded {show(s['ld_degraded'])} · Offline {show(s['ld_offline'])}. "
                + ld_detail, source("crashDump.txt")),
        _status("critical" if s["pd_failed"] or pd_states.intersection({"FAILED", "OFFLINE", "UNCONFIGURED_BAD"}) else
                "warn" if s["pd_predictive"] else status_values(s["pd_failed"], s["pd_predictive"]),
                "Physical disk state", f"Disks {show(s['pd_disks'])} · Failed {show(s['pd_failed'])} · "
                f"Predictive failure {show(s['pd_predictive'])}. Counts exclude enclosure devices and do not exclude missing RAID members.",
                source("crashDump.txt")),
        _status("critical" if s["mem_uncorrectable"] else "warn" if s["mem_correctable"] else
                status_values(s["mem_correctable"], s["mem_uncorrectable"]), "Memory error counters",
                f"Correctable {show(s['mem_correctable'])} · Uncorrectable {show(s['mem_uncorrectable'])}. "
                "Counters may include historical events.", source("crashDump.txt")),
        _status("warn" if reset_nonzero else "info", "Controller reset counter",
                f"CtrlResetCount {show(s['controller_resets'])} (raw). This is not the MPI3 Num Hard Resets counter; "
                "its reset scope is not established by this export.", source("NVRAM_MODULE.txt")),
        _status("warn" if s["discovery_errors"] else status_values(s["discovery_errors"]), "Discovery error counter",
                f"SAS device discovery errors {show(s['discovery_errors'])}. Nonzero counters may be historical.", source("PL_MODULE.txt")),
        _status("warn" if marker else "info", "Firmware release level",
                f"{firmware['release_level']} found; confirm the supported release." if marker else
                "Release level is not reported; this does not establish production support.", source("crashDump.txt")),
        _status("info", "Snapshot trigger", (trigger + ". " if trigger else "Trigger not reported. ") +
                "Raw module/function/FaultCode values are not decoded; the header alone does not establish a controller crash.",
                source("crashDump.txt")),
    ]
    pd_counters = [item[key] for item in physical_drives for key in ("media_errors", "other_errors", "predictive_failures")]
    if physical_drives:
        checks.insert(3, _status("warn" if any(pd_counters) else status_values(*pd_counters), "Physical disk error counters",
                      "; ".join(f"PD {item['id']}: media {show(item['media_errors'])}, other {show(item['other_errors'])}, "
                                f"predictive {show(item['predictive_failures'])}" for item in physical_drives[:32]) +
                      ". Counters may be historical and do not identify a failed component by themselves.", source("crashDump.txt")))
    if pcie["max_speed_code"] or pcie["current_speed_code"]:
        error_values = [pcie[key] for key in ("device_error_bits", "correctable_error_status", "uncorrectable_error_status")]
        error_text = " / ".join(f"0x{value:X}" if value is not None else "Not reported" for value in error_values)
        checks.append(_status("warn" if any(error_values) else "info", "Host PCIe register snapshot",
                      f"Current {show(pcie['current_speed_gts'])} GT/s x{show(pcie['current_width'])} · "
                      f"Maximum {show(pcie['max_speed_gts'])} GT/s x{show(pcie['max_width'])}. "
                      f"Device / correctable / uncorrectable error status: {error_text}. "
                      "Latched error bits may be historical; they do not establish an active link failure.", source("HWREG.txt")))
    health_fields = ["outstanding_io", "pending_io", "ld_present", "ld_degraded", "ld_offline", "pd_disks",
                     "pd_failed", "pd_predictive", "mem_correctable", "mem_uncorrectable", "controller_resets", "discovery_errors"]
    present = sum(s[key] is not None for key in health_fields)
    notes = [
        "MegaRAID module format detected. Checks use this format's fields; MPI3 Summary/Cpu/IopBase fields are not assumed.",
        f"Parsed {present}/{len(health_fields)} format-specific health fields; field coverage is not a complete hardware diagnosis.",
        "Identity and drive state come from the current crashDump snapshot. TTY and event history may contain older firmware and drive states.",
        "An empty FW packageVersion or driverVersion=--NA-- is not reported; historical versions are not substituted.",
        "Host PCIe values, when available, use labelled HWREG configuration registers. Backend firmware link codes are not decoded as host-link speed.",
        "FaultCode is preserved as raw evidence, not treated as a crash verdict. Event T timestamps are relative and may restart after boot.",
        "This is a point-in-time snapshot; zero counters do not exclude earlier or intermittent faults.",
    ]
    missing = [key for key in health_fields if s[key] is None]
    if missing:
        notes.insert(1, "Fields not reported by the supplied logs: " + ", ".join(missing) + ".")
    if standalone:
        notes.insert(0, "Only a standalone text export was supplied; upload the full SnapDump ZIP for cross-file analysis.")
    return {"filename": filename, "file_count": len(files),
            "files": [{"name": name, "bytes": len(text.encode("utf-8"))} for name, text in sorted(files.items())],
            "format": {"id": "megaraid_legacy", "label": "MegaRAID module format"},
            "trigger": trigger or "Not reported", "firmware": firmware,
            "pcie": pcie,
            "snapshot": snapshot, "logical_drives": logical_drives, "physical_drives": physical_drives,
            "coverage": {"health_fields_present": present, "health_fields_expected": len(health_fields),
                         "missing_fields": missing, "complete": present == len(health_fields)},
            "checks": checks, "events": _event_summary(events), "notes": notes, "_file_text": files}


def analyze_snapdump(filename: str, data: bytes) -> dict[str, Any]:
    inventory: list[dict[str, Any]] = []
    files = _read_files(filename, data, inventory)
    result = _analyze_files(filename, files)
    enrich(result)
    skipped = [entry for entry in inventory if entry["status"] != "decoded text"]
    result["intake"] = {"archive_entries": len(inventory) if inventory else len(files),
                        "decoded_text_files": len(files), "unparsed_entries": skipped,
                        "limitation": "Only decoded text is analyzed. Binary traces and bundled utilities are inventoried without execution or decoding."}
    if skipped:
        result["notes"].append(f"{len(skipped)} archive entries are not decoded. Their presence does not establish a healthy controller; binary traces require a matching vendor decoder/string table.")
    return result


def _analyze_files(filename: str, files: dict[str, str]) -> dict[str, Any]:
    # A standalone export can be renamed or combine several sections. Search its
    # text for explicit field labels; never infer absent sections from its name.
    standalone = next(iter(files.values())) if not filename.lower().endswith(".zip") else ""
    crash_text = _find(files, "crashDump.txt") or standalone
    modern = bool(re.search(r"SNAPDUMPI_FAILURE_TYPE_", _find(files, "Summary.txt"))
                  or re.search(r"^\s*Ver Name\s*:", crash_text, re.M))
    legacy = bool(re.search(r"===SnapDump Generic Info Start===", crash_text, re.I)
                  or re.search(r"^Firmware version\s+\S+\s+built on\s+", crash_text, re.M)
                  or any(name.rsplit("/", 1)[-1].lower() in {"pl_module.txt", "nvram_module.txt"} for name in files))
    if legacy and not modern:
        return _analyze_legacy(filename, files, standalone)
    sections = ["Summary.txt", "CrashDump.txt", "Cpu.txt", "Nvram.txt", "PlBase.txt",
                "DmBase.txt", "IopBase.txt", "Encl.txt", "ControllerPEL.txt"]
    summary, crash, cpu, nvram, plbase, dm, iop, encl, controller_pel = [
        _find(files, name) or standalone for name in sections
    ]
    trigger = _first(r"(SNAPDUMPI_FAILURE_TYPE_[A-Z_]+)", summary + "\n" + crash, default="Unknown")
    outstanding = _number(r"Outstanding IOs:\s*(\d+)", summary)
    pending = _number(r"Pending IOs:\s*(\d+)", summary)
    active_tm = _number(r"Active TM Count:\s*(\d+)", summary)
    failed_io = _number(r"gDmIoFailedList Count:\s*(\d+)", summary)
    topo_error = _number(r"Topology Error Present\s*:\s*(\d+)", dm)
    topo_critical = _number(r"Is Topo Error Critical\s*:\s*(\d+)", dm)
    hw_errors = _number(r"Num HW Errors\s*:\s*(\d+)", plbase)
    hard_resets = _number(r"Num Hard Resets\s*:\s*(\d+)", plbase)
    discovery_errors = _number(r"SAS Device Discovery Error Event Counter\s*:\s*(\d+)", plbase)
    hex_value = r"((?:0x)?[0-9A-Fa-f]+)\b"
    failed_por = _number(r"FailedPorCount:\s*" + hex_value, nvram, base=16)
    failed_hip = _number(r"FailedHipCount:\s*" + hex_value, nvram, base=16)
    ioc_values = _all_numbers(r"IocFaultCode\s*(?:[:=]\s*)?" + hex_value, iop, base=16)
    ioc_faults = sorted({f"0x{value:X}" for value in ioc_values if value})
    firmware = {
        "version": _first(r"^[ \t]*Ver Name[ \t]*:[ \t]*([^\r\n]+)", crash),
        "package": _first(r"Package Ver Name:[ \t]*([^\r\n]*)", crash),
        "driver": _first(r"Driver Ver[ \t]*:[ \t]*([^\r\n]*)", crash),
        "build_date": _first(r"BuildDate[ \t]*:[ \t]*([^\r\n]*)", crash),
        "release_level": _first(r"Release Level:[ \t]*([^\r\n]*)", crash),
        "board": _first(r"BoardName:[ \t]*([^\r\n]*)", crash + "\n" + summary),
        "personality": _first(r"current personality\s+([^\r\n]+)", crash),
        "operation_mode": _first(r"current fwOpMode\s+([^\r\n]+)", crash),
        "runtime_lines": re.findall(r"Firmware is running in [^\r\n]+", crash, re.I),
        "mode_name": _first(r"^FwMode:[ \t]*(\S+)", summary),
    }
    pcie = {
        "max_speed_code": _first(r"\bmaxPciLinkSpeed=([^\s]+)", crash),
        "max_width": _number(r"\bmaxPortWidth=(\d+)", crash),
        "current_speed_code": _first(r"\bcurrentPciLinkSpeed=([^\s]+)", crash),
        "current_width": _number(r"\bcurrentPortWidth=(\d+)", crash),
    }
    cpu_no_fault = bool(re.search(r"not due to any Fault", cpu, re.I))
    nonproduction = bool(
        re.search(r"ALPHA|BETA", firmware["release_level"], re.I)
        or re.search(r"not intended for production", crash + controller_pel, re.I)
    )

    def show(value: int | None) -> str:
        return str(value) if value is not None else "Unknown"

    def observed_zero(*values: int | None) -> str:
        return "ok" if all(value == 0 for value in values) else "info"

    checks = [
        _status(observed_zero(outstanding, pending), "I/O queues",
                f"Outstanding {show(outstanding)} · Pending {show(pending)}. "
                "Queue activity alone does not establish an I/O fault.", "Summary.txt"),
        _status("critical" if failed_io else "warn" if active_tm else observed_zero(active_tm, failed_io),
                "Task management and failed I/O",
                f"Active TM {show(active_tm)} · Failed list {show(failed_io)}. "
                "Active task management requires context about recovery progress.", "Summary.txt"),
        _status("critical" if topo_critical else "warn" if topo_error else observed_zero(topo_error, topo_critical),
                "Topology state", f"Topology error {show(topo_error)} · Critical {show(topo_critical)}", "DmBase.txt"),
        _status("warn" if any(value for value in (hw_errors, hard_resets, discovery_errors))
                else observed_zero(hw_errors, hard_resets, discovery_errors),
                "Hardware and discovery counters",
                f"HW errors {show(hw_errors)} · Hard resets {show(hard_resets)} · Discovery errors {show(discovery_errors)}. "
                "Nonzero counters can include historical events.", "PlBase.txt"),
        _status("warn" if nonproduction else "info", "Firmware release level",
                "ALPHA/BETA or nonproduction firmware markers found; confirm the supported release."
                if nonproduction else f"Release level: {firmware['release_level'] or 'Unknown'}. "
                "No nonproduction marker was found; this does not establish production support.",
                "CrashDump.txt / ControllerPEL.txt"),
        _status("ok" if cpu_no_fault else "info", "Snapshot trigger",
                "The CPU log explicitly states that this snapshot was not triggered by a fault."
                if cpu_no_fault else "No explicit statement excluding a CPU fault was found.", "Cpu.txt"),
        _status("critical" if ioc_faults else "warn" if failed_por or failed_hip
                else observed_zero(failed_por, failed_hip, max(ioc_values) if ioc_values else None),
                "NVRAM / IOC fault",
                f"Failed POR {show(failed_por)} · Failed HIP {show(failed_hip)} · IOC faults "
                f"{', '.join(ioc_faults) if ioc_faults else 'None observed' if ioc_values else 'Unknown'}. "
                "POR/HIP counters can include historical failures.", "Nvram.txt / IopBase.txt"),
    ]
    health_values = [outstanding, pending, active_tm, failed_io, topo_error, topo_critical,
                     hw_errors, hard_resets, discovery_errors, failed_por, failed_hip,
                     max(ioc_values) if ioc_values else None]
    health_names = ["outstanding_io", "pending_io", "active_tm", "failed_io", "topology_error", "topology_critical",
                    "hw_errors", "hard_resets", "discovery_errors", "failed_por", "failed_hip", "ioc_faults"]
    counts_text = _first(r"^Ld/PD device counts:[ \t]*\r?\n([\s\S]*?)(?=^Adapter Status:|\Z)", crash)
    counts = {}
    physical_drives = []
    mode = operating_mode(files, bool(standalone)) if modern else {}
    if modern and counts_text and mode.get("raid_counts_applicable"):
        labels = {"ld_present": "ldPresentCnt", "ld_degraded": "ldDegradedCnt", "ld_offline": "ldOfflineCnt",
                  "pd_disks": "pdDiskPresentCnt", "pd_failed": "pdDiskFailedCnt", "pd_predictive": "pdDiskPredFailureCnt"}
        if mode.get("external_ddr_applicable"):
            labels.update(mem_correctable="memCorrectableErrCnt", mem_uncorrectable="memUnCorrectableErrCnt")
        counts = {key: _number(r"\b" + label + r"\s*=\s*" + hex_value, counts_text, base=16)
                  for key, label in labels.items()}
        health_names.extend(counts)
        health_values.extend(counts.values())
        checks.extend([
            _status("critical" if counts["ld_offline"] else "warn" if counts["ld_degraded"] else
                    observed_zero(counts["ld_degraded"], counts["ld_offline"]), "Logical drive state",
                    f"Present {show(counts['ld_present'])} · Degraded {show(counts['ld_degraded'])} · Offline {show(counts['ld_offline'])}. "
                    "These are controller counts; per-volume state is not decoded from packed RAID registers.", "CrashDump.txt"),
            _status("critical" if counts["pd_failed"] else "warn" if counts["pd_predictive"] else
                    observed_zero(counts["pd_failed"], counts["pd_predictive"]), "Physical disk state",
                    f"Disks {show(counts['pd_disks'])} · Failed {show(counts['pd_failed'])} · Predictive failure {show(counts['pd_predictive'])}.", "CrashDump.txt"),
        ])
        if "mem_correctable" in counts:
            checks.append(_status("critical" if counts["mem_uncorrectable"] else "warn" if counts["mem_correctable"] else
                    observed_zero(counts["mem_correctable"], counts["mem_uncorrectable"]), "Memory error counters",
                    f"Correctable {show(counts['mem_correctable'])} · Uncorrectable {show(counts['mem_uncorrectable'])}. "
                    "Counters may include historical events.", "CrashDump.txt"))
        physical_drives = _physical_drives(_find(files, "Pd.txt") or standalone)
        if physical_drives:
            pd_counters = [item[key] for item in physical_drives for key in ("media_errors", "other_errors", "predictive_failures")]
            checks.append(_status("warn" if any(pd_counters) else observed_zero(*pd_counters), "Physical disk error counters",
                          "; ".join(f"PD {item['id']}: media {show(item['media_errors'])}, other {show(item['other_errors'])}, "
                                    f"predictive {show(item['predictive_failures'])}" for item in physical_drives[:32]) +
                          ". Counters may include historical events.", "Pd.txt"))
    slot_tokens = re.findall(r"\binUseSlotCount:[ \t]*((?:0x)?[0-9a-f]+)\b", encl, re.I)
    slot_counts = [int(token, 16 if token.lower().startswith("0x") or re.search(r"[a-f]", token, re.I) else 10)
                   for token in slot_tokens]
    present = sum(value is not None for value in health_values)
    missing = [name for name, value in zip(health_names, health_values) if value is None]
    notes = [
        "Findings use explicit text evidence. Missing fields remain unknown and cannot establish a healthy controller.",
        "The name CrashDump.txt does not establish a crash; inspect the trigger and CPU evidence.",
        "PCIe speed values are raw firmware codes, not decoded GT/s. Backend pciLinkSpeed is not the current host link.",
        "This is a point-in-time snapshot; zero counters do not exclude earlier or intermittent faults.",
        "Mapped slots is the highest reported enclosure inUseSlotCount, not a total disk count; raw slot tokens are retained.",
    ]
    if counts_text:
        notes.append("MPI3 RAID controller counts use the dump's hexadecimal Cnt fields. Packed per-volume RAID states are not inferred.")
    if missing:
        notes.append("Fields not reported by the supplied logs: " + ", ".join(missing) + ".")
    if present < len(health_values):
        notes.insert(0, f"Insufficient evidence for a complete health assessment: {present}/{len(health_values)} health fields are present.")
    if standalone:
        notes.insert(0, "Only a standalone text export was supplied; upload the full SnapDump ZIP for cross-file analysis.")
        for check in checks:
            check["evidence"] = filename or "SnapDump.txt"
    return {
        "filename": filename,
        "format": {"id": "mpi3" if modern else "unrecognized",
                   "label": "MPI3 section format" if modern else "Unrecognized / partial text format"},
        "file_count": len(files),
        "files": [{"name": name, "bytes": len(text.encode("utf-8"))} for name, text in sorted(files.items())],
        "trigger": trigger,
        "firmware": firmware,
        "pcie": pcie,
        "snapshot": {
            "outstanding_io": outstanding, "pending_io": pending, "active_tm": active_tm,
            "failed_io": failed_io, "topology_error": topo_error, "topology_critical": topo_critical,
            "hw_errors": hw_errors, "hard_resets": hard_resets, "discovery_errors": discovery_errors,
            "failed_por": failed_por, "failed_hip": failed_hip, "ioc_faults": ioc_faults,
            "cpu_no_fault": cpu_no_fault,
            "pd_state": _first(r"PD STATE\s*\r?\n([\s\S]{0,180}?)(?:\r?\n\r?\n|-------------)", summary).strip(),
            "mapped_slots": max(slot_counts) if slot_counts else None,
            "mapped_slots_raw": slot_tokens,
            **counts,
        },
        "physical_drives": physical_drives,
        "coverage": {"health_fields_present": present, "health_fields_expected": len(health_values),
                     "missing_fields": missing, "complete": present == len(health_values)},
        "checks": checks,
        "events": _event_summary(controller_pel),
        "notes": notes,
        "_file_text": files,
    }


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    """Strip raw text before returning the main JSON response."""
    return {key: value for key, value in result.items() if key != "_file_text"}
