"""Avenger text evidence, scoped to MPI3 exports; no vendor binaries are run.

Reference scope: user-supplied Avenger overview/debug (July 2025), drive
ordering (August 2025), and NVDATA overview (August 2025). These describe
formats and relationships, not a complete firmware-specific bit dictionary.
"""
from __future__ import annotations

from collections import Counter, deque
import hashlib
import re
from typing import Any

HEX = r"(?:0x)?[0-9a-f]+"


def _source(name: str, text: str, match: re.Match) -> dict[str, Any]:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    end = len(text) if end < 0 else end
    return {"name": name, "start_line": text.count("\n", 0, start) + 1,
            "end_line": text.count("\n", 0, end) + 1, "excerpt": text[start:end].rstrip("\r")}


def _file(files: dict[str, str], base: str) -> tuple[str, str]:
    matches = [(name, value) for name, value in files.items()
               if name.rsplit("/", 1)[-1].lower() == base.lower()]
    # Different controllers may have identically named files. Never silently join them.
    return matches[0] if len(matches) == 1 else ("", "")


def controller_identity(files: dict[str, str], standalone: bool = False) -> dict[str, Any]:
    """Select generation only from literal current board identity, never TTY history."""
    name, text = _file(files, "CrashDump.txt")
    if standalone:
        name, text = next(iter(files.items()))
    evidence, values = [], {}
    for label in ("ChipName", "BoardName", "BoardTracerNumber"):
        matches = list(re.finditer(r"^[ \t]*" + label + r":[ \t]*([^\r\n]+)", text, re.M | re.I))
        values[label] = sorted({m.group(1).strip() for m in matches})
        evidence.extend(_source(name, text, m) for m in matches[:8])
    chips = values["ChipName"]
    chip = chips[0].upper() if len(chips) == 1 else ""
    generation = "AV1" if re.fullmatch(r"SAS4\d{3}W?", chip) else "AV2" if re.fullmatch(r"SAS5\d{3}W", chip) else "Unverified"
    role = ("RoC" if re.fullmatch(r"SAS(?:41|51)\d{2}W?", chip) else
            "IOC" if re.fullmatch(r"SAS40\d{2}W?", chip) or chip == "SAS5032W" else "Unverified")
    return {"chip": chip or None, "generation": generation, "chip_role": role,
            "board": values["BoardName"][0] if len(values["BoardName"]) == 1 else None,
            "board_tracer": values["BoardTracerNumber"][0] if len(values["BoardTracerNumber"]) == 1 else None,
            "conflict": any(len(v) > 1 for v in values.values()), "evidence": evidence,
            "reference": "SAS4xxx-Controller-Differences-AN102 pp. 7-8, 24-25; SAS5xxxxW-FW-Diff-AN101 pp. 5-6",
            "limitation": "Generation follows the explicit snapshot ChipName, not firmware version, archive name or historical TTY. AV2 RoC integrated-cache and media restrictions do not describe SAS5032W IOC/HBA. Unknown chip roles remain unverified."}


