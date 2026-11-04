"""Backplane diagnostic contracts from SP-000008 v1.06, Tables 39 and 55-63."""
import copy
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import app


def capture(app_id='BB', values=(0xC0, 0xC3), communication=0xD3, enabled=0xBE,
            result=0, configuration=1, vmd=5, extended=None, start=0):
    ctrl = [0] * 32
    ctrl[:4] = [0x50, 0x53, 0x6F, 0x43]
    ctrl[4:8] = [0xEE, 0x43, 0x11, 0x18] if app_id in {'BF', 'C0', 'C1'} else [0xE2, 0x17, 0x21, 0]
    ctrl[8] = 0x26
    ctrl[12:15] = [result, configuration, enabled]
    ctrl[16] = int(app_id, 16)
    ctrl[21] = vmd
    ctrl[23:25] = [len(values), start]
    ctrl[26] = 7
    n = len(values)
    status = [0x26, n, (-0x26-n) & 255, communication, *values, 4, 0x13]
    status.append((-sum(status[3:])) & 255)
    ext = [0x81] * n if extended is None else extended
    status.extend(ext)
    status.append((-sum(ext)) & 255)
    return ctrl, status


def parse(ctrl, status, profile='v4_v5'):
    lines = []
    for name, values in [('ctrl', ctrl), ('status', status)]:
        lines.append(f'#cio -n bp1_sep0_{name} -m block -t wr 32 0')
        lines.extend(app.split_v4_register_dump(' '.join(f'{v:02X}' for v in values)))
    return app.parse_sep_info('\n'.join(lines), profile)


def report(rows):
    return {'id': 'spec-test', 'format': 'v4_minilog', 'system': {}, 'firmware': [], 'source_file': 'test.tar.gz', 'files': {}, 'events': [], 'fru': [],
            'pci': {'adapters': [], 'storage': []}, 'sep_info': rows, 'sep_vpd': [],
            'nic_details_version': 1, 'pcie_details_version': 1}


