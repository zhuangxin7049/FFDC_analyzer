"""Evidence-grounded Lenovo CFF PSU log decoding.

The field positions and v4/v5 split are based on the supplied CFF PSU
specifications and the accompanying spec-to-log comparison guide.  Raw bytes
are retained for every decoded record; fields without an explicit conversion
stay raw instead of being guessed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path


V4_MODELS = {"sr650v3", "sr630v3", "sr665v3", "sr645v3", "sr655v3", "sr635v3"}
V5_MODELS = {"sr650v4", "sr630v4"}
PSU_LOG_INFO_NAMES = {"psu_log_info", "psu_log_info.txt", "psu_log_info.log"}
PSU_DUMP_NAMES = {"psu_dump.log", "psu_dump.txt"}
HEX_RE = re.compile(r"(?<![0-9A-Fa-f])(?:0x)?([0-9A-Fa-f]{2})(?![0-9A-Fa-f])")
INT_RE = re.compile(r"(?<![A-Za-z0-9])(?:0x[0-9A-Fa-f]+|\d+)(?![A-Za-z0-9])")
D0_RE = re.compile(
    r"(?:Time:\s*(?P<timestamp>[^|]+)\|\s*)?(?:(?P<psu>PSU\d+)\s*\|\s*)?D0h\s*:\s*(?P<bytes>[0-9A-Fa-f\s]+)$",
    re.I,
)
D2_RE = re.compile(
    r"(?:Time:\s*(?P<timestamp>[^|]+)\|\s*)?(?:(?P<psu>PSU\d+)\s*\|\s*)?D2h\s*:\s*(?P<bytes>[0-9A-Fa-f\s]+)$",
    re.I,
)


def _hex_bytes(text):
    return [int(value, 16) for value in re.findall(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{2})(?![0-9A-Fa-f])", str(text or ""))]


def _raw(values):
    return " ".join(f"{value:02X}" for value in values)


def _model_text(system):
    if isinstance(system, dict):
        return " ".join(str(system.get(key, "")) for key in ("type_model", "model", "machine_type", "product"))
    return str(system or "")


def select_platform(system, source_format, text=""):
    model = _model_text(system).lower()
    if any(item in model for item in V5_MODELS):
        return {"family": "v5", "basis": "platform model", "inferred": False}
    if any(item in model for item in V4_MODELS):
        return {"family": "v4", "basis": "platform model", "inferred": False}
    if source_format == "psu_dump.log":
        return {"family": "v5", "basis": "psu_dump.log uses the supplied v5 fixed-record layout", "inferred": True}
    if re.search(r"SR650V4|SR630V4", text or "", re.I):
        return {"family": "v5", "basis": "platform text in source", "inferred": True}
    if re.search(r"SR650V3|SR630V3|SR665V3|SR645V3|SR655V3|SR635V3", text or "", re.I):
        return {"family": "v4", "basis": "platform text in source", "inferred": True}
    return {"family": "v4", "basis": "psu_log_info defaulted to v4 until a platform or v5 dump identity is available", "inferred": True}


def decode_d0(values):
    values = list(values)
    result = {"raw": _raw(values), "valid_length": len(values) >= 18}
    if len(values) < 18:
        result["limitations"] = [f"D0h has {len(values)} byte(s); 18 byte(s) are required by the supplied specification."]
        return result
    month, day, year = values[:3]
    result.update({
        "date_raw": _raw(values[:3]),
        "date": f"{2000 + year:04d}-{month:02d}-{day:02d}" if 1 <= month <= 12 and 1 <= day <= 31 else "",
        "date_rule": "MM DD YY",
        "hc_group_1": _raw(values[3:7]),
        "pokwh_raw": _raw(values[7:11]),
        "hc_group_2": _raw(values[11:15]),
        "cycle_count_raw": _raw(values[15:17]),
        "key": f"{values[17]:02X}",
    })
    if not result["date"]:
        result["limitations"] = ["D0h date bytes are outside the documented MM/DD/YY range; the raw bytes are retained."]
    return result


def _status_maps(family):
    byte7 = [
        (7, "VOUT_OV_FAULT", "7Ah", "fault"),
        (6, "VOUT_UV_FAULT", "7Ah", "fault"),
        (5, "VIN_OV_FAULT", "7Ch", "fault"),
        (4, "VIN_OV_WARNING", "7Ch", "warning"),
        (3, "VIN_UV_WARNING", "7Ch", "warning"),
        (2, "VIN_UV_FAULT", "7Ch", "fault"),
        (1, "IIN_OC_FAULT", "7Ch", "fault"),
        (0, "IIN_OC_WARNING", "7Ch", "warning"),
    ]
    byte8 = [
        (7, "IOUT_OC_FAULT", "7Bh", "fault"),
        (6, "IOUT_OC_WARNING", "7Bh", "warning"),
        (5, "OT_FAULT", "7Dh", "fault"),
        (4, "OT_WARNING", "7Dh", "warning"),
        (3, "FAN_1_FAULT", "81h", "fault"),
        (2, "FAN_2_FAULT", "81h", "fault"),
        (1, "FAN_1_WARNING" if family == "v4" else "81h_BIT5_RESERVED", "81h", "warning" if family == "v4" else "reserved"),
        (0, "FAN_2_WARNING" if family == "v4" else "81h_BIT4_RESERVED", "81h", "warning" if family == "v4" else "reserved"),
    ]
    if family == "v4":
        byte9 = [
            (7, "CURRENT_SHARE_WARNING", "80h", "warning"),
            (6, "OVERSUBSCRIPTION_FAULT", "80h", "fault"),
            (5, "ORING_FET_FAULT", "80h", "fault"),
            (4, "INTERNAL_OVERCURRENT_FAULT", "80h", "fault"),
            (3, "PFC_BULK_OV_FAULT", "80h", "fault"),
            (2, "ZERO_WAKE_UP_HEAVY_LOAD", "80h", "warning"),
            (1, "80h_BIT1_RESERVED", "80h", "reserved"),
            (0, "80h_BIT0_RESERVED", "80h", "reserved"),
        ]
    else:
        byte9 = [
            (7, "CURRENT_SHARE_WARNING", "7Bh", "warning"),
            (6, "OUTPUT_ORING_DEVICE_FAULT", "7Fh", "fault"),
            (5, "OVERSUBSCRIPTION_FAULT", "80h", "fault"),
            (4, "VSENSE_SHORT_WARNING", "80h", "warning"),
            (3, "INTERNAL_OVERCURRENT_FAULT", "80h", "fault"),
            (2, "PFC_BULK_OV_FAULT", "80h", "fault"),
            (1, "ZERO_WAKE_UP_HEAVY_LOAD", "80h", "warning"),
            (0, "80h_BIT0_RESERVED", "80h", "reserved"),
        ]
    byte10 = [
        (7, "VIRTUAL_RESEAT_ACTIVE", "E3h", "info"),
        (6, "VIRTUAL_RESEAT_FAULT", "E3h", "fault"),
        (5, "UNSUPPORTED_COMMAND", "7Eh", "protocol"),
        (4, "UNSUPPORTED_DATA", "7Eh", "protocol"),
        (3, "PEC_FAILED", "7Eh", "protocol"),
        (2, "7Eh_BIT4_RESERVED", "7Eh", "reserved"),
        (1, "7Eh_BIT3_RESERVED", "7Eh", "reserved"),
        (0, "7Eh_BIT2_RESERVED", "7Eh", "reserved"),
    ]
    return (byte7, byte8, byte9, byte10)


def decode_status_bytes(status, family):
    maps = _status_maps(family)
    active = []
    definitions = []
    for offset, value in enumerate(status[:4]):
        for bit, name, register, kind in maps[offset]:
            item = {"byte": offset + 7, "raw_byte": f"{value:02X}", "bit": bit, "name": name, "register": register, "kind": kind}
            definitions.append(item)
            if value & (1 << bit) and kind != "reserved":
                active.append({**item, "severity": "Critical" if kind == "fault" else "Warning" if kind == "warning" else "Info"})
    return active, definitions


def decode_d2(values, family, record_number=None, timestamp_raw=None):
    values = list(values)
    result = {"raw": _raw(values), "record_number": record_number, "valid_length": len(values) >= (30 if family == "v5" and record_number is not None else 25)}
    required = 30 if family == "v5" and record_number is not None else 25
    if len(values) < required:
        result["limitations"] = [f"D2h record has {len(values)} byte(s); {required} byte(s) are required for the selected layout."]
        return result
    status = values[6:10]
    active, definitions = decode_status_bytes(status, family)
    result.update({
        "hc1": f"{values[0]:02X}", "hc2": f"{values[1]:02X}", "dcr": f"{values[2]:02X}",
        "f5": f"{values[3]:02X}", "error_count_raw": _raw(values[4:6]),
        "status_bytes": _raw(status), "status_definitions": definitions, "active_flags": active,
        "vbulk_raw": _raw(values[10:12]), "vbulk_volts": int.from_bytes(bytes(values[10:12]), "little"),
        "read_iout_raw": _raw(values[12:14]),
        "temperature_1_raw": _raw(values[14:16]), "temperature_2_raw": _raw(values[16:18]),
        "temperature_3_raw": _raw(values[18:20]), "fan_speed_1_raw": _raw(values[20:22]),
        "fan_speed_2_raw": _raw(values[22:24]),
        "key": f"{values[29 if family == 'v5' and record_number is not None else 24]:02X}",
    })
    if family == "v5" and record_number is not None:
        result["reserved_raw"] = _raw(values[22:25])
        stamp = int.from_bytes(bytes(values[25:29]), "little")
        result["system_timestamp_raw"] = _raw(values[25:29])
        result["system_timestamp_utc"] = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if 946684800 <= stamp <= 4102444800 else ""
    if timestamp_raw:
        result["source_timestamp"] = timestamp_raw.strip()
    return result


def _line_record(psu, kind, line_number, raw_line, values, timestamp=""):
    return {"psu": psu, "kind": kind, "line": line_number, "raw_line": raw_line.rstrip("\n"), "values": values, "timestamp": timestamp}


def parse_psu_log_info(text, family, source):
    psus = {}
    current = ""
    for line_number, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        match = D0_RE.match(line)
        kind = "D0h"
        if not match:
            match = D2_RE.match(line)
            kind = "D2h"
        if not match:
            continue
        psu = (match.group("psu") or current or "PSU?").upper()
        current = psu
        values = _hex_bytes(match.group("bytes"))
        psus.setdefault(psu, []).append(_line_record(psu, kind, line_number, raw, values, match.group("timestamp") or ""))
    result_psus = []
    for psu in sorted(psus, key=lambda value: (value == "PSU?", value)):
        records = psus[psu]
        d0 = next((row for row in records if row["kind"] == "D0h"), None)
        d2 = [row for row in records if row["kind"] == "D2h"]
        decoded = []
        if d0:
            decoded.append({"kind": "D0h", "line": d0["line"], "raw_line": d0["raw_line"], "decoded": decode_d0(d0["values"])})
        for row in d2:
            decoded.append({"kind": "D2h", "line": row["line"], "raw_line": row["raw_line"], "decoded": decode_d2(row["values"], family)})
        result_psus.append({
            "name": psu, "format": "psu_log_info", "source": source, "records": decoded,
            "first_four": decoded[:4], "d0_present": bool(d0), "d2_count": len(d2),
            "active_flags": [flag for item in decoded if item["kind"] == "D2h" for flag in item["decoded"].get("active_flags", [])],
        })
    return result_psus


def _numeric_sections(text):
    chunks = re.split(r"a\{qay\}", str(text or ""), flags=re.I)
    return [chunk for chunk in chunks[1:] if chunk.strip()]


def parse_psu_dump(text, family, source):
    result_psus = []
    for index, chunk in enumerate(_numeric_sections(text), 1):
        numbers = []
        for match in INT_RE.finditer(chunk):
            token = match.group(0)
            try:
                value = int(token, 0)
            except ValueError:
                continue
            if 0 <= value <= 255:
                numbers.append(value)
        records = []
        positions = [pos for pos in range(max(0, len(numbers) - 3)) if numbers[pos:pos + 4][:2] == [0, 0] and numbers[pos + 3] == 0x20]
        for pos in positions:
            if len(numbers) < pos + 34:
                continue
            record_number = numbers[pos + 2]
            payload = numbers[pos + 4:pos + 34]
            records.append({
                "kind": "D2h", "record_number": record_number,
                "raw_line": _raw(numbers[pos:pos + 34]),
                "decoded": decode_d2(payload, "v5", record_number=record_number),
            })
        result_psus.append({
            "name": f"PSU{index}", "format": "psu_dump.log", "source": source,
            "records": records, "first_four": records[:4], "record_count": len(records),
            "active_flags": [flag for item in records for flag in item["decoded"].get("active_flags", [])],
            "header_bytes": _raw(numbers[:35]),
        })
    return result_psus


def _source_kind(path):
    name = Path(path).name.lower()
    if name in PSU_DUMP_NAMES or "psu_dump" in name:
        return "psu_dump.log"
    if name in PSU_LOG_INFO_NAMES or "psu_log_info" in name:
        return "psu_log_info"
    return ""


def discover_psu_sources(extract_dir):
    found = []
    root = Path(extract_dir)
    if not root.is_dir():
        return found
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        kind = _source_kind(path)
        if kind:
            found.append((path, kind))
    return sorted(found, key=lambda item: str(item[0]).lower())


def _finding_for_flag(flag):
    kind = flag.get("kind")
    if kind == "fault":
        severity = "Critical"
        conclusion = f"PSU status bit {flag['name']} is asserted in composite D2h byte {flag['byte']} (raw {flag['raw_byte']})."
    elif kind == "warning":
        severity = "Warning"
        conclusion = f"PSU warning bit {flag['name']} is asserted in composite D2h byte {flag['byte']} (raw {flag['raw_byte']})."
    elif kind == "protocol":
        severity = "Warning"
        conclusion = f"PSU protocol/communication flag {flag['name']} is asserted; this is not by itself an electrical power fault."
    else:
        severity = "Info"
        conclusion = f"PSU status flag {flag['name']} is asserted; interpret it with the selected specification and timeline."
    return {"severity": severity, "title": flag["name"], "conclusion": conclusion, "evidence": f"D2h byte {flag['byte']} bit {flag['bit']} = 1; source register {flag['register']}"}


def analyze_psu_logs(extract_dir, system=None):
    sources = discover_psu_sources(extract_dir)
    if not sources:
        return {"available": False, "sources": [], "psus": [], "findings": [], "limitations": ["No psu_log_info or psu_dump.log source was collected."]}
    all_psus, findings, source_rows = [], [], []
    for path, source_format in sources:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            source_rows.append({"path": str(path.relative_to(extract_dir)), "format": source_format, "status": "unreadable", "error": str(exc)})
            continue
        platform = select_platform(system, source_format, text)
        if source_format == "psu_log_info":
            psus = parse_psu_log_info(text, platform["family"], str(path.relative_to(extract_dir)))
        else:
            psus = parse_psu_dump(text, "v5", str(path.relative_to(extract_dir)))
        all_psus.extend(psus)
        source_rows.append({"path": str(path.relative_to(extract_dir)), "format": source_format, "status": "parsed", "platform": platform})
        for psu in psus:
            for flag in psu.get("active_flags", []):
                finding = _finding_for_flag(flag)
                finding["psu"] = psu["name"]
                finding["source"] = psu["source"]
                findings.append(finding)
    limitations = []
    if any(item.get("format") == "psu_dump.log" and not item.get("records") for item in all_psus):
        limitations.append("A psu_dump.log source was found, but no documented 00 00 <record number> 20 fixed-record envelope was recognized; raw numeric evidence was retained without inventing records.")
    if any(row.get("platform", {}).get("inferred") for row in source_rows):
        limitations.append("PSU v4/v5 selection was inferred from the source format or log text; provide the server model to confirm the baseline.")
    limitations.append("READ_IOUT, temperature, and fan values remain raw because the supplied comparison guide does not define a universal conversion for them.")
    limitations.append("PSU status records are point-in-time evidence; they do not by themselves establish current hardware health.")
    return {
        "available": bool(all_psus), "source_count": len(source_rows), "sources": source_rows,
        "platforms": sorted({row.get("platform", {}).get("family") for row in source_rows if row.get("platform")}),
        "psus": all_psus, "findings": findings,
        "limitations": limitations,
        "spec_baseline": "CFF Power Supply v4 Rev. 3.1 / v5 Rev. 2.4 and supplied spec-to-log comparison guide",
    }


def analyze_standalone_psu_log(text, source_path="psu_log_info"):
    """Decode a directly uploaded PSU log without requiring a full FFDC archive."""
    source_format = "psu_dump.log" if "psu_dump" in Path(source_path).name.lower() else "psu_log_info"
    platform = select_platform({}, source_format, text)
    psus = parse_psu_dump(text, "v5", source_path) if source_format == "psu_dump.log" else parse_psu_log_info(text, platform["family"], source_path)
    findings = []
    for psu in psus:
        for flag in psu.get("active_flags", []):
            finding = _finding_for_flag(flag)
            finding["psu"] = psu["name"]
            finding["source"] = source_path
            findings.append(finding)
    limitations = []
    if source_format == "psu_dump.log" and any(not item.get("records") for item in psus):
        limitations.append("A psu_dump.log source was found, but no documented 00 00 <record number> 20 fixed-record envelope was recognized; raw numeric evidence was retained without inventing records.")
    limitations.extend([
        "Platform selection was inferred because the standalone upload did not include a server model.",
        "READ_IOUT, temperature, and fan values remain raw because the supplied comparison guide does not define a universal conversion for them.",
        "PSU status records are point-in-time evidence; they do not by themselves establish current hardware health.",
    ])
    return {
        "available": True, "source_count": 1, "sources": [{"path": source_path, "format": source_format, "status": "parsed", "platform": platform}],
        "platforms": [platform["family"]], "psus": psus, "findings": findings, "limitations": limitations,
        "spec_baseline": "CFF Power Supply v4 Rev. 3.1 / v5 Rev. 2.4 and supplied spec-to-log comparison guide",
    }