def operating_mode(files: dict[str, str], standalone: bool = False) -> dict[str, Any]:
    identity = controller_identity(files, standalone)
    crash_name, crash = _file(files, "CrashDump.txt")
    summary_name, summary = _file(files, "Summary.txt")
    if standalone:
        crash_name, crash = next(iter(files.items()))
        summary_name, summary = crash_name, crash
    evidence = []

    def field(pattern: str, name: str, text: str) -> str:
        match = re.search(pattern, text, re.I | re.M)
        if not match:
            return ""
        evidence.append(_source(name, text, match))
        return match.group(1)

    personality = field(r"^current personality[ \t]+(" + HEX + r")\b", crash_name, crash)
    profile = field(r"^\s*OEM/ProfileIdentifier:[ \t]*[0-9a-f]+/(" + HEX + r")\b", crash_name, crash)
    if not profile:
        profile = field(r"^oem=[0-9a-f]+[ \t]+profileId=(" + HEX + r")\b", crash_name, crash)
    runtime = field(r"^FwMode:[ \t]*(IOPI_FW_OPMODE_[A-Z0-9_]+)\b", summary_name, summary)
    pairs = {(2, 0): "RAID", (0, 0): "PerfIT", (0, 3): "PerfIT", (0, 4): "PerfIT",
             (0, 1): "EVP", (0, 2): "FeatureHBA"}
    profile_table = identity["generation"] == "AV1" and not identity["conflict"]
    inferred = pairs.get((int(personality, 16), int(profile, 16))) if profile_table and personality and profile else None
    declared = {"IOPI_FW_OPMODE_RAID": "RAID", "IOPI_FW_OPMODE_PERFIT": "PerfIT",
                "IOPI_FW_OPMODE_EVP": "EVP", "IOPI_FW_OPMODE_FEATUREHBA": "FeatureHBA"}.get(runtime)
    conflict = bool(declared and inferred and declared != inferred)
    # Unknown runtime enums are not overridden by an older profile table.
    selected = None if conflict or identity["conflict"] or (runtime and not declared) else declared or inferred
    return {"name": selected or "Unverified", "personality": personality, "profile_id": profile,
            "runtime": runtime, "profile_interpretation": inferred, "conflict": conflict,
            "profile_table_applicable": profile_table,
            "external_ddr_applicable": selected == "RAID" and profile_table and identity["chip_role"] == "RoC",
            "raid_counts_applicable": selected in {"RAID", "EVP"}, "evidence": evidence,
            "basis": "Explicit snapshot FwMode; AV1-only personality/profile fallback after ChipName validation",
            "limitation": "AV1 profile enums are not decoded for AV2 or unidentified chips. External DDR checks require AV1 RoC RAID. Unknown combinations remain unverified. Historical TTY configuration candidates do not select the current mode."}


def host_functions(files: dict[str, str], standalone: bool = False) -> dict[str, Any]:
    """Inventory explicit IOC instances; these are not a physical-card count."""
    name, text = _file(files, "IopBase.txt")
    if standalone:
        name, text = next(iter(files.items()))
    evidence, summary, functions = [], {}, []
    section = re.search(r"^-+Host Interface Information-+[^\n]*\n([\s\S]*?)(?=^\*\*\* Generic Config \*\*\*|\Z)", text, re.M)
    if section:
        body = section.group(1)
        for label in ("IocEnabled", "MaxSupportedIocCount"):
            match = re.compile(r"^" + label + r"\s+([0-9a-f]+)\b", re.I | re.M).search(text, section.start(1), section.end(1))
            if match:
                summary[label] = int(match.group(1), 16)
                evidence.append(_source(name, text, match))
        match = re.compile(r"^NumPceFunc\s*:\s*MPI\s+([0-9a-f]+)\s+NVMe\s+([0-9a-f]+)\b", re.M | re.I).search(text, section.start(1), section.end(1))
        if match:
            summary.update(mpi_functions_reported=int(match.group(1), 16), nvme_functions_reported=int(match.group(2), 16))
            evidence.append(_source(name, text, match))
        for match in re.finditer(r"^ioc ([0-9a-f]+):[ \t]*\r?\n([\s\S]*?)(?=^ioc [0-9a-f]+:|\Z)", body, re.M | re.I):
            index = int(match.group(1), 16)
            fields, refs = {}, []
            offset = section.start(1) + match.start()
            line = text.count("\n", 0, offset) + 1
            refs.append({"name": name, "start_line": line, "end_line": line, "excerpt": match.group().splitlines()[0]})
            # Only the labelled fixed header is read, never queue or memory words.
            for row in re.finditer(r"^[^\n]+", match.group(2)[:2048], re.M):
                found = list(re.finditer(r"\b(IocFaultCode|IocState|BusNum|DeviceFunc|EtpDevType|MaxMsixVec|MaxOpQueues)\s+([0-9a-f]+)\b", row.group(), re.I))
                if found:
                    fields.update({f.group(1): int(f.group(2), 16) for f in found})
                    number = text.count("\n", 0, section.start(1) + match.start(2) + row.start()) + 1
                    refs.append({"name": name, "start_line": number, "end_line": number, "excerpt": row.group().rstrip("\r")})
            functions.append({"ioc_index": index, "raw_fields": fields, "role": "Unverified", "sources": refs})
            if len(functions) >= 64:
                break
    # Keep this differently scoped label as a literal counter, not the observed PF count.
    generic = []
    for match in re.finditer(r"^NumberOfIocs:[ \t]*([0-9a-f]+)\b", text, re.M | re.I):
        generic.append({"raw": match.group(1), "source": _source(name, text, match)})
        if len(generic) >= 16:
            break
    return {"summary": summary, "functions": functions, "generic_ioc_counters": generic,
            "physical_card_count": None, "evidence": evidence,
            "reference": "SAS5xxxxW-FW-Diff-AN101 pp. 7-8, 13-14",
            "limitation": "IOC indices, enabled bitmap, MPI function count and Generic Config NumberOfIocs have separate scopes; none is a physical-card count. A PCI domain/segment is not supplied here. Supervisor/Non-supervisor roles require explicit role or PCI identity evidence; IOC index alone does not prove a role. Management visibility is not OS visibility; confirm PF assignment, Mgmt only and Exposed to Host before diagnosing a missing disk. Up to 64 functions are shown; raw state/type values remain undecoded."}


