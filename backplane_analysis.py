"""Read-only backplane correlation using the user-designated FW v1.06 baseline."""
import re
from pathlib import Path

BACKPLANE_SPEC = {
    'document': 'SP-000008', 'revision': 'v1.06',
    'title': 'Lenovo Backplane Firmware Specification',
    'baseline': 'User-confirmed current specification, 2026-10-15',
}
SUPPORTED = {'BB', 'BC', 'BE', 'BF', 'C0', 'C1', '40', '42', '44', '45', '49'}
EXPECTED_SILICON = {**dict.fromkeys(('BB', 'BC', 'BD', 'BE'), 'E2172100'),
                    **dict.fromkeys(('BF', 'C0', 'C1'), 'EE431118'), 'BA': 'EACE120E',
                    **dict.fromkeys(('40', '44', '45', '49'), 'E2142100'), '42': '100A11A0'}
EGS_SPEC = {
    'document': 'Lenovo_EagleStream-Genoa_Backplane_SEP_FW_Spec', 'revision': 'v0.81',
    'title': 'Lenovo EagleStream-Genoa Backplane SEP Firmware Specification',
    'baseline': 'Supplied EGS/Genoa reference profile; V4/V5 remains SP-000008 v1.06',
}
# Table 70: use an explicitly reported backplane name, never a controller model.
BOARD_APPS = {
    **dict.fromkeys(('Wraith', 'Vantage', 'Wattson', 'Ash', 'Catalyst', 'Crypto', 'Gibraltar',
                     'Bangalore', 'Lifeline', 'Mirage', 'Horizon', 'Octane', 'Sparrow'), 'BB'),
    'Seer': 'BD', 'Valkyrie': 'BD', 'Pathfinder': 'BC', 'Bloodhound': 'BC', 'Fuse': 'BE',
    'Boone': 'BF', 'Lore': 'BF', 'Ballistic': 'C1', 'Rampart': 'C1', 'Loba': 'C1',
    **dict.fromkeys(('Benzema', 'Silva', 'MoSalah', 'Haaland'), 'BA'),
    **dict.fromkeys(('Titania', 'Ariel', 'Sycorax', 'Caliban', 'Bianca', 'Sao', 'Francisco', 'Proteus', 'Trinculo'), '40'),
    **dict.fromkeys(('Oberon', 'Umbriel', 'Puck', 'Portia', 'Stephano', 'Willemstad', 'Juliet', 'Cressida', 'Rosalind', 'Triton'), '42'),
    **dict.fromkeys(('Havana', 'Kingston', 'Oranjestad', 'Enzo'), '44'),
    **dict.fromkeys(('Nassau', 'Bridgetown'), '45'),
    'Zidane': '49',
}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        return int(text, 16) if text.lower().startswith('0x') else int(text, 10)
    except (TypeError, ValueError):
        return None


def bp_key(value):
    match = re.fullmatch(r'(?:bp|backplane)?\s*(\d+)', str(value or '').strip(), re.I)
    return 'bp' + str(int(match[1])) if match else str(value or '').strip().lower()


def profile_spec(row):
    if row.get('decode_profile') == 'egs_genoa':
        return 'Lenovo EagleStream-Genoa Backplane SEP FW Specification v0.81'
    if row.get('decode_profile') == 'legacy_sep':
        return row.get('legacy_spec', 'SEP Firmware Specification Rev 1.08 (2017)')
    return 'SP-000008 v1.06'


def identity(value):
    text = str(value or '').strip().casefold()
    return '' if text in {'', 'n/a', 'na', 'none', 'unknown', 'not reported', 'missing'} or set(text) <= {'0', '-', ' '} else text


def registers(row):
    return {int(k): int(v, 16) for k, v in row.get('register_bytes', {}).items()
            if str(k).isdigit() and re.fullmatch(r'[0-9a-fA-F]{2}', str(v))}


def evidence(row, offsets, section):
    raw = registers(row)
    return {'source': row.get('source', ''), 'line': row.get('line'),
            'command': row.get('command', ''), 'bp': row.get('bp'), 'sep': row.get('sep'),
            'registers': {f'0x{o:02X}': f'0x{raw[o]:02X}' for o in offsets if o in raw},
            'spec': f'{profile_spec(row)} {section}'}


def finding(severity, title, conclusion, proof):
    return {'severity': severity, 'category': 'Backplane', 'title': title,
            'conclusion': conclusion, 'evidence': proof}


