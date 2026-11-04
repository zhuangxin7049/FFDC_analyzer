"""Deterministic decoder for Hydra/Santorini/Troy FPGA block dumps.

The downloaded skill contains a large platform specification.  This module keeps
the high-confidence, common fields in code and preserves the original block and
source-line evidence so a later detailed decoder can be added without changing
the report contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


BLOCK_RE = re.compile(r"^\s*Block\s+(?P<block>[0-9A-Fa-f]{1,3})\s*[-:]\s*(?P<body>.*)$", re.I)
HEX_RE = re.compile(r"(?<![0-9A-Fa-f])(?:0x)?(?P<byte>[0-9A-Fa-f]{2})(?![0-9A-Fa-f])")

PROJECTS = {
    0x00: ("Hydra", "Hydra 1U SR630 V4", "Hydra/Santorini_FPGA_Spec.md"),
    0x01: ("Santorini", "Santorini 2U SR650 V4", "Hydra/Santorini_FPGA_Spec.md"),
    0x0C: ("Troy", "Troy SR450 V4", "Troy_FPGA_Spec.md"),
}


def _hex(value: int) -> str:
    return f"0x{value:02X}"


def _bcd(value: int) -> int | None:
    hi, lo = value >> 4, value & 0xF
    if hi > 9 or lo > 9:
        return None
    return hi * 10 + lo


def _row(item: str, value: Any, block: int | None = None, offset: int | None = None, path: str = "", line: int | None = None) -> dict[str, Any]:
    result = {"item": item, "value": value}
    evidence = []
    if block is not None and offset is not None:
        evidence.append(f"Block {block} offset {offset:02X}h={_hex(value) if isinstance(value, int) else value}")
    if path and line:
        evidence.append(f"{path}:{line}")
    if evidence:
        result["evidence"] = " | ".join(evidence)
    return result


def parse_fpga_blocks(text: str, source_path: str = "") -> dict[str, Any]:
    """Parse raw Block lines and decode high-confidence common fields.

    Missing blocks and malformed/truncated lines remain explicit in ``warnings``;
    a missing block is never converted into an all-zero value.
    """
    blocks: dict[int, dict[str, Any]] = {}
    warnings: list[str] = []
    for line_no, line in enumerate((text or "").splitlines(), start=1):
        match = BLOCK_RE.match(line)
        if not match:
            continue
        block = int(match.group("block"), 16)
        values = [int(m.group("byte"), 16) for m in HEX_RE.finditer(match.group("body"))]
        # The format is 16 bytes split by a dash.  Do not accept adjacent
        # address/ASCII material as data, and retain the original evidence.
        if len(values) < 16:
            warnings.append(f"Block {block} line {line_no} has {len(values)} byte(s); expected 16")
            continue
        if len(values) > 16:
            values = values[:16]
        blocks[block] = {"values": values, "line": line_no, "raw": line.rstrip("\n")}

    if not blocks:
        return {}

    def get(block: int, offset: int) -> int | None:
        entry = blocks.get(block)
        if not entry or offset >= len(entry["values"]):
            return None
        return entry["values"][offset]

    device_id = get(0, 0)
    project_id = get(1, 7)
    project = PROJECTS.get(project_id)
    supported_device = device_id == 0x40
    supported_project = project is not None
    platform = project[0] if project else "Unsupported"
    model = project[1] if project else "Unsupported / unidentified project"
    if device_id is None:
        warnings.append("Block 0 is missing; device identity is unavailable")
    elif not supported_device:
        warnings.append(f"Device ID {_hex(device_id)} is outside the downloaded Hydra/Santorini/Troy rules")
    if project_id is None:
        warnings.append("Block 1 is missing or has no Project ID at offset 07h")
    elif not supported_project:
        warnings.append(f"Project ID {_hex(project_id)} is outside the downloaded Hydra/Santorini/Troy rules")

    summary: list[dict[str, Any]] = []
    if device_id is not None:
        summary.append(_row("Device ID", _hex(device_id), 0, 0, source_path, blocks[0]["line"] if 0 in blocks else None))
    if project_id is not None:
        summary.append(_row("Project ID", _hex(project_id), 1, 7, source_path, blocks[1]["line"] if 1 in blocks else None))
    summary.append({"item": "Platform", "value": model, "evidence": project[2] if project else "unsupported project; no platform-specific fields applied"})

    fw_major, fw_minor = get(0, 1), get(0, 2)
    if fw_major is not None and fw_minor is not None:
        major, minor = _bcd(fw_major), _bcd(fw_minor)
        version = f"v{major}.{minor:02d}" if major is not None and minor is not None else f"{_hex(fw_major)}.{_hex(fw_minor)} (non-BCD)"
        summary.append(_row("FPGA Firmware", version, 0, 1, source_path, blocks[0]["line"]))
    build = [_bcd(get(0, x)) if get(0, x) is not None else None for x in (4, 5, 6)]
    if all(x is not None for x in build):
        summary.append(_row("Build Date", f"{2000 + build[2]:04d}-{build[0]:02d}-{build[1]:02d}", 0, 4, source_path, blocks[0]["line"]))
    family = get(0, 3)
    if family is not None:
        summary.append(_row("FPGA Family", _hex(family), 0, 3, source_path, blocks[0]["line"]))
    interface = get(0, 7)
    if interface is not None:
        summary.append(_row("Interface", f"v{interface >> 4}.x" if interface >> 4 == 3 else _hex(interface), 0, 7, source_path, blocks[0]["line"]))
    hw_version = get(1, 9)
    if hw_version is not None:
        summary.append(_row("HW Version", str(hw_version), 1, 9, source_path, blocks[1]["line"]))
    wipe = get(1, 10)
    if wipe is not None:
        summary.append(_row("Platform Wipe", "secure-boot host lock armed" if wipe & 0x80 else "not armed", 1, 10, source_path, blocks[1]["line"]))

    status: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    def evidence(block: int, offset: int) -> str:
        entry = blocks.get(block, {})
        line = entry.get("line")
        value = get(block, offset)
        return f"Block {block} offset {offset:02X}h={_hex(value) if value is not None else 'missing'}" + (f" ({source_path}:{line})" if source_path and line else "")

    power_faults = []
    for block in (4, 5):
        for offset in range(1, 9):
            value = get(block, offset)
            if value:
                power_faults.append((block, offset, value))
    if get(4, 0) is not None or get(5, 0) is not None:
        status.append({"item": "Power Faults", "value": "; ".join(f"B{b} {o:02X}h={_hex(v)}" for b, o, v in power_faults) if power_faults else "None"})
    if power_faults:
        findings.append({"severity": "Critical", "title": "FPGA power fault detected", "conclusion": "Block 4/5 contains one or more asserted power-fault bits. Downstream power-good zeros may be cascade side effects and must not be reported as independent faults.", "evidence": "; ".join(evidence(b, o) for b, o, _ in power_faults)})
    else:
        status.append({"item": "Power Fault Cascade", "value": "No Block 4/5 power-fault bit asserted"})

    b6 = get(6, 0)
    if b6 is not None:
        status.append({"item": "Interrupts", "value": _hex(b6), "evidence": evidence(6, 0)})

    b10_08, b10_0b = get(10, 8), get(10, 11)
    if b10_08 is not None:
        status.append({"item": "UEFI Checkpoint", "value": _hex(b10_08), "evidence": evidence(10, 8)})
    if b10_0b is not None:
        status.append({"item": "BMC Progress", "value": _hex(b10_0b), "evidence": evidence(10, 11)})

    b11_02, b11_03 = get(11, 2), get(11, 3)
    if b11_02 is not None:
        power_state = {0b11: "S0", 0b00: "S5"}.get(b11_02 >> 6, "reserved/unknown")
        post = "POST complete" if b11_02 & 0x20 else "POST not complete"
        status.append({"item": "Run State", "value": f"{power_state}; {post}", "evidence": evidence(11, 2)})
    if b11_03 is not None and b11_03 & 0x03:
        findings.append({"severity": "Critical", "title": "Host fatal signal asserted", "conclusion": "Block 11 reports PCIe Fatal and/or CATERR. Correlate with Block 14 RAS and the original event timeline.", "evidence": evidence(11, 3)})
    elif b11_03 is not None:
        status.append({"item": "PCIe Fatal / CATERR", "value": "None asserted", "evidence": evidence(11, 3)})

    b14_01, b14_03, b14_05, b14_06, b14_07, b14_08 = [get(14, x) for x in (1, 3, 5, 6, 7, 8)]
    ras_faults = []
    for offset, value, label in ((1, b14_01, "thermal critical"), (3, b14_03, "thermal alert"), (5, b14_05, "power supply critical"), (6, b14_06, "CPU error capture"), (7, b14_07, "CPU error status"), (8, b14_08, "PCIe fatal")):
        if value:
            ras_faults.append((offset, value, label))
    if ras_faults:
        findings.append({"severity": "Critical", "title": "FPGA RAS event bits asserted", "conclusion": "Block 14 contains non-zero event/status bits. Capability offset 00h is not treated as a fault.", "evidence": "; ".join(evidence(14, o) + f" ({label})" for o, _, label in ras_faults)})
    elif any(x is not None for x in (b14_01, b14_03, b14_05, b14_06, b14_07, b14_08)):
        status.append({"item": "RAS events", "value": "No common thermal, power-supply, CPU, or PCIe event bits asserted", "evidence": evidence(14, 1)})

    b61_01, b61_02, b61_03, b61_0f = [get(61, x) for x in (1, 2, 3, 15)]
    if b61_01 is not None:
        status.append({"item": "Power Sequence Fault Latch", "value": _hex(b61_01), "evidence": evidence(61, 1)})
        if b61_01:
            findings.append({"severity": "Warning", "title": "Power sequence fault latch is non-zero", "conclusion": "Block 61 retains a power-sequence code. Decode it with the platform appendix and correlate with Block 4/5 before assigning a root cause.", "evidence": evidence(61, 1)})
    if b61_02 is not None and b61_02 & 0x03:
        findings.append({"severity": "Warning", "title": "Power fault type flags asserted", "conclusion": "Block 61 indicates a current or previous VR power fault; use Block 4/5 as the primary fault source.", "evidence": evidence(61, 2)})
    if b61_03 is not None:
        status.append({"item": "Power Sequence Address", "value": _hex(b61_03), "evidence": evidence(61, 3)})
    if b61_0f is not None:
        status.append({"item": "Fault LED Code", "value": _hex(b61_0f), "evidence": evidence(61, 15)})

    b63_00, b63_01 = get(63, 0), get(63, 1)
    if b63_00 is not None:
        if (b63_00 & 0xF0) != 0xF0:
            findings.append({"severity": "Warning", "title": "PSU PMBus alert or power-off fault bit asserted", "conclusion": "Block 63 offset 00h uses active-low PSU ALERT# bits; a zero in the PSU nibble is an alert. Low-nibble bits are fault flags.", "evidence": evidence(63, 0)})
        else:
            status.append({"item": "PSU PMBus / power-off flags", "value": "No common alert/fault bit asserted", "evidence": evidence(63, 0)})
    if b63_01 is not None and b63_01 & 0x03:
        findings.append({"severity": "Warning", "title": "Current CPU PVCCIN fault flag asserted", "conclusion": "Block 63 offset 01h low bits report a current CPU PVCCIN fault.", "evidence": evidence(63, 1)})

    if not (supported_device and supported_project):
        warnings.append("Platform-specific fault decoding was withheld because Device ID and Project ID did not identify a supported Hydra/Santorini/Troy platform")
        status = [{"item": "Decoder Scope", "value": "Identity/raw block evidence only; platform-specific conclusions withheld"}]
        findings = [{"severity": "Warning", "title": "Unsupported FPGA platform", "conclusion": "The downloaded rules were not applied to fault conclusions because the Device ID/Project ID combination is outside the supported Hydra/Santorini/Troy scope.", "evidence": "; ".join(warnings)}]
    elif not findings:
        findings.append({"severity": "Pass", "title": "No high-confidence FPGA fault finding", "conclusion": "The parsed common power, host fatal, RAS, power-sequence, and PSU fields contain no asserted fault condition.", "evidence": "Deterministic common-field decoder"})

    blocks_out = []
    for number, entry in sorted(blocks.items()):
        blocks_out.append({"block": number, "bytes": " ".join(f"{x:02X}" for x in entry["values"]), "line": entry["line"], "raw": entry["raw"]})
    return {
        "schema": 1,
        "source": source_path,
        "platform": platform,
        "model": model,
        "device_id": device_id,
        "project_id": project_id,
        "supported": supported_device and supported_project,
        "summary": summary,
        "status": status,
        "findings": findings,
        "warnings": warnings,
        "blocks": blocks_out,
        "block_count": len(blocks),
    }


def find_fpga_block_file(extract_dir: Path) -> Path | None:
    """Select the richest block-dump file from an extracted FFDC tree."""
    candidates = []
    for path in extract_dir.rglob("*"):
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            continue
        name = path.name.lower()
        if "fpga" not in name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_fpga_blocks(text, str(path.relative_to(extract_dir)))
        if parsed:
            candidates.append((parsed.get("block_count", 0), -len(parsed.get("warnings", [])), path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2])), reverse=True)
    return candidates[0][2]


def analyze_fpga_block_file(path: Path | None, extract_dir: Path | None = None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"schema": 1, "source": str(path), "warnings": [f"FPGA block log could not be read: {exc}"]}
    source = str(path.relative_to(extract_dir)) if extract_dir else str(path)
    return parse_fpga_blocks(text, source)