def device_mapping(files: dict[str, str]) -> dict[str, Any]:
    name, text = _file(files, "DevPrst.txt")
    ranges = []
    malformed = 0
    table = re.search(r"^Index[ \t]+EnclD[^\n]*\n([\s\S]*?)(?=^DEVPRST |\Z)", text, re.M)
    if table:
        for match in re.finditer(r"^[ \t]*[0-9a-f]+[ \t]+[0-9a-f]+[^\r\n]*", table.group(1), re.I | re.M):
            tokens = match.group().split()
            # PH is two words. Parsing by a one-word column offset corrupts IsEx/IsR.
            if len(tokens) != 15 or not all(re.fullmatch(HEX, token, re.I) for token in tokens):
                malformed += 1
                continue
            values = [int(token, 16) for token in tokens]
            index, elid, first, count, slot = values[:5]
            if elid == 0 or first == 0xffff or count < 2 or not values[9]:
                continue
            if first + count > 0x10000:
                malformed += 1
                continue
            offset = table.start(1) + match.start()
            # Construct the source directly from the original line offset.
            line = text.count("\n", 0, offset) + 1
            ranges.append({"index": index, "enclosure_elid": f"{elid:016x}",
                           "first_id": first, "reserved_ids": count, "first_slot": slot,
                           "phy_bitmap_words": tokens[7:9], "recorded": bool(values[10]),
                           "source": {"name": name, "start_line": line, "end_line": line,
                                      "excerpt": match.group().rstrip("\r")}})
    pd_name, pd = _file(files, "Pd.txt")
    devices = []
    for match in re.finditer(r"^PD\s*=\s*([0-9a-f]+)\b([\s\S]*?)(?=^PD\s*=|\Z)", pd, re.I | re.M):
        block = match.group(2)
        scsi = re.search(r"\bscsiType\s*=\s*(" + HEX + r")\b", block, re.I)
        if not scsi or int(scsi.group(1), 16) not in {0, 13}:
            continue
        pid = int(match.group(1), 16)

        def value(pattern: str) -> str | None:
            found = re.search(pattern, block, re.I | re.M)
            return found.group(1).strip() if found else None

        slot_raw = value(r"\bslotNumber\s*=\s*(" + HEX + r")\b")
        encl_raw = value(r"\benclDeviceId\s*=\s*(" + HEX + r")\b") or value(r"\benclid[ \t]+(" + HEX + r")\b")
        slot = int(slot_raw, 16) if slot_raw and int(slot_raw, 16) != 0xffff else None
        candidates = [item for item in ranges if item["first_id"] <= pid < item["first_id"] + item["reserved_ids"]]
        item = {"persistent_id": pid, "id_hex": f"0x{pid:x}", "kind": "disk" if int(scsi.group(1), 16) == 0 else "SES",
                "slot": slot, "enclosure_id": int(encl_raw, 16) if encl_raw else None,
                "state": value(r"\bstate\s*=\s*[0-9a-f]+\s*\(([^)]+)\)"),
                "model": value(r"^\s*productIdentification=([^\r\n]+)"),
                "address": value(r"\baddr\[0\]=([0-9a-f:]+)"),
                "serial": value(r"^\s*(?:serialNumber|SerialNo)[ \t]*[:=][ \t]*([\x21-\x7e ]+)"),
                "range_status": "unresolved", "enclosure_elid": None, "range_slot": None, "range_id_offset": None,
                "sources": []}
        header_end = pd.find("\n", match.start())
        header = pd[match.start():header_end if header_end >= 0 else len(pd)].rstrip("\r")
        line = pd.count("\n", 0, match.start()) + 1
        item["sources"] = [{"name": pd_name, "start_line": line, "end_line": line,
                            "excerpt": header}]
        # Keep the literal slot/identity lines as separate evidence; no packed fields are guessed.
        for fact in re.finditer(r"^[^\n]*(?:slotNumber\s*=|productIdentification=|serialNumber[ \t]*=)[^\n]*", block, re.I | re.M):
            begin = match.start(2) + fact.start()
            number = pd.count("\n", 0, begin) + 1
            item["sources"].append({"name": pd_name, "start_line": number, "end_line": number, "excerpt": fact.group().rstrip("\r")})
        if len(candidates) == 1:
            candidate = candidates[0]
            delta = pid - candidate["first_id"]
            # DSN (physical slot) may be noncontiguous. PID offset is not DSN.
            # Keep range_slot null for older consumers rather than leaking an inferred slot.
            item.update(enclosure_elid=candidate["enclosure_elid"], range_id_offset=delta,
                        range_status="range candidate")
            item["sources"].append(candidate["source"])
        elif len(candidates) > 1:
            item["range_status"] = "ambiguous"
        devices.append(item)
        if len(devices) >= 2048:
            break
    prst_name, prst = _file(files, "PdPrst.txt")
    persistent_records = []
    for match in re.finditer(r"^INDEX[ \t]*:[ \t]*(0x[0-9a-f]+)([\s\S]*?)(?=^INDEX[ \t]*:|\Z)", prst, re.I | re.M):
        block = match.group(2)
        fields = {}
        for label in ("UniqueId", "PdType", "pdConfiguration", "pdIsBad", "pdIsMissing", "PdRebuildNeeded"):
            found = re.search(r"\b" + label + r"[ \t]*:[ \t]*(" + HEX + r")\b", block, re.I)
            fields[label] = int(found.group(1), 16) if found else None
        line = prst.count("\n", 0, match.start()) + 1
        end = prst.find("\n", match.start())
        persistent_records.append({"index": int(match.group(1), 16), **fields,
                                   "source": {"name": prst_name, "start_line": line, "end_line": line,
                                              "excerpt": prst[match.start():end if end >= 0 else len(prst)].rstrip("\r")}})
        if len(persistent_records) >= 2048:
            break
    return {"ranges": ranges[:1024], "devices": devices, "malformed_rows": malformed,
            "persistent_records": persistent_records,
            "persistent_record_limitation": "PdPrst records may retain missing/old devices. INDEX and UniqueId are not assumed to be the current PD Persistent ID or a disk WWN; these flags do not establish current disk failures. At most 2048 records are decoded.",
            "reference": "SAS4xxx-EncReq-AN100 pp. 5-6: DSN, SlotIndex and CEI are distinct",
            "limitation": "Range membership is a candidate, not global disk identity. Persistent ID offset is not a physical slot: DSN, SlotIndex and CEI differ and slot numbers may be noncontiguous. Only literal Pd slotNumber supplies the observed slot; no slot conflict is inferred from a range. Use serial/WWN plus controller and enclosure context across captures. SES devices are not disks. Display data is bounded to 1024 ranges and 2048 PD records."}