def decode_links(ctrl, status):
    raw, app_id = registers(ctrl), ctrl.get('application_id')
    notes, findings = [], []
    result = {'configured_widths': [], 'negotiated_width': 'not collected',
              'ubm_disabled_ports': [], 'observed_management': [], 'limitations': notes}
    trusted = (ctrl.get('decode_profile') in {'v4_v5', 'egs_genoa'} and app_id in SUPPORTED
               and ctrl.get('ctrl_signature_valid') == 'yes' and not ctrl.get('error')
               and not ctrl.get('snapshot_conflict') and not ctrl.get('conflicting_offsets')
               and status.get('data_validation', {}).get('diagnostics_valid') is True)
    result['snapshot_valid'] = trusted
    if not trusted:
        notes.append('Link configuration cannot be validated from this snapshot')
        return result, findings
    if 0x1A in raw:
        result['configured_management'] = [name for bit, name in enumerate(('SGPIO', 'I2C_HP', 'UBM')) if raw[0x1A] & (1 << bit)]
    status_raw = registers(status)
    count = status_raw.get(1, 0)
    active, decode = status_raw.get(3), status_raw.get(count + 5)
    if active is not None and decode is not None:
        result['observed_management_collected'] = True
        for bit in range(6):
            if active & (1 << bit):
                result['observed_management'].append({'port': f'segregated {2*bit}' if bit < 4 else f'converged {bit-4}',
                    'protocol': 'UBM' if decode & (1 << bit) else 'I2C_HP' if bit < 4 else 'SGPIO'})
    if app_id in {'BB', 'BC'}:
        if 0x45 in raw:
            result['ubm_disable_collected'] = True
            names = ['I2C_HP0', 'I2C_HP2', 'I2C_HP4', 'I2C_HP6', 'converged TM0']
            result['ubm_disabled_ports'] = [name for bit, name in enumerate(names) if raw[0x45] & (1 << bit)]
            if result['ubm_disabled_ports']:
                findings.append(finding('Info', 'UBM port override observed',
                    'The collected control register intentionally disables UBM on these ports. This can explain a protocol difference; it is not proof of a cable fault.',
                    evidence(ctrl, [0x1A, 0x45], '10.1.13 Table 50')))
        else:
            notes.append('UBM port-disable register 0x45 was not collected')
    if app_id in {'BC', 'C1'}:
        result['edsff_configuration'] = f'0x{raw[0x48]:02X}' if 0x48 in raw else 'not collected'
        if raw.get(0x48) == 0xBB:
            findings.append(finding('Warning', 'EDSFF configuration is invalid',
                'The SEP reports invalid E3.S configuration. Verify the supported form factor, cable installation and bifurcation; this does not establish a defective cable.',
                evidence(ctrl, [0x48], '10.1.15 Table 52')))
    if app_id == 'BB':
        if 0x49 not in raw:
            notes.append('AnyBay bifurcation register 0x49 was not collected')
        else:
            value, u3 = raw[0x49], raw.get(0x1B)
            result['reported_width_bits'] = [{'local_slot': bit, 'width': 'x2' if value & (1 << bit) else 'x4'} for bit in range(min(count, 4))]
            if value & 0x80:
                result['configured_widths'] = result['reported_width_bits']
            result['configuration_valid_bit'] = bool(value & 0x80)
            if not value & 0x80:
                notes.append('Table 53 hexadecimal examples and valid-bit definitions disagree; an unset bit 7 alone is not a definitive cabling fault')
            if u3 is not None and u3 & value & 0x0F:
                findings.append(finding('Warning', 'NVMe x2 and U.3 x1 configuration conflict',
                    'The same local slot has NVMe x2 bifurcation and native U.3 x1 enabled, a combination disallowed by the specification. Verify the configuration and cabling.',
                    evidence(ctrl, [0x1B, 0x49], '10.1.8, 10.1.16')))
            if value & 0x0F not in {0, 15} and count == 4:
                findings.append(finding('Warning', 'AnyBay bifurcation requires verification',
                    'The captured slot bits mix x2 and x4, whereas the SEP 4MV4 definition applies one bifurcation mode across the configured group.',
                    evidence(ctrl, [0x49], '10.1.16')))
    if app_id == 'BF':
        if 0x4A not in raw:
            notes.append('NVMe-only bifurcation register 0x4A was not collected')
        else:
            value = raw[0x4A]
            result['cable_type_high'] = bool(value & 0x10)
            result['configuration_valid_bit'] = bool(value & 0x80)
            if value & 0x80:
                result['configured_widths'] = [{'local_slot': bit, 'width': 'x2' if value & (1 << bit) else 'x1'} for bit in range(min(count, 4))]
                expected = 15 if value & 0x10 else 0
                if value & 0x0F != expected:
                    findings.append(finding('Warning', 'NVMe-only cable-type and bifurcation disagree',
                        'The reported CABLE_TYPE and slot-width bits are inconsistent. Verify the register capture, configuration and cable type.',
                        evidence(ctrl, [0x4A], '10.1.17 Table 54')))
            else:
                notes.append('NVMe-only configuration valid bit is clear; widths cannot be confirmed')
    return result, findings


