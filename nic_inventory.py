"""Bounded, evidence-preserving PCIe and NIC inventory parsing for V3/V4 FFDC.

Link state is an inventory observation, not a fault diagnosis. Packed V4 Addr
values and unitless V3 link speeds deliberately remain uninterpreted.
"""

import re


MAX_TEXT_CHARS = 8 * 1024 * 1024
MAX_LINES = 80000
MAX_LINE_CHARS = 8192

_NETWORK = re.compile(
    r"\b(?:ethernet|network|nic|netxtreme|connect[- ]?x|"
    r"\d+(?:\.\d+)?\s*GbE|[ex][578]\d{2}|i350|i210|i225|i226|x550|x540|x520)\b", re.I
)
_STORAGE = re.compile(r"\b(?:raid|megaraid|hba|storage|sas|sata|nvme)\b", re.I)
_V3_HEADER = re.compile(r"^\s*PCI Adapter\s+(\d{1,8})\s*:\s*(.+?)\s*$", re.I)
_CONTROLLER_HEADER = re.compile(
    r"^\s*(?:[A-Za-z][A-Za-z0-9 /&._+-]{0,100}\s+)?Controller"
    r"(?:\s+\d{1,8})?\s*:?\s*$", re.I
)
_V4_HEADER = re.compile(
    r"^\s*(Slot|Onboard)\s+(\d{1,8}),\s*Addr\s+(0x[\da-f]+),\s*"
    r"\[([^\]]+)\],\s*([^,]+),\s*(.+?),\s*EID\(([^)]*)\)"
    r"(?:,\s*(.*))?\s*$", re.I
)
_BOUNDARY = re.compile(
    r"^\s*(?:Storage|Other Drives|Drive wear report|Backplanes?|"
    r"Power Supplies|Fans|Processors|Memory|PLDM firmware)\s*(?::|\d+\s*[: ,])|"
    r"^\s*Bay\s*\d+\s*,|^\s*=+\s*Pci adapters time cost\b", re.I
)
_LINK_STATES = {0: "NotSupported", 1: "Unknown", 2: "Down", 3: "Up"}


def _lines(text, source, notes):
    text = str(text or "")
    if len(text) > MAX_TEXT_CHARS:
        notes.append("{}: inventory input truncated at {} characters".format(source, MAX_TEXT_CHARS))
        # Drop the partial final line rather than interpreting incomplete data.
        text = text[:MAX_TEXT_CHARS].rsplit("\n", 1)[0]
    for number, line in enumerate(text.splitlines(), 1):
        if number > MAX_LINES:
            notes.append("{}: inventory input truncated at {} lines".format(source, MAX_LINES))
            break
        if len(line) > MAX_LINE_CHARS:
            notes.append("{}:{}: oversized inventory line skipped".format(source, number))
            yield number, ""
        else:
            yield number, line


def _integer(value):
    match = re.match(r"\s*(0x[\da-f]{1,16}|\d{1,16})(?=\s|\(|$)", str(value or ""), re.I)
    if not match:
        return None
    token = match.group(1)
    return int(token, 16 if token.lower().startswith("0x") else 10)


def _identity_value(value):
    value = str(value or "").strip()
    number = _integer(value)
    return str(number) if number is not None else value.lower()


def _is_nic(name):
    return bool(_NETWORK.search(name or "") and not _STORAGE.search(name or ""))


def _adapter(name, source, line, raw):
    return {
        "slot": "", "name": name, "eid": "", "tid": "", "address": "",
        "pci_bdf": "", "pci_ids": {}, "pldm_types": [], "pldm_capabilities": {},
        "firmware": "", "firmware_components": [], "source": source, "line": line,
        "manufacturer": "", "model": "", "part_number": "", "serial": "",
        "raw": raw.strip(), "pldm_types_raw": "", "pldm_mask": "",
        "event_types": [], "event_types_raw": "",
    }


def _port(adapter, number, line, raw):
    return {
        "slot": adapter["slot"], "adapter": adapter["name"], "eid": adapter["eid"],
        "port": number, "mac": "", "state": "", "speed": "", "speed_unit": "",
        "source": adapter["source"], "line": line, "raw": raw.strip(),
        "pci_bdf": adapter.get("pci_bdf", ""),
    }