PAGE_NAMES = {0: "Board identity", 7: "Connectors", 8: "PHY / receptacle / slot mapping",
              9: "Runtime resources", 10: "I2C controllers", 11: "I2C targets", 20: "Personality features",
              21: "RAID policy", 40: "Controller defaults", 41: "VD defaults", 42: "RAID PD defaults",
              43: "Advanced host PD defaults", 46: "Boot event actions", 47: "Persistent device table",
              51: "PHY SerDes settings", 52: "PHY groups", 55: "SAS recovery settings", 56: "Virtual SES"}


def configuration(files: dict[str, str], generation: str = "Unverified") -> dict[str, Any]:
    name, text = _file(files, "ConfigPages.txt")
    pages = []
    region = "UNSPECIFIED"
    current = None
    # Page numbers in the exporter header are decimal; dump words are hexadecimal.
    header = re.compile(r"^PageType ([A-Z0-9]+): PageNum (\d+) for IocNum (\d+) PageAddr (0x[0-9a-f]+) Size (0x[0-9a-f]+) words:", re.I)
    for number, line in enumerate(text.splitlines(), 1):
        if len(line) > 8192:
            if current:
                current["collection_error"] = True
            continue
        marker = re.search(r"====Read (DEFAULT|CURRENT|PERSISTENT) Configuration Pages====", line)
        if marker:
            region, current = marker.group(1), None
        match = header.match(line)
        if match:
            if len(pages) >= 2048:
                break
            kind, num, ioc, address, size = match.groups()
            current = {"region": region, "type": kind.upper(), "page": int(num), "ioc": int(ioc),
                       "address": address.lower(), "size_words": int(size, 16), "words_seen": 0,
                       "signature": hashlib.sha256(), "collection_error": False,
                       "label": (PAGE_NAMES.get(int(num), "Manufacturing page") if generation == "AV1" else "Manufacturing page; field meaning unverified") if kind.upper() == "MFG" else kind.upper() + " configuration page",
                       "source": {"name": name, "start_line": number, "end_line": number, "excerpt": line}}
            pages.append(current)
        elif current:
            words = re.match(r"^[0-9a-f]+:[ \t]+((?:[0-9a-f]{8}[ \t]*)+)$", line, re.I)
            skipped = re.match(r"^\[skipped (0x[0-9a-f]+) empty dwords\]", line, re.I)
            if words:
                tokens = words.group(1).lower().split()
                current["signature"].update("".join(tokens).encode("ascii"))
                current["words_seen"] += len(tokens)
            elif skipped:
                count = int(skipped.group(1), 16)
                # Never allocate or loop based on an untrusted zero-run count.
                if count <= 65536 and current["words_seen"] + count <= 65536:
                    current["signature"].update(b"00000000" * count)
                else:
                    current["collection_error"] = True
                current["words_seen"] += count
            elif re.search(r"Validation Failed|invalid status|retVal", line, re.I):
                current["collection_error"] = True
    by_key = {}
    for page in pages:
        key = (page["region"], page["type"], page["page"], page["ioc"], page["address"])
        by_key.setdefault(key, []).append(page)
    changes = []
    for page in pages:
        if page["region"] != "CURRENT":
            continue
        key = (page["type"], page["page"], page["ioc"], page["address"])
        defaults = by_key.get(("DEFAULT", *key), [])
        currents = by_key[("CURRENT", *key)]
        if len(defaults) == len(currents) == 1:
            default = defaults[0]
            if all(p["words_seen"] == p["size_words"] and not p["collection_error"] for p in (page, default)):
                if page["signature"].digest() != default["signature"].digest():
                    changes.append({"type": page["type"], "page": page["page"], "ioc": page["ioc"],
                                    "address": page["address"], "label": page["label"],
                                    "sources": [default["source"], page["source"]]})
    for page in pages:
        page.pop("signature")
    return {"regions": dict(Counter(page["region"] for page in pages)), "pages": pages,
            "current_default_differences": changes,
            "limitation": "CURRENT describes this boot. Differences are raw page differences, not faults or decoded settings. Address/header words are not firmware feature bits. Page field layouts require matching MPI3/MFG specifications; example board pinouts are not universal. At most 2048 page records are decoded."}