def vpd_inventory(report):
    result = []
    for row in (report.get('sep_vpd') or [])[:256]:
        text = ' '.join(str(row.get(k, '')) for k in ('name', 'summary', 'raw'))
        serial = row.get('serial') or next(iter(re.findall(r'\bSN\s+([A-Za-z0-9_-]+)', text, re.I)), '')
        part = row.get('part_number') or next(iter(re.findall(r'\bPN\s+([A-Za-z0-9_-]+)', text, re.I)), '')
        names = [name for name in BOARD_APPS if re.search(r'\b'+re.escape(name)+r'\b', str(row.get('name', '')), re.I)]
        result.append({'bp': bp_key(row.get('bp')), 'name': row.get('name', ''), 'serial': serial,
                       'part_number': part, 'expected_application': BOARD_APPS[names[0]] if len(names) == 1 else '',
                       'source': row.get('source', ''), 'raw': row.get('raw', '')})
    return result


def build_topology(report, devices, boards, external_names):
    result = []
    controllers = list((report.get('pci', {}).get('storage') or [])[:128])
    other_drives = report.get('pci', {}).get('other_drives') or []
    if other_drives:
        controllers.append({'controller': 'Controller not recorded', 'drives': other_drives[:256], '_unassigned': True})
    for controller in controllers:
        adapter = controller.get('adapter') or {}
        label = adapter.get('name') or controller.get('controller', '')
        if identity(label) in external_names or re.search(r'\b\d{3,4}-\d+e\b', str(label), re.I):
            continue
        boot = bool(re.search(r'\bm\.?2\b|\bboot\b', str(label), re.I))
        serial = identity(adapter.get('serial'))
        serial_unique = serial and sum(identity((c.get('adapter') or {}).get('serial')) == serial for c in controllers) == 1
        linked = [b for b in boards if serial_unique and identity(b['serial']) == serial]
        for drive in (controller.get('drives') or [])[:256]:
            drive_boot = boot or (controller.get('_unassigned') and bool(re.search(r'\bm\.?2\b|\bboot\b', ' '.join(str(drive.get(k, '')) for k in ('description', 'name', 'form_factor')), re.I)))
            bay = number(drive.get('bay'))
            explicit = bp_key(drive.get('backplane') or drive.get('backplane_id'))
            candidates = [d for d in devices if d['range_valid'] and not d.get('mapping_conflict') and bay is not None
                          and d['start_slot'] <= bay < d['start_slot'] + d['slot_count']
                          and (d['application_id'] == 'BA') == bool(drive_boot)]
            proof = 'bay number only; controller-local numbering may differ'
            strong = False
            if explicit:
                candidates = [d for d in candidates if d['bp'] == explicit]
                proof, strong = 'explicit drive backplane identity and reported slot range', True
                if len(linked) == 1 and linked[0]['bp'] != explicit:
                    candidates, strong = [], False
                    proof = 'explicit drive backplane conflicts with controller/backplane serial identity'
            elif len(linked) == 1:
                candidates = [d for d in candidates if d['bp'] == linked[0]['bp']]
                proof, strong = 'unique controller/backplane serial and reported slot range', True
            if len(candidates) == 1:
                d = candidates[0]
                target, sep = d['bp'], d['sep']
                state = 'confirmed' if strong else 'candidate'
                if strong and controller.get('_unassigned'):
                    state = 'backplane confirmed; controller unresolved'
            else:
                target, sep = '', ''
                state = 'ambiguous' if candidates else 'unresolved'
            result.append({'controller': label, 'controller_slot': adapter.get('slot', ''), 'eid': adapter.get('eid', ''),
                           'bay': bay, 'drive_serial': drive.get('serial', ''), 'backplane': target, 'sep': sep,
                           'mapping': state, 'evidence': proof, 'candidates': [d['bp']+' '+d['sep'] for d in candidates],
                           'source': next((str((report.get('files') or {}).get(k)) for k in ('io_devices', 'dmdb') if (report.get('files') or {}).get(k) not in {None, '', 'missing'}), '')})
    return result