def _ids(value):
    parts = re.split(r"\s*\|\s*|\s+", value.strip())
    # Firmware V4 text commonly omits the ``0x`` prefix, including IDs that
    # contain A-F (for example Broadcom's ``14E4 1657 17AA 402D``).  Accept
    # those as hexadecimal while retaining the decimal-group rule for exports
    # such as ``32902 | 4681 | 32902 | 16387``.
    token_re = r"(?:0x[\da-f]{1,4}|[\da-f]{1,4}|\d{5})"
    if len(parts) != 4 or not all(re.fullmatch(token_re, p, re.I) for p in parts):
        return {}
    # The text dump normally uses hexadecimal tokens (often with a 0x prefix),
    # but some firmware exports the same 16-bit IDs as decimal integers.  A
    # five-digit decimal value such as 32902 cannot be a 16-bit hex token and
    # is a reliable signal that the whole unprefixed group is decimal.  Keep
    # the established hex interpretation for ordinary four-digit groups.
    decimal_group = any(not part.lower().startswith("0x") and part.isdigit() and len(part) > 4 for part in parts)
    parsed = []
    for part in parts:
        try:
            number = int(part, 16 if part.lower().startswith("0x") or not decimal_group else 10)
        except ValueError:
            return {}
        if not 0 <= number <= 0xFFFF:
            return {}
        parsed.append(number)
    return {key: "0x{:04x}".format(number)
            for key, number in zip(("vid", "did", "svid", "sdid"), parsed)}


def _type_numbers(value):
    # Stop at parenthetical event delivery annotations such as '(Async)'.
    value = value.split("(", 1)[0]
    return list(dict.fromkeys(int(x) for x in re.findall(r"\b\d{1,3}\b", value)))


def _named_capabilities(value):
    return {name.strip(): flag.upper() == "Y"
            for name, flag in re.findall(r"([A-Za-z][\w& /-]*)\(([YN])\)", value, re.I)}


def _v4_capabilities(value):
    explicit = _named_capabilities(value)
    if explicit:
        return explicit
    # DSP0245 Table 1: derive support only from a complete numeric type list.
    # Missing, partial or unrecognized text must not become explicit N flags.
    if not re.fullmatch(r"\s*\d{1,2}(?:\s*,\s*\d{1,2})*\s*", value):
        return {}
    types = _type_numbers(value)
    if any(code > 63 for code in types):
        return {}
    return {name: code in types for name, code in
            (("Monitor&Control", 2), ("FRU", 4), ("FwUpdate", 5), ("RDE", 6))}


def _speed(value, unit=""):
    value = value.strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:\(?([A-Za-z][A-Za-z/ ]*)\)?)?", value)
    if match:
        return match.group(1), (unit or match.group(2) or "").strip()
    return value, unit.strip()


def _state(value):
    key = re.sub(r"[\s_-]", "", value).lower()
    return {"linkdown": "Down", "down": "Down", "linkup": "Up", "up": "Up",
            "unknown": "Unknown", "notsupport": "NotSupported",
            "notsupported": "NotSupported"}.get(key, value.strip())