OBSERVATIONS = (
    ("assert", re.compile(r"\bASSERT\s*:[^\n]*\b(?:File|line|ECode)\b", re.I)),
    ("command_status", re.compile(r"\bIOCStatus\s*[:=]?\s*(?:0x)?[0-9a-f]+[^\n]*\bIOCLogInfo\s*[:=]?\s*(?:0x)?[0-9a-f]+", re.I)),
    ("sense", re.compile(r"\bSense\s*[:=]?\s*(?:0x)?[0-9a-f]{1,2}/(?:0x)?[0-9a-f]{1,2}/(?:0x)?[0-9a-f]{1,2}\b", re.I)),
    ("safe_mode", re.compile(r"\b(?:entered|entering|waiting in|running in|is in|remains in)\s+(?:FW\s+)?Safe\s*Mode\b", re.I)),
    ("memory", re.compile(r"\b(?:DDR init[^\n]*failed|(?:multi[ -]?bit|uncorrectable) ECC (?:error|detected)|Write Level Cycle Adjust FAILED)\b", re.I)),
    ("nand", re.compile(r"\b(?:NAND[^\n]{0,50}(?:initialization failed|init failed)|Unable to initialize ONFI HW|Non-Volatile Cache has gone bad)\b", re.I)),
    ("cache", re.compile(r"\b(?:Cache offload failed|offload expected but didn.t happen|controller cache discarded|restore completed in \d+ seconds|pinned cache)\b", re.I)),
    ("management_status", re.compile(r"\b(?:SLStatus|comStatus|DCMDStatus|SCSIStatus|NVMeStatus)\s*[:=]\s*(?:0x)?[0-9a-f]+\b", re.I)),
    ("management_context", re.compile(r"\b(?:invalid sequence|incomplete buffer|buffer too small|MCTP[^\n]{0,40}(?:sequence|packet)[^\n]{0,30}(?:error|mismatch))\b", re.I)),
)