def collect_update_evidence(extract, files=None):
    """Bounded reads of own-report logs; no archive extraction or live requests."""
    result = {'events': [], 'sources': [], 'limitations': []}
    if extract is None or not Path(extract).is_dir():
        result['limitations'].append('Retained firmware log directory is unavailable')
        return result
    root = Path(extract).resolve()
    files = files or {}
    names = [files.get(k) for k in ('flash_history', 'pldm_log')]
    names += ['pstorage/flash/flash_history.log', 'pstorage/persist/fm/flash_history.log',
              'tmp/fm.log', 'tmp/ibmulog/bmu_fwrpm.log', 'var/log/pldm.log', 'tmp/var/log/pldm.log']
    visited = set()
    budget = 2 * 1024 * 1024
    for name in names:
        if not name or name == 'missing':
            continue
        path = Path(name)
        path = path if path.is_absolute() else root/path
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or resolved in visited or not resolved.is_file():
                continue
            visited.add(resolved)
            cap = min(512 * 1024, budget)
            if cap <= 0:
                result['limitations'].append('Firmware evidence byte budget reached')
                break
            with resolved.open('rb') as stream:
                blob = stream.read(cap + 1)
            truncated = len(blob) > cap
            blob = blob[:cap]; budget -= len(blob)
            source = resolved.relative_to(root).as_posix()
            result['sources'].append({'source': source, 'bytes_read': len(blob), 'truncated': truncated})
            lines = blob.decode('utf-8', errors='replace').splitlines()
            if truncated and not blob.endswith(b'\n'):
                lines = lines[:-1]
            for line_number, raw in enumerate(lines, 1):
                if not re.search(r'\bSEP\b|\bPSoC\b|backplane(?:[_ -]?\d+)?\b|\bSTOREXP\b|\bbp[_ ]*\d+[_ -]sep[_ ]*\d+\b', raw, re.I):
                    continue
                if not re.search(r'firmware|\bFW\b|updat|flash|bootload|rollback', raw, re.I):
                    continue
                if re.search(r'password|authorization|bearer|api[_ -]?key|\btoken\s*[:=]', raw, re.I):
                    continue
                result['events'].append({'source': source, 'line': line_number, 'evidence': raw.strip()[:700]})
                if len(result['events']) >= 80:
                    result['limitations'].append('Firmware event limit reached; other lines require raw-log review')
                    return result
            if truncated:
                result['limitations'].append(source + ': only the first bounded excerpt was inspected')
        except (OSError, ValueError):
            result['limitations'].append('One firmware source could not be read')
    if not result['sources']:
        result['limitations'].append('No supported backplane firmware log source was collected')
    return result


def correlate_updates(evidence_rows, devices):
    events = []
    for entry in evidence_rows[:80]:
        text = entry['evidence']
        identities = {('bp'+str(int(bp)), 'sep'+str(int(sep))) for bp, sep in re.findall(r'\bbp[_ ]*(\d+)[_ -]+sep[_ ]*(\d+)\b', text, re.I)}
        matches = [d for d in devices if len(identities) == 1 and (d['bp'], d['sep']) in identities]
        status = 'observed'
        # Script/transport outcomes do not establish a firmware update result.
        if not re.search(r'\bscript\b|\bMCTP\b|\btransfer\b|\bdownload\b|\bNIC\b|\bRAID\b|\bHBA\b', text, re.I):
            action = r'(?:firmware|\bFW\b)\s+(?:update|flash)(?:\s+from\s+[\w.()-]+\s+to\s+[\w.()-]+)?\s+(?:has\s+)?'
            if re.search(action + r'(?:failed|failure)\b', text, re.I):
                status = 'failure reported'
            elif re.search(action + r'(?:succeeded|successful|completed successfully)\b', text, re.I):
                status = 'success reported'
        version = re.search(r'\bfrom\s+([\w.()-]+)\s+to\s+([\w.()-]+)', text, re.I)
        events.append({**entry, 'bp': matches[0]['bp'] if len(matches) == 1 else '',
                       'sep': matches[0]['sep'] if len(matches) == 1 else '',
                       'association': 'explicit BP/SEP identity' if len(matches) == 1 else 'unresolved',
                       'result': status if len(matches) == 1 else 'observed',
                       'timestamp': next(iter(re.findall(r'\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d', text)), ''),
                       'reported_versions': {'from': version[1], 'to': version[2]} if version and len(matches) == 1 else {}})
    return events