def _parse_v3(text, source, notes, nic_only=True):
    adapters, ports = [], []
    current = None
    function = None
    component = None
    port_number = ""
    port_mode = ""
    link = None
    fields = {"eid": "eid", "slot number": "slot", "manufacturer": "manufacturer",
              "model": "model", "part number": "part_number", "serial number": "serial",
              "location": "location"}
    for number, raw in _lines(text, source, notes):
        head = _V3_HEADER.match(raw)
        if head:
            current, function, component, link, port_number, port_mode = None, None, None, None, "", ""
            if not nic_only or _is_nic(head.group(2)):
                current = _adapter(head.group(2), source, number, raw)
                current["index"] = head.group(1)
                adapters.append(current)
            continue
        if _BOUNDARY.match(raw):
            current, function, component, link = None, None, None, None
            continue
        if current is None:
            continue
        if _CONTROLLER_HEADER.match(raw):
            function = _adapter(current["name"], source, number, raw)
            current.setdefault("functions", []).append(function)
            component, link, port_number, port_mode = None, None, "", ""
            continue
        target = function if function is not None else current
        network_ports = _is_nic(current["name"])
        physical = re.match(r"^\s*physical port\s+(\d{1,8})\s*:\s*$", raw, re.I)
        if physical and network_ports:
            port_number, port_mode = physical.group(1), "physical"
            link = _port(target, port_number, number, raw)
            link["physical_section"] = port_number
            ports.append((current, target, link))
            continue
        if network_ports and re.match(r"^\s*logical port\s+\d{1,8}\s*:\s*$", raw, re.I):
            port_mode, link = "logical", None
            continue
        port_head = re.match(r"^\s*\[?Port\s+(\d{1,8})\]?\s*:?\s*$", raw, re.I)
        if port_head and network_ports:
            port_number, link, port_mode = port_head.group(1), None, "physical"
            continue
        if re.match(r"^\s*firmware\s+\d+\s*:\s*$", raw, re.I):
            component = {"name": "", "version": "", "description": "",
                         "source": source, "line": number}
            target["firmware_components"].append(component)
            continue
        kv = re.match(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$", raw)
        if not kv:
            continue
        key, value = re.sub(r"\s+", " ", kv.group(1).strip()).lower(), kv.group(2)
        if key in fields:
            target[fields[key]] = value
            if key != "eid" and not current.get(fields[key]):
                current[fields[key]] = value
        elif key.replace(" ", "") == "seg|bus|dev|func":
            target["pci_bdf_raw"] = value
            parts = value.split("|")
            coords = [_integer(x) for x in parts]
            if len(coords) == 4 and all(x is not None for x in coords):
                seg, bus, dev, func = coords
                target["pci_coordinates"] = dict(zip(("segment", "bus", "device", "function"), coords))
                if seg <= 0xffff and bus <= 0xff and dev <= 0x1f and func <= 7:
                    target["pci_bdf"] = "{:04x}:{:02x}:{:02x}.{:x}".format(*coords)
        elif key.replace(" ", "") == "vid|did|svid|sdid":
            target["pci_ids_raw"], target["pci_ids"] = value, _ids(value)
        elif key == "pldm":
            target["pldm_types_raw"] = value
            mask = re.search(r"\btypes\s*\(\s*(0x[\da-f]{1,16})\s*\)", value, re.I)
            if mask:
                target["pldm_mask"] = mask.group(1)
                mask_value = int(mask.group(1), 16)
                target["pldm_types"] = [bit for bit in range(64) if mask_value & (1 << bit)]
            target["pldm_capabilities"].update(_named_capabilities(value))
        elif key in ("firmware name", "version string", "description"):
            if component is None and key != "description":
                component = {"name": "", "version": "", "description": "",
                             "source": source, "line": number}
                target["firmware_components"].append(component)
            if component is not None:
                component[{"firmware name": "name", "version string": "version", "description": "description"}[key]] = value
        elif network_ports and port_mode != "logical" and key in ("port index", "permanent address"):
            if link is None:
                link = _port(target, port_number, number, raw)
                ports.append((current, target, link))
            if raw.strip() not in link["raw"].splitlines():
                link["raw"] += "\n" + raw.strip()
            if key == "port index":
                if re.fullmatch(r"\d{1,8}", value):
                    port_number = value
                    link["port"] = value
                    link["port_index"] = value
            else:
                link["mac_raw"] = value
                compact = re.sub(r"[:-]", "", value)
                if re.fullmatch(r"[\da-f]{12}", compact, re.I):
                    link["mac"] = ":".join(compact[i:i + 2].upper() for i in range(0, 12, 2))
        elif network_ports and port_mode != "logical" and (key == "link status" or re.fullmatch(r"link speed(?:\s*\([^)]*\))?", key)):
            if link is None or (key == "link status" and link["state"]):
                link = _port(target, port_number, number, raw)
                ports.append((current, target, link))
            elif raw.strip() not in link["raw"].splitlines():
                link["raw"] += "\n" + raw.strip()
            if key == "link status":
                code = _integer(value)
                link["state_code"] = code
                link["state_raw"] = value
                link["state"] = _LINK_STATES.get(code, "Unknown") if code is not None else _state(value)
            else:
                unit = re.search(r"\(([^)]+)\)", kv.group(1))
                link["speed"], link["speed_unit"] = _speed(value, unit.group(1) if unit else "")
                link["speed_raw"] = value
    for adapter in adapters:
        functions = adapter.get("functions", [])
        for row in [adapter] + functions:
            row["firmware"] = "; ".join(
                "{}: {}".format(c["name"], c["version"]).strip(": ")
                for c in row["firmware_components"] if c["name"] or c["version"]
            )
            if not row["slot"]:
                row["slot"] = adapter["slot"]
        if functions:
            primary = next((f for f in functions if _integer(f["eid"]) is not None), functions[0])
            for key in ("eid", "tid", "address", "pci_bdf", "pci_bdf_raw", "pci_coordinates",
                        "pci_ids", "pci_ids_raw", "pldm_types", "pldm_capabilities", "pldm_mask",
                        "pldm_types_raw", "firmware", "firmware_components", "event_types", "event_types_raw"):
                if key in primary:
                    adapter[key] = primary[key]
            adapter["primary_function_line"] = primary["line"]
    # Some dumps place EID/slot after their link section.
    for adapter, identity, port in ports:
        port["slot"], port["eid"] = adapter["slot"], identity["eid"]
        port["pci_bdf"] = identity["pci_bdf"]
        if identity is not adapter:
            port["function_line"] = identity["line"]
    return adapters, [p for _, _, p in ports]


def _parse_v4(text, source, notes, nic_only=True):
    adapters, ports, endpoints = [], [], []
    current = None
    for number, raw in _lines(text, source, notes):
        head = _V4_HEADER.match(raw)
        if head:
            current = None
            kind, slot, address, ids, service, name, eid, version = head.groups()
            if nic_only and not _is_nic(name):
                continue
            current = _adapter(name.strip(), source, number, raw)
            current.update({"slot": ("Onboard " if kind.lower() == "onboard" else "") + str(int(slot)),
                            "eid": eid.strip(), "address": address, "pci_ids": _ids(ids),
                            "pci_ids_raw": ids.strip(), "device_type": service.strip(),
                            "firmware": (version or "").split(",", 1)[0].strip()})
            adapters.append(current)
            continue
        if re.match(r"^\s*(?:Slot|Onboard)\b", raw, re.I) or _BOUNDARY.match(raw):
            current = None
            continue
        if re.match(r"^\s*TID\s*\|", raw, re.I):
            current = None
            continue
        columns = [x.strip() for x in raw.split("|")]
        if len(columns) == 6 and re.fullmatch(r"\d{1,8}", columns[0]) and all(
                re.fullmatch(r"0x[\da-f]+", columns[i], re.I) for i in (1, 2, 3)):
            tid, eid, address, vid, types, events = columns
            endpoints.append({"tid": tid, "eid": eid, "address": address, "vid": vid,
                              "pldm_types": _type_numbers(types), "pldm_types_raw": types,
                              "pldm_capabilities": _v4_capabilities(types),
                              "event_types": _type_numbers(events), "event_types_raw": events,
                              "source": source, "line": number, "raw": raw.strip()})
            current = None
            continue
        if current is None:
            continue
        port_match = re.match(r"^\s*\[Port\s+(\d{1,8})\]\s*(.*)$", raw, re.I)
        if port_match and _is_nic(current["name"]):
            port = _port(current, port_match.group(1), number, raw)
            tail = port_match.group(2)
            mac = re.search(r"\b(?:[\da-f]{2}:){5}[\da-f]{2}\b", tail, re.I)
            if mac:
                port["mac"] = mac.group(0)
            state = re.search(r"\bState\s*:\s*([^;]+)", tail, re.I)
            if state:
                port["state_raw"] = state.group(1).strip()
                port["state"] = _state(state.group(1))
            speed = re.search(r"\bSpeed\s*(?:\(([^)]+)\))?\s*:\s*([^;]+)", tail, re.I)
            if speed:
                port["speed_raw"] = speed.group(2).strip()
                port["speed"], port["speed_unit"] = _speed(speed.group(2), speed.group(1) or "")
            ports.append(port)
            continue
        for field in raw.split(";"):
            pair = field.strip().split(":", 1)
            if len(pair) != 2:
                continue
            key = {"p/n": "part_number", "s/n": "serial", "manufacture": "manufacturer",
                   "manufacturer": "manufacturer", "model": "model", "sku": "sku"}.get(pair[0].strip().lower())
            if key:
                current[key] = pair[1].strip()
    # Tables may appear before or after inventory. Require both identifiers.
    by_identity = {}
    for endpoint in endpoints:
        key = (_identity_value(endpoint["eid"]), _identity_value(endpoint["address"]))
        by_identity.setdefault(key, []).append(endpoint)
    for adapter in adapters:
        key = (_identity_value(adapter["eid"]), _identity_value(adapter["address"]))
        matches = _deduplicate(by_identity.get(key, []), ("line",))
        if not matches:
            continue
        adapter["pldm_endpoints"] = matches
        tids = list(dict.fromkeys(x["tid"] for x in matches))
        if len(tids) == 1:
            adapter["tid"] = tids[0]
        else:
            notes.append("{}:{}: multiple TIDs match EID {} and Addr {}; TID left unspecified".format(
                source, adapter["line"], adapter["eid"], adapter["address"]))
        for key in ("pldm_types", "event_types", "pldm_capabilities"):
            values = {_freeze(x[key]) for x in matches}
            if len(values) == 1:
                adapter[key] = matches[0][key]
            else:
                adapter["pldm_ambiguous"] = True
                notes.append("{}:{}: conflicting {} match EID {} and Addr {}; field left unspecified".format(
                    source, adapter["line"], key, adapter["eid"], adapter["address"]))
        for key in ("pldm_types_raw", "event_types_raw"):
            adapter[key] = "; ".join(dict.fromkeys(x[key] for x in matches))
    return adapters, ports


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items() if k != "line"))
    if isinstance(value, list):
        return tuple(_freeze(x) for x in value)
    return value