def diagnostics(files: dict[str, str], mapping: dict[str, Any]) -> dict[str, Any]:
    by_kind = {kind: deque(maxlen=120) for kind, _ in OBSERVATIONS}
    counts = Counter()
    scanned = 0
    long_lines = 0
    scanned_files = []
    selected = {"tty.txt", "controllerpel.txt", "rmcringbuffer.txt", "etpringbuffer.txt",
                "crashdump.txt", "oob.txt", "storelib8debug.txt", "summary.txt", "cpu.txt"}
    for name, text in sorted(files.items()):
        if len(files) > 1 and name.rsplit("/", 1)[-1].lower() not in selected:
            continue
        scanned_files.append(name)
        for number, line in enumerate(text.splitlines(), 1):
            scanned += 1
            if len(line) > 4000:
                long_lines += 1
                continue
            kinds = [kind for kind, pattern in OBSERVATIONS if pattern.search(line)]
            if "command_status" in kinds:
                status = re.search(r"\bIOCStatus\s*[:=]?\s*((?:0x)?[0-9a-f]+)", line, re.I)
                info = re.search(r"\bIOCLogInfo\s*[:=]?\s*((?:0x)?[0-9a-f]+)", line, re.I)
                if status and info and int(status.group(1), 16) == int(info.group(1), 16) == 0:
                    kinds.remove("command_status")
            layer_values = {m.group(1): m.group(2) for m in re.finditer(
                r"\b(SLStatus|comStatus|DCMDStatus|SCSIStatus|NVMeStatus)\s*[:=]\s*((?:0x)?[0-9a-f]+)\b", line, re.I)}
            if "management_status" in kinds and not any(int(v, 16) for v in layer_values.values()):
                kinds.remove("management_status")
            if not kinds:
                continue
            counts.update(kinds)
            record = {"kinds": kinds, "source": {"name": name, "start_line": number, "end_line": number, "excerpt": line},
                      "scope": "Log observation; active state and boot correlation unverified"}
            if "command_status" in kinds:
                record["status_namespace"] = "MPI IOC reply (raw IOCStatus/IOCLogInfo)"
            if layer_values:
                record["management_status_fields"] = layer_values
            if "management_context" in kinds:
                record["interpretation"] = "Collection/transport context; does not establish a media failure"
            for label, pattern in {
                "ioc_status": r"\bIOCStatus\s*[:=]?\s*((?:0x)?[0-9a-f]+)",
                "ioc_log_info": r"\bIOCLogInfo\s*[:=]?\s*((?:0x)?[0-9a-f]+)",
                "sense": r"\bSense\s*[:=]?\s*((?:0x)?[0-9a-f]{1,2}/(?:0x)?[0-9a-f]{1,2}/(?:0x)?[0-9a-f]{1,2})",
                "time": r"EVT#[0-9]+-([^:]+:\d{2}:\d{2}|T\d+(?:\.\d+)?):",
            }.items():
                found = re.search(pattern, line, re.I)
                if found:
                    record[label] = found.group(1)
            pd = re.search(r"\bPD\s+(0x[0-9a-f]+)\b", line, re.I)
            if pd:
                pid = int(pd.group(1), 16)
                record["persistent_id"] = pid
                devices = [d for d in mapping["devices"] if d["persistent_id"] == pid]
                if len(devices) == 1:
                    record["device"] = {k: devices[0][k] for k in ("id_hex", "slot", "enclosure_id", "model", "range_status")}
            record["_order"] = scanned
            for kind in kinds:
                by_kind[kind].append(record)
    # Reserve room for each category, so noisy command replies cannot hide
    # every ASSERT, Sense or cache record. The final order remains file order.
    retained = {}
    for depth in range(120):
        for records in by_kind.values():
            if len(records) > depth and len(retained) < 120:
                record = records[-1 - depth]
                retained[record["_order"]] = record
    observations = [retained[key] for key in sorted(retained)]
    for record in observations:
        record.pop("_order", None)
    recommendations = []
    if counts["command_status"]:
        recommendations.append("Correlate IOCStatus/IOCLogInfo with the same command and OOB/driver logs; full code meanings require the matching ROP specification.")
    if counts["safe_mode"]:
        recommendations.append("Collect blocking Boot Events and PEL acknowledgement state; Safe Mode alone does not establish a hung controller.")
    if counts["cache"] or counts["memory"] or counts["nand"]:
        recommendations.append("Correlate ECC, NAND, SuperCap and offload/restore evidence within the same boot or power cycle before assigning a cache-loss cause.")
    if counts["sense"]:
        recommendations.append("Correlate CDB/Sense and PD enclosure/slot with serial/WWN and OS driver logs; a Sense triple alone does not identify the failed component.")
    if counts["management_status"] or counts["management_context"]:
        recommendations.append("Keep StoreLib SLStatus, communication comStatus, MPI, DCMD, SCSI and NVMe namespaces separate. Check the command result, populated bits and transferred length before using returned values; invalid sequence requires refreshed context, not a disk-failure diagnosis. OOB collection should include storelib8debug.txt and transport logs.")
    return {"counts": dict(counts), "observations": observations, "total_matches": sum(counts.values()),
            "lines_scanned": scanned, "files_scanned": scanned_files, "long_lines_omitted": long_lines,
            "selection": "Up to 120 source lines, balancing recent matches per category in file order; not a merged chronological timeline",
            "recommended_evidence": recommendations,
            "limitation": "Historical observations do not overwrite current health checks. Raw status and Sense values are preserved without an unsupported code dictionary."}