def analyze_backplanes(report, firmware_evidence=None):
    scope = report.get('backplane_scope') or {}
    output = {'schema': 2, 'spec': dict(BACKPLANE_SPEC), 'devices': [], 'topology': [],
              'checks': [], 'firmware_events': [], 'log_sources': [], 'limitations': []}
    if scope.get('applicable') is False:
        output['limitations'].append(scope.get('reason', 'Built-in backplane evidence is outside this storage path'))
        return output
    rows = (report.get('sep_info') or [])[:512]
    controls = [r for r in rows if r.get('register_type') == 'ctrl']
    statuses = {(r.get('bp'), r.get('sep')): r for r in rows if r.get('register_type') == 'status'}
    boards = vpd_inventory(report)
    for ctrl in controls:
        raw = registers(ctrl)
        status = statuses.get((ctrl.get('bp'), ctrl.get('sep')), {})
        n = number(status.get('total_slots'))
        reported_count = n
        range_validation = status.get('range_validation', {})
        if 'mapped_count' in range_validation and n is not None:
            n = range_validation['mapped_count']
        start = number(ctrl.get('start_slot'))
        app_id = ctrl.get('application_id', '')
        legacy_sep = ctrl.get('decode_profile') == 'legacy_sep'
        linked = [b for b in boards if b['bp'] == bp_key(ctrl.get('bp'))]
        if len(linked) != 1:
            linked = []
        link, findings = decode_links(ctrl, status)
        usable = bool(ctrl.get('ctrl_signature_valid') == 'yes' and not ctrl.get('error')
                      and not ctrl.get('snapshot_conflict') and not ctrl.get('conflicting_offsets'))
        firmware = {'snapshot_version': ctrl.get('bp_firmware', ''), 'development_flag': 'not collected',
                    'debug_log': {'state': 'not collected'}}
        if ctrl.get('decode_profile') in {'v4_v5', 'egs_genoa'} and usable and app_id in SUPPORTED:
            if 0x1C in raw:
                firmware['development_flag'] = f'0x{raw[0x1C]:02X}'
                if raw[0x1C] == 0x5A:
                    spec_text = 'EGS/Genoa v0.81' if ctrl.get('decode_profile') == 'egs_genoa' else 'SP-000008 v1.06'
                    findings.append(finding('Info', 'Backplane development firmware blocks automatic BMC update',
                        f'The development-firmware marker is 0x5A. Per {spec_text}, BMC must not replace it with embedded firmware. This explains an update restriction, not a failed flash.',
                        evidence(ctrl, [0x08, 0x1C], 'development firmware table')))
            if all(i in raw for i in range(0x3C, 0x40)):
                command, response = raw[0x3C], raw[0x3D]
                length = raw[0x3E] | raw[0x3F] << 8
                firmware['debug_log'] = {'command': f'0x{command:02X}', 'response': f'0x{response:02X}', 'length': length,
                    'state': 'response ready; payload must be collected separately' if command in range(1, 7) and response == command and length > 0 else 'no completed log response',
                    'payload_decoded': False}
            expected = EXPECTED_SILICON.get(app_id)
            if expected and all(i in raw for i in range(4, 8)):
                silicon = ''.join(f'{raw[i]:02X}' for i in range(4, 8))
                if silicon not in {expected, ''.join(reversed([expected[i:i+2] for i in range(0, 8, 2)]))}:
                    table = 'EGS/Genoa v0.81 Table 33' if ctrl.get('decode_profile') == 'egs_genoa' else 'SP-000008 v1.06 Table 37'
                    findings.append(finding('Warning', 'SEP application and silicon identity need verification',
                        f'The application/silicon combination differs from the {table} identity table. Verify the board and applicable firmware before selecting an update package.',
                        evidence(ctrl, [4, 5, 6, 7, 0x10], 'application and silicon identity')))
            if linked and linked[0]['expected_application'] and linked[0]['expected_application'] != app_id:
                findings.append(finding('Warning', 'Backplane VPD and SEP application disagree',
                    f'The explicitly reported backplane name and SEP Application ID differ from the applicable {profile_spec(ctrl)} identity map. Verify identity and mapping before assigning a firmware image.',
                    {'register': evidence(ctrl, [0x10], '15 Table 70'), 'vpd': linked[0]}))
        proof = evidence(ctrl, [0x10, 0x12, 0x13, 0x16, 0x17, 0x18, 0x19], '5, 10.1.3-10.1.6, 15')
        if legacy_sep:
            proof = evidence(ctrl, [0x0D, 0x10, 0x12, 0x13], '')
            proof['spec'] = ctrl.get('legacy_spec', '')
            proof['slot_count'] = {'source': status.get('source', ''), 'command': status.get('command', ''),
                                   'register': 'Status[0x01]', 'value': n}
            proof['start_slot_source'] = ctrl.get('start_slot_source', '')
        device = {'bp': bp_key(ctrl.get('bp')), 'sep': ctrl.get('sep', ''),
                  'name': linked[0]['name'] if linked else '', 'location': ctrl.get('location', ''),
                  'application_id': app_id, 'application': ctrl.get('application', ''),
                  'decode_profile': ctrl.get('decode_profile', ''), 'spec': profile_spec(ctrl),
                  'start_slot': start, 'slot_count': n, 'backplane_total_slots': None if legacy_sep else number(ctrl.get('total_slots')),
                  'reported_slot_count': reported_count, 'unmapped_count': range_validation.get('unmapped_count', 0),
                  'backplane_number': raw.get(0x16, 0) & 7 if not legacy_sep and 0x16 in raw else None,
                  'starting_hfc': None if legacy_sep else raw.get(0x19), 'nvme_slot_id': raw.get(0x12), 'nvme_bay_id': raw.get(0x13),
                  'reverse_bay_numbering': None if legacy_sep else raw.get(0x1D),
                  'range_valid': bool(usable and status.get('data_validation', {}).get('diagnostics_valid') and n and start is not None
                                      and range_validation.get('valid', True)),
                  'links': link, 'firmware': firmware, 'evidence': proof}
        output['devices'].append(device); output['checks'].extend(findings)
    devices = output['devices']
    for bp in dict.fromkeys(d['bp'] for d in devices):
        group = [d for d in devices if d['bp'] == bp and d['range_valid']]
        for i, d in enumerate(group):
            for other in group[i+1:]:
                overlap = max(d['start_slot'], other['start_slot']) < min(d['start_slot']+d['slot_count'], other['start_slot']+other['slot_count'])
                repeated_hfc = d['backplane_number'] == other['backplane_number'] and d['starting_hfc'] is not None and d['starting_hfc'] == other['starting_hfc']
                totals_disagree = (d['backplane_total_slots'] is not None and other['backplane_total_slots'] is not None
                                   and d['backplane_total_slots'] != other['backplane_total_slots'])
                if overlap or repeated_hfc or totals_disagree:
                    d['mapping_conflict'] = other['mapping_conflict'] = True
                    output['checks'].append(finding('Warning', 'Backplane SEP mapping is inconsistent',
                        'The collected SEP ranges, HFC identities or backplane slot totals conflict. Resolve the mapping before locating a drive or selecting a firmware target.',
                        {'first': d['evidence'], 'second': other['evidence'], 'overlapping_bays': overlap, 'repeated_hfc': repeated_hfc, 'spec': '; '.join(sorted({d.get('spec', 'SP-000008 v1.06'), other.get('spec', 'SP-000008 v1.06')}))}))
    external = {identity(r.get('name')) for r in scope.get('external_adapters', [])}
    output['topology'] = build_topology(report, devices, boards, external)
    fw = firmware_evidence or {}
    output['firmware_events'] = correlate_updates(fw.get('events', []), devices)
    output['log_sources'] = fw.get('sources', [])
    output['limitations'].extend(fw.get('limitations', []))
    if any(r['mapping'] != 'confirmed' for r in output['topology']):
        output['limitations'].append('Bay-number-only associations remain candidates; controller/backplane identity is not confirmed')
    return output