def _deduplicate(rows, ignore=()):
    result, seen = [], set()
    for row in rows:
        key = _freeze({k: v for k, v in row.items() if k not in ignore})
        if key not in seen:
            result.append(row)
            seen.add(key)
    return result


def parse_nic_inventory(dmdb_text="", io_text="",
                        dmdb_source="tmp/ffdc_live_dbg/dmdb_pci_dumper.txt",
                        io_source="tmp/io_devices.txt"):
    """Return explicit adapter/port observations with source and 1-based lines.

    ``pci_ids`` is a vid/did/svid/sdid mapping. Empty strings/lists/dicts mean
    unavailable evidence. ``port`` is empty when V3 did not identify a port;
    ``state_code`` is the explicit V3 enum, if present. No link observations
    become faults here. ``notes`` records parser limits or association ambiguity.
    """
    return _parse_inventory(dmdb_text, io_text, dmdb_source, io_source, nic_only=True)


def parse_pcie_inventory(dmdb_text="", io_text="",
                         dmdb_source="tmp/ffdc_live_dbg/dmdb_pci_dumper.txt",
                         io_source="tmp/io_devices.txt"):
    """Return every explicit V3 PCI Adapter and V4 Slot/Onboard device.

    The schema matches ``parse_nic_inventory``. ``functions`` preserves each V3
    Controller subsection; the first function with an explicit numeric EID
    supplies top-level identity/PLDM fields, falling back to the first function.
    Empty PLDM evidence is distinct from explicit ``pldm_mask='0x0'``/N flags.
    V4 endpoint associations require EID and address; conflicts remain in
    ``pldm_endpoints`` and ``notes`` rather than inventing combined capabilities.
    ``ports`` contains only network observations, since storage/PCIe link state
    numbers do not have the NIC link-enum semantics used here.
    """
    return _parse_inventory(dmdb_text, io_text, dmdb_source, io_source, nic_only=False)


def _parse_inventory(dmdb_text, io_text, dmdb_source, io_source, nic_only):
    notes = []
    v3_adapters, v3_ports = _parse_v3(dmdb_text, dmdb_source, notes, nic_only=nic_only)
    v4_adapters, v4_ports = _parse_v4(io_text, io_source, notes, nic_only=nic_only)
    return {"adapters": _deduplicate(v3_adapters + v4_adapters, ("index",)),
            "ports": _deduplicate(v3_ports + v4_ports), "notes": notes}