class BackplaneSpecTests(unittest.TestCase):
    def checks(self, rows):
        return [c for c in app.run_automated_checks(report(rows)) if c['category'] == 'Backplane']

    def test_vmd_bits_map_to_even_numbered_ports(self):
        for value, expected in [(5, '0, 4'), (15, '0, 2, 4, 6'), (10, '2, 6'), (0x80, '')]:
            with self.subTest(value=value):
                self.assertEqual(parse(*capture(vmd=value))[0]['vmd_enabled_ports'], expected)

    def test_nv5_canonical_presence_empty_fail_rebuild_and_locate(self):
        for value, category in [(0x81, 'nvme'), (0x83, 'empty'), (0xA1, 'fail'),
                                (0x84, 'fault'), (0x86, 'fault'), (0x91, 'rebuild'), (0x89, 'locate')]:
            with self.subTest(value=value):
                self.assertEqual(app.decode_bp_slot_status(f'{value:02x}', '', application_id='bf')[1], category)
                rows = parse(*capture('BF', (value,)))
                self.assertTrue(rows[1]['diagnostics_valid'])
                self.assertNotIn('Unknown', rows[1]['slot_status'])

    def test_nv5_reserved_bit_conflict_is_explicit_and_cannot_raise_drive_fault(self):
        rows = parse(*capture('BF', (0xE1,)))
        self.assertFalse(rows[1]['diagnostics_valid'])
        self.assertIn('Reserved bit 6', json.dumps(rows[1]))
        self.assertFalse(rows[1]['fail_slots'])
        self.assertFalse(any(c['severity'] == 'Critical' for c in self.checks(rows)))

    def test_apid_selects_layout_even_when_management_byte_looks_like_other_capability(self):
        for app_id, value, expected in [('BF', 0x81, 'nvme_only'), ('BB', 0x81, 'anybay'), ('BC', 0xC2, 'anybay_edsff')]:
            for management in (0x05, 0x07, 0x27):
                with self.subTest(app_id=app_id, management=management):
                    ctrl, status = capture(app_id, (value,));ctrl[26] = management
                    rows = parse(ctrl, status)
                    self.assertEqual(rows[1]['status_profile'], expected)
                    self.assertTrue(rows[1]['diagnostics_valid'])
                    self.assertFalse(rows[1]['bp_type_fault_slots'])
        self.assertIn('U.2', parse(*capture('BF', (0x81,)))[1]['slot_status'])
        self.assertIn('U.3', parse(*capture('BB', (0x81,)))[1]['slot_status'])

    def test_all_supported_type_faults_reach_checks_and_badges(self):
        for app_id, values in [('BF', (0x84, 0x86)), ('BB', (0xC4, 0xC5, 0xC6, 0x85)),
                               ('BC', (0xC4, 0xC5, 0xC6, 0x46)), ('BE', (0xC4, 0x44)), ('C0', (0x44,)), ('C1', (0x44,))]:
            with self.subTest(app_id=app_id):
                rows = parse(*capture(app_id, values, start=16));status=rows[1]
                expected=', '.join(str(16+i) for i in range(len(values)))
                self.assertEqual(status['bp_type_fault_slots'], expected)
                faults=[c for c in self.checks(rows) if 'BP type fault indication' in c['title']]
                self.assertEqual(len(faults), 1)
                self.assertEqual(faults[0]['severity'], 'Warning')
                self.assertIn('APID '+app_id, faults[0]['evidence'])
                self.assertIn('<b>BP Type Fault</b>', app.render_backplane_registers(rows, 'v4_minilog'))
                self.assertFalse(status['fail_slots'])

    def test_type_fault_bit_is_not_lost_with_fail_rebuild_or_locate(self):
        for app_id, bases in [('BF', (0x84, 0x86)), ('BB', (0xC4, 0xC5, 0xC6)), ('BC', (0xC4, 0x46)), ('BE', (0x44,))]:
            for base in bases:
                for attention in range(0, 0x40, 8):
                    with self.subTest(app_id=app_id, byte=base|attention):
                        rows=parse(*capture(app_id, (base|attention,)))
                        status=rows[1];checks=self.checks(rows)
                        self.assertTrue(status['diagnostics_valid'])
                        self.assertEqual(status['bp_type_fault_slots'], '0')
                        self.assertEqual(bool(status['fail_slots']), bool(attention & 0x20))
                        self.assertEqual(bool(status['rebuild_slots']), bool(attention & 0x10))
                        self.assertEqual(bool(status['locate_slots']), bool(attention & 0x08))
                        self.assertTrue(any('BP type fault indication' in c['title'] for c in checks))
                        self.assertEqual(any(c['severity']=='Critical' for c in checks), bool(attention & 0x20))
                        page=app.render_backplane_registers(rows, 'v4_minilog')
                        self.assertIn('<b>BP Type Fault</b>slot 0', page)
                        self.assertEqual('<b>Drive Fail</b>slot 0' in page, bool(attention & 0x20))

    def test_normal_nvme_empty_and_attention_do_not_become_type_fault(self):
        for app_id, values in [('BF', (0x81, 0x83, 0x91, 0x89, 0xA1)),
                               ('BB', (0xC0, 0xC1, 0x81, 0xC3, 0xD1, 0xC9, 0xE1)),
                               ('BC', (0xC0, 0xC1, 0x81, 0xC2, 0x42, 0xC3))]:
            for config in (1, 0xA0):
                rows=parse(*capture(app_id, values, configuration=config))
                self.assertFalse(rows[1]['bp_type_fault_slots'])
                self.assertFalse(any('BP type fault indication' in c['title'] for c in self.checks(rows)))

    def test_wrong_layout_bytes_are_unknown_or_limited_without_borrowing(self):
        for app_id, values in [('BF', (0xC4, 0xC5, 0xC1, 0xC3)), ('BB', (0x84, 0x86, 0x83)),
                               ('D5', (0xC4, 0x84, 0xC5))]:
            rows=parse(*capture(app_id, values))
            self.assertFalse(rows[1]['bp_type_fault_slots'])
            self.assertFalse(rows[1]['fail_slots'])
            self.assertFalse(any('BP type fault indication' in c['title'] for c in self.checks(rows)))
            self.assertTrue(all(o['limitations'] for o in rows[1]['slot_observations']))

    def test_undocumented_empty_plus_drive_flags_does_not_invent_a_fault(self):
        for app_id, empty in [('BF',0x83), ('BB',0xC3)]:
            for flag in (0x04,0x08,0x10,0x20):
                rows=parse(*capture(app_id,(empty|flag,)))
                self.assertEqual(rows[1]['unknown_slots'],'0')
                self.assertFalse(rows[1]['bp_type_fault_slots'])
                self.assertFalse(rows[1]['fail_slots'])
                self.assertTrue(rows[1]['slot_observations'][0]['limitations'])

    def test_legacy_identity_is_not_guessed_from_sibling_status_bytes(self):
        self.assertIs(app.choose_bp_status_table('07', ['C2','C4']), app.TRI_MODEL_BP_STATUS)
        self.assertIs(app.choose_bp_status_table('05', ['C2','85']), app.SAS_SATA_BP_STATUS)
        self.assertEqual(app.choose_bp_status_table('00', ['C4','85']), {})
        self.assertEqual(app.choose_bp_status_table('07', ['C4'], 'D5'), {})
        self.assertEqual(app.decode_bp_slot_status('85', '00')[1], 'unknown')
        self.assertEqual(app.decode_bp_slot_status('87', '00')[1], 'unknown')
        self.assertEqual(app.decode_bp_slot_status('87', '07')[1], 'unknown')
        self.assertEqual(app.decode_bp_slot_status('87', '06')[1], 'boot_drive')

    def test_invalid_type_fault_flags_never_become_findings(self):
        for app_id, value in [('BF',0x84), ('BB',0xC4), ('BC',0xC5)]:
            for kwargs in ({'communication':0x80}, {'enabled':0xB0}, {'result':0xFF}):
                rows=parse(*capture(app_id, (value,), **kwargs))
                self.assertFalse(rows[1]['bp_type_fault_slots'])
                self.assertFalse(any('BP type fault indication' in c['title'] for c in self.checks(rows)))

    def test_mixed_sep_families_keep_independent_global_bay_faults(self):
        nv5=parse(*capture('BF', (0x84,), start=8))
        anybay=parse(*capture('BB', (0x81,), start=24))
        lines=[]
        for rows, name in ((nv5,'bp1'), (anybay,'bp2')):
            for row in rows:
                lines.extend([row['command'].replace('bp1_',name+'_'), *row['registers']])
        rows=app.parse_sep_info('\n'.join(lines),'v4_v5')
        self.assertEqual(rows[1]['status_profile'],'nvme_only')
        self.assertEqual(rows[1]['bp_type_fault_slots'],'8')
        self.assertEqual(rows[3]['status_profile'],'anybay')
        self.assertFalse(rows[3]['bp_type_fault_slots'])
        self.assertIn('slot 24: NVMe Drive U.3',rows[3]['slot_status'])
        faults=[c for c in self.checks(rows) if 'BP type fault indication' in c['title']]
        self.assertEqual(len(faults),1)
        self.assertIn('bp1 sep0 slots 8',faults[0]['evidence'])

    def test_unrecognized_sibling_code_does_not_hide_valid_type_fault(self):
        ctrl,status=capture('40',(0xC2,0xC4));ctrl[4:8]=[0xE2,0x14,0x21,0]
        rows=parse(ctrl,status,'v1_v3')
        self.assertEqual(rows[1]['status_profile'],'egs_anybay')
        self.assertEqual(rows[1]['unknown_slots'],'0')
        self.assertEqual(rows[1]['bp_type_fault_slots'],'1')
        self.assertTrue(any('BP type fault indication' in c['title'] for c in self.checks(rows)))

    def test_marker_three_reports_refresh_type_fault_for_api_ai_tool_and_page(self):
        for app_id, value, is_fault in [('BF',0x84,True), ('BB',0xC4,True), ('BF',0x81,False)]:
            stored=report(parse(*capture(app_id, (value,))))
            stored['backplane_details_version']=3
            stored['backplane_analysis']={'schema':2}
            stored['sep_info'][1].update(bp_type_fault_slots='', status_profile='stale')
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);folder=root/stored['id'];folder.mkdir();path=folder/'report.json'
                path.write_text(json.dumps(stored));before=path.read_bytes()
                with patch.object(app, 'REPORT_DIR', root):
                    updated=app.enrich_nic_report(copy.deepcopy(stored))
                    self.assertEqual(updated['backplane_details_version'],6)
                    self.assertEqual(bool(updated['sep_info'][1]['bp_type_fault_slots']),is_fault)
                    ai=json.dumps(app.compact_report_for_ai(updated))
                    self.assertIn('status_profile', ai)
                    self.assertEqual('BP type fault indication detected' in json.dumps(app.check_backplane_health_tool(updated)),is_fault)
                    self.assertEqual('<b>BP Type Fault</b>' in app.render_report(updated),is_fault)
                    self.assertEqual(path.read_bytes(),before)

    def test_validated_snapshot_can_pass_and_real_drive_fail_still_critical(self):
        rows = parse(*capture('BF', (0x81, 0x83)))
        self.assertTrue(any(c['severity'] == 'Pass' for c in self.checks(rows)))
        rows = parse(*capture('BF', (0xA1, 0x83)))
        self.assertEqual(rows[1]['fail_slots'], '0')
        self.assertTrue(any(c['severity'] == 'Critical' for c in self.checks(rows)))

    def test_header_checksum_failure_suppresses_fault_and_pass(self):
        ctrl, status = capture('BF', (0xA1,))
        status[2] ^= 1
        rows = parse(ctrl, status)
        self.assertEqual(rows[1]['data_validation']['header_checksum'], 'invalid')
        self.assertFalse(rows[1]['fail_slots'])
        self.assertFalse(any(c['severity'] in {'Critical', 'Pass'} for c in self.checks(rows)))

    def test_payload_checksum_failure_suppresses_fault(self):
        ctrl, status = capture('BB', (0xE0,))
        status[4] ^= 1
        rows = parse(ctrl, status)
        self.assertEqual(rows[1]['data_validation']['status_checksum'], 'invalid')
        self.assertFalse(rows[1]['fail_slots'])

    def test_extended_checksum_failure_suppresses_edsff_fault(self):
        ctrl, status = capture('BE', (0xE0,))
        status[-1] ^= 1
        rows = parse(ctrl, status)
        self.assertEqual(rows[1]['data_validation']['extended_checksum'], 'invalid')
        self.assertFalse(rows[1]['fail_slots'])

    def test_standby_does_not_report_communication_or_drive_failure(self):
        rows = parse(*capture('BB', (0xE0,), communication=0x80))
        self.assertFalse(rows[1]['data_validation']['pgood'])
        self.assertFalse(rows[1]['fail_slots'])
        self.assertTrue(all(c['severity'] == 'Info' for c in self.checks(rows)))

    def test_invalid_communication_byte_cannot_establish_power(self):
        rows = parse(*capture('BB', (0xE0,), communication=0x40))
        self.assertIsNone(rows[1]['data_validation']['pgood'])
        self.assertFalse(rows[1]['fail_slots'])

    def test_drive_valid_bit_and_autoconfiguration_gate_diagnostics(self):
        for kwargs in ({'values': (0x21,)}, {'values': (0xA1,), 'enabled': 0xB0},
                       {'values': (0xA1,), 'enabled': 0}, {'values': (0xA1,), 'result': 0xFF}):
            rows = parse(*capture('BF', **kwargs))
            self.assertFalse(rows[1]['fail_slots'])
            self.assertFalse(any(c['severity'] in {'Critical', 'Pass'} for c in self.checks(rows)))

    def test_saved_configuration_ba_with_valid_live_status_keeps_drive_alerts(self):
        rows = parse(*capture('BF', (0xA1,), result=0xBA))
        self.assertIn('Saved/default', rows[0]['auto_config_status'])
        self.assertTrue(rows[1]['diagnostics_valid'])
        checks = self.checks(rows)
        self.assertTrue(any(c['severity'] == 'Critical' for c in checks))
        self.assertTrue(any('auto-configuration' in c['title'] for c in checks))

    def test_edsff_bit7_is_presence_not_validity(self):
        for app_id in ['BC', 'BE', 'C0', 'C1']:
            rows = parse(*capture(app_id, (0x42 if app_id == 'BC' else 0x40,)))
            self.assertTrue(rows[1]['diagnostics_valid'])
            self.assertIn('EDSFF', rows[1]['drive_presence'])
        rows = parse(*capture('BE', (0x60,), extended=[0]))
        self.assertFalse(rows[1]['fail_slots'])
        self.assertIn('Extended drive status valid bit', json.dumps(rows[1]))

    def test_unknown_application_never_borrows_sas_status_table(self):
        rows = parse(*capture('D5', (0xA0,)))
        self.assertFalse(rows[1]['fail_slots'])
        self.assertFalse(any(c['severity'] == 'Critical' for c in self.checks(rows)))

    def test_read_failure_and_invalid_identity_are_warnings_not_crash_findings(self):
        for signature in (False, True):
            ctrl, status = capture('BB', (0xE0,))
            if signature:
                ctrl[0] = 0
                rows = parse(ctrl, status)
            else:
                rows = app.parse_sep_info('#cio -n bp1_sep0_ctrl\nCIO read failed\n#cio -n bp1_sep0_status\nCIO timeout\n', 'v4_v5')
            checks = self.checks(rows)
            self.assertTrue(any(c['severity'] == 'Warning' for c in checks))
            self.assertFalse(any(c['severity'] == 'Critical' or 'crash' in c['title'] for c in checks))

    def test_c4_drive_type_fault_is_not_suppressed_by_nvme_only_configuration(self):
        for config in (0xA0, 1):
            rows = parse(*capture('BB', (0xC4,), configuration=config))
            checks = self.checks(rows)
            fault = next(c for c in checks if 'BP type fault' in c['title'])
            self.assertEqual(fault['severity'], 'Warning')
            self.assertEqual(rows[1]['bp_type_fault_slots'], '0')
            self.assertEqual(rows[1]['fault_slots'], '0')
            self.assertFalse(any(c['severity'] == 'Critical' for c in checks))
            html = app.render_backplane_registers(rows, 'v4_minilog')
            self.assertIn('<b>BP Type Fault</b>slot 0', html)
            self.assertNotIn('<b>NVMe Only</b>', html)

    def test_nvme_only_configuration_without_fault_status_remains_normal(self):
        rows = parse(*capture('BB', (0xC1,), configuration=0xA0))
        self.assertFalse(rows[1]['fault_slots'])
        self.assertFalse(rows[1]['bp_type_fault_slots'])
        self.assertFalse(any(c['severity'] in {'Critical', 'Warning'} for c in self.checks(rows)))

    def test_legacy_trimodel_c4_is_scoped_to_its_sep_and_global_bay_numbers(self):
        raw = '''#cio -n bp3_sep0_ctrl -m block -t wr 32 0
rData[00]: 50 53 6F 43 E2 14 21 00 31 00 00 00 00 05 BE 00
rData[10]: 40 00 50 10 00 00 03 08 10 00 07 00 00 00 00 00
#cio -n bp3_sep0_status -m block -t wr 32 0
rData[00]: 31 04 CB CF C4 C4 C4 C4 04 10 0D 82 82 82 82 F8
rData[10]: 00 00 00 00 00 00 00 00 00 00 00 FF FF FF FF FF
#cio -n bp3_sep1_ctrl -m block -t wr 32 0
rData[00]: 50 53 6F 43 E2 14 21 00 31 00 00 00 00 06 BE 00
rData[10]: 40 00 54 14 00 00 03 08 14 05 07 00 00 00 00 00
#cio -n bp3_sep1_status -m block -t wr 32 0
rData[00]: 31 04 CB CF C0 C1 C1 C1 04 10 1A 81 81 81 81 FC
rData[10]: 00 00 00 00 00 00 00 00 00 00 00 FF FF FF FF FF'''
        rows = app.parse_sep_info(raw)
        self.assertEqual(rows[1]['fault_slots'], '16, 17, 18, 19')
        self.assertEqual(rows[1]['bp_type_fault_slots'], '16, 17, 18, 19')
        self.assertFalse(rows[3]['fault_slots'])
        checks = self.checks(rows)
        faults = [c for c in checks if 'BP type fault' in c['title']]
        self.assertEqual(len(faults), 1)
        self.assertIn('bp3 sep0', faults[0]['evidence'])
        self.assertIn('Control[0x0D]=05', faults[0]['evidence'])
        self.assertIn('bit 2=1', faults[0]['evidence'])

    def test_invalid_c4_snapshot_cannot_raise_type_fault(self):
        for app_id in ('BB', 'BC'):
            ctrl, status = capture(app_id, (0xC4,))
            status[2] ^= 1
            rows = parse(ctrl, status)
            self.assertFalse(rows[1]['bp_type_fault_slots'])
            self.assertFalse(any('BP type fault' in c['title'] for c in self.checks(rows)))

    def test_partial_capture_cannot_pass_or_raise_slot_fault(self):
        ctrl, status = capture('BF', (0xA1,))
        rows = parse(ctrl, status[:5])
        self.assertFalse(rows[1]['fail_slots'])
        self.assertFalse(any(c['severity'] in {'Pass', 'Critical'} for c in self.checks(rows)))

    def test_invalid_slot_does_not_hide_another_valid_slot_failure(self):
        rows = parse(*capture('BF', (0x01, 0xA1)))
        self.assertFalse(rows[1]['diagnostics_valid'])
        self.assertEqual(rows[1]['fail_slots'], '1')
        self.assertTrue(any(c['severity'] == 'Critical' for c in self.checks(rows)))

    def test_boot_and_legacy_layouts_keep_their_own_decoding(self):
        ctrl, status = capture('BA', (0x40, 0x40))
        ctrl[26] = 6
        rows = parse(ctrl, status)
        self.assertEqual(rows[0]['application'], 'SEP BRV4')
        self.assertIn('SAS/SATA', rows[1]['drive_presence'])
        ctrl, status = capture('D5', (0x80, 0xA0))
        ctrl[4:8] = [0x10, 0x0A, 0x11, 0xA0]
        ctrl[26] = 5
        rows = parse(ctrl, status, 'v1_v3')
        self.assertEqual(rows[1]['fail_slots'], '1')
        self.assertEqual(rows[1]['data_validation']['profile'], 'legacy')

    def test_legacy_refresh_updates_api_ai_and_page_without_rewriting_report(self):
        rows = parse(*capture('BF', (0x81, 0x83)))
        # Emulate pre-release report fields and stale diagnostics.
        for r in rows:
            for k in ('data_validation', 'slot_observations', 'diagnostics_valid'):
                r.pop(k, None)
        rows[1]['slot_status'] = 'slot 0: Unknown 81'
        stored = report(rows)
        stored['automated_checks'] = [{'category': 'Backplane', 'severity': 'Critical', 'title': 'Backplane firmware crash suspected'}]
        stored['pci']['storage'] = [{'controller': 'RAID 540', 'adapter': {'name': 'RAID 540'}, 'drives': [{'serial': 'retained'}]}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / stored['id']; folder.mkdir()
            path = folder / 'report.json'
            path.write_text(json.dumps(stored))
            before = path.read_bytes()
            with patch.object(app, 'REPORT_DIR', root):
                updated = app.enrich_nic_report(copy.deepcopy(stored))
                self.assertIn('NVMe Drive U.2', updated['sep_info'][1]['slot_status'])
                self.assertEqual(updated['pci']['storage'], stored['pci']['storage'])
                context = app.compact_report_for_ai(updated)
                self.assertTrue(context['backplane_registers'][1]['diagnostics_valid'])
                tool = app.check_backplane_health_tool(updated)
                self.assertNotIn('crash suspected', json.dumps(tool))
                page = app.render_report(updated)
                self.assertNotIn('Snapshot validation:', page)
                self.assertNotIn('V3 / V4 source coverage', page)
                server = app.FFDCThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/report?id=spec-test', timeout=5) as response:
                        api = json.load(response)
                    self.assertTrue(api['sep_info'][1]['diagnostics_valid'])
                    self.assertEqual(api['backplane_details_version'], 6)
                    self.assertNotIn('crash suspected', json.dumps(api['automated_checks']))
                finally:
                    server.shutdown(); server.server_close(); thread.join(timeout=2)
                self.assertEqual(path.read_bytes(), before)

    def test_new_analysis_persists_current_validation_marker(self):
        from test_nic_integration import tar_bytes
        ctrl, status = capture('BF', (0x81, 0x83))
        bp = {'DriveBackplanes': [], 'Backplane1': {'Control': [' '.join(f'{b:02X}' for b in ctrl)], 'Status': [' '.join(f'{b:02X}' for b in status)]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); upload = root/'ffdc.tar.gz'
            upload.write_bytes(tar_bytes({'minilog.json': '{}', 'backplanes.json': json.dumps(bp)}, 'w:gz'))
            with patch.object(app, 'REPORT_DIR', root/'reports'), patch.object(app, 'API_KEY_FILE', root/'unused-test-key'):
                result = app.analyze(upload, cleanup=False)
                self.assertEqual(result['backplane_details_version'], 6)
                saved = json.loads((root/'reports'/result['id']/'report.json').read_text())
                self.assertTrue(saved['sep_info'][1]['diagnostics_valid'])

    def test_conflicting_capture_cannot_mix_control_and_status_snapshots(self):
        ctrl, status = capture('BF', (0xA1,))
        rows = parse(ctrl, status)
        lines = []
        for row in [rows[0], rows[0], rows[1]]:
            lines.extend([row['command'], *row['registers']])
        parsed = app.parse_sep_info('\n'.join(lines), 'v4_v5')
        self.assertFalse(parsed[-1]['fail_slots'])
        self.assertIn('unambiguously', json.dumps(parsed[-1]))

    def test_invalid_bytes_are_isolated_to_their_own_backplane(self):
        good = parse(*capture('BF', (0xA1,)))
        bad = parse(*capture('BF', (0xA1,), communication=0x80))
        lines = []
        for index, row in enumerate(good + bad):
            command = row['command'] if index < len(good) else row['command'].replace('bp1_', 'bp2_')
            lines.extend([command, *row['registers']])
        parsed = app.parse_sep_info('\n'.join(lines), 'v4_v5')
        self.assertEqual(parsed[1]['fail_slots'], '0')
        self.assertFalse(parsed[3]['fail_slots'])


if __name__ == '__main__':
    unittest.main()