def enrich(result: dict[str, Any]) -> None:
    if result["format"]["id"] != "mpi3":
        return
    files = result["_file_text"]
    standalone = not result["filename"].lower().endswith(".zip")
    identity = controller_identity(files, standalone)
    result["controller_identity"] = identity
    mode = operating_mode(files, standalone)
    result["operating_mode"] = mode
    result["host_functions"] = host_functions(files, standalone)
    result["firmware"]["profile_id"] = mode["profile_id"]
    result["device_mapping"] = device_mapping(files)
    result["configuration"] = configuration(files, identity["generation"] if not identity["conflict"] else "Unverified")
    result["diagnostics"] = diagnostics(files, result["device_mapping"])
    if mode["conflict"]:
        result["checks"].append({"severity": "warn", "title": "Operating mode conflict",
                                 "detail": "Snapshot runtime and personality/profile disagree; mode-dependent checks remain unverified.",
                                 "evidence": " / ".join(f"{s['name']}:{s['start_line']}" for s in mode["evidence"])})
    if identity["conflict"]:
        result["checks"].append({"severity": "warn", "title": "Controller identity conflict",
                                 "detail": "Snapshot board identity is inconsistent; generation/mode-dependent checks remain unverified.",
                                 "evidence": " / ".join(f"{s['name']}:{s['start_line']}" for s in identity["evidence"])})
    duplicates = [base for base, count in Counter(n.rsplit('/', 1)[-1].lower() for n in files).items() if count > 1]
    if duplicates:
        result["notes"].append("Duplicate log basenames: Avenger cross-file enrichment excludes ambiguous sources: " + ", ".join(duplicates))
    result["notes"].append("Avenger interpretation is generation-scoped using the supplied AV1/AV2 library and July/August 2025 references. Unknown firmware layouts remain undecoded. Configured link limits are separate from maximum capability and negotiated speed.")
