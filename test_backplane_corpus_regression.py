"""Count/range defects found by replaying retained FFDCs on 2026-10-19."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from test_backplane_spec import capture, parse, report


REAL_TEN_BAY = '''#cio -n bp1_sep0_ctrl -m block -t wr 32 0
rData[00]: 50 53 6F 43 EE 43 11 18 03 00 00 00 00 01 BE 00
rData[10]: BF 00 40 00 00 00 00 0A 00 00 06 0F 00 00 00 00
rData[20]: 00 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00
rData[30]: 00 00 00 00 00 00 03 FF FF FF FF FF FF FF FF FF
rData[40]: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF
rData[50]: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF
#cio -n bp1_sep0_status -m block -t wr 32 0
rData[00]: 03 04 F9 C1 81 81 81 81 04 01 36 81 81 81 81 FC
rData[10]: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
#cio -n bp1_sep1_ctrl -m block -t wr 32 0
rData[00]: 50 53 6F 43 EE 43 11 18 03 00 00 00 00 02 BE 00
rData[10]: BF 00 44 04 00 00 00 0A 04 01 06 0F 00 00 00 00
rData[20]: 00 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00
rData[30]: 00 00 00 00 00 00 03 FF FF FF FF FF FF FF FF FF
rData[40]: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF
rData[50]: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF
#cio -n bp1_sep1_status -m block -t wr 32 0
rData[00]: 03 04 F9 C1 81 81 A1 A1 04 01 F6 81 81 82 82 FA
rData[10]: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
#cio -n bp1_sep2_ctrl -m block -t wr 32 0
rData[00]: 50 53 6F 43 EE 43 11 18 03 00 00 00 00 03 BE 00
rData[10]: BF 00 48 08 00 00 00 0A 08 02 06 03 00 00 00 00
rData[20]: 00 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00
rData[30]: 00 00 00 00 00 00 03 FF FF FF FF FF FF FF FF FF
rData[40]: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF
rData[50]: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF
#cio -n bp1_sep2_status -m block -t wr 32 0
rData[00]: 03 04 F9 C1 00 81 80 80 04 01 B9 81 81 81 81 FC
rData[10]: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00'''


class RetainedCorpusRegressionTests(unittest.TestCase):
    def test_multi_slot_fail_rebuild_and_locate_badges_match_comma_lists(self):
        for raw, label in ((0xA1, 'Drive Fail'), (0x91, 'Rebuilding'), (0x89, 'Locate')):
            with self.subTest(label=label):
                rows = parse(*capture('BF', (raw, raw, raw), start=6))
                page = app.render_backplane_registers(rows, 'v4_minilog')
                self.assertIn(f'<b>{label}</b>slot 6-8', page)

    def test_real_ten_bay_capture_preserves_four_bytes_without_inventing_bays(self):
        rows = app.parse_sep_info(REAL_TEN_BAY, 'v4_v5')
        self.assertEqual(rows[3]['fail_slots'], '6, 7')
        status = rows[-1]
        self.assertEqual(status['status_values'], ['00', '81', '80', '80'])
        self.assertEqual([o['slot'] for o in status['slot_observations']], [8, 9, None, None])
        self.assertEqual([o['local_index'] for o in status['unmapped_observations']], [2, 3])
        self.assertEqual(status['range_validation']['mapped_count'], 2)
        self.assertFalse(status['range_validation']['valid'])
        self.assertEqual(status['unknown_slots'], '8')
        self.assertIn('slot 9:', status['slot_status'])
        self.assertNotIn('slot 10:', status['slot_status'])
        analysis = app.analyze_backplanes(report(rows))
        device = analysis['devices'][-1]
        self.assertEqual(device['slot_count'], 2)
        self.assertEqual(device['reported_slot_count'], 4)
        self.assertFalse(device['range_valid'])
        html = app.render_backplane_registers(rows, 'v4_minilog')
        self.assertIn('local index 2 = 80', html)
        self.assertNotIn('slot None', html)
        self.assertIn('8-9; 2 unmapped', app.render_backplane_analysis(analysis))

    def test_zero_boundary_is_not_replaced_by_fallback_total(self):
        ctrl, status = capture('BB', (0xE4, 0xC0))
        raw = '\n'.join(line for r in parse(ctrl, status) for line in [r['command'], *r['registers']])
        raw += '\n' + raw.replace('sep0', 'sep1')
        rows = app.parse_sep_info(raw, 'v4_v5')
        first = rows[1]
        self.assertEqual(first['range_validation']['capacity'], 0)
        self.assertEqual(len(first['slot_observations']), 2)
        self.assertTrue(all(o['slot'] is None for o in first['slot_observations']))
        self.assertFalse(first['fail_slots'])
        self.assertFalse(first['bp_type_fault_slots'])

    def test_missing_control_retains_local_bytes_and_cannot_raise_faults(self):
        rows = app.parse_sep_info('''#cio -n bp3_sep0_status -m block -t wr 32 0
rData[00]: 03 04 F9 C1 81 81 81 A1 04 01 16 81 81 81 82 FB''', 'v4_v5')
        status = rows[0]
        self.assertEqual(len(status['slot_observations']), 4)
        self.assertEqual([o['local_index'] for o in status['slot_observations']], list(range(4)))
        self.assertTrue(all(o['slot'] is None and not o['diagnostics_valid'] for o in status['slot_observations']))
        self.assertFalse(status['fail_slots'])
        self.assertFalse(status['bp_type_fault_slots'])
        self.assertIn('local index 3 = A1', app.render_backplane_registers(rows))
        self.assertFalse(any(c['severity'] == 'Critical' for c in app.backplane_register_checks(report(rows))))

    def test_failed_control_read_and_missing_start_have_local_unknowns(self):
        ctrl, status = capture('BF', (0xA1, 0x84))
        raw = '#cio -n bp1_sep0_ctrl -m block -t wr 32 0\ncio_block_write_read failure: CIO Call Failure\n'
        raw += '#cio -n bp1_sep0_status -m block -t wr 32 0\n'
        raw += '\n'.join(app.split_v4_register_dump(' '.join(f'{v:02X}' for v in status)))
        row = app.parse_sep_info(raw, 'v4_v5')[-1]
        self.assertEqual(len(row['unmapped_observations']), 2)
        self.assertFalse(row['fail_slots'] or row['bp_type_fault_slots'])

    def test_missing_first_sep_cannot_establish_whole_board_boundary(self):
        ctrl, status = capture('BF', (0x81, 0x81, 0x81, 0xA1), start=8)
        ctrl[23] = 10
        raw = '\n'.join(line for row in parse(ctrl, status) for line in [row['command'], *row['registers']])
        raw = raw.replace('sep0', 'sep1')
        raw += '\n#cio -n bp1_sep0_ctrl -m block -t wr 32 0\ncio_block_write_read failure: CIO Call Failure'
        rows = app.parse_sep_info(raw, 'v4_v5')
        row = rows[1]
        self.assertEqual(len(row['slot_observations']), 4)
        self.assertIsNone(row['range_validation']['capacity'])
        self.assertFalse(row['range_validation']['valid'])
        self.assertEqual(row['fail_slots'], '11')
        self.assertFalse(app.analyze_backplanes(report(rows))['devices'][0]['range_valid'])

    def test_outside_boundary_flags_never_get_a_physical_fault_bay(self):
        ctrl, status = capture('BF', (0xA1, 0x84))
        ctrl[23] = 1
        rows = parse(ctrl, status)
        self.assertEqual(rows[1]['fail_slots'], '0')
        self.assertFalse(rows[1]['bp_type_fault_slots'])
        self.assertIsNone(rows[1]['slot_observations'][1]['slot'])
        self.assertFalse(rows[1]['slot_observations'][1]['type_fault'])
        checks = app.backplane_register_checks(report(rows))
        self.assertTrue(any(c['severity'] == 'Critical' for c in checks))
        self.assertFalse(any('BP type fault indication' in c['title'] for c in checks))

    def test_unverified_old_application_does_not_become_healthy_or_use_modern_table(self):
        ctrl, status = capture('51', (0x80, 0xA0))
        ctrl[4:8] = bytes.fromhex('E2132100')
        ctrl[26] = 0x20
        rows = parse(ctrl, status, 'v1_v3')
        self.assertEqual(rows[1]['status_profile'], 'unknown')
        self.assertFalse(rows[1]['data_validation']['diagnostics_valid'])
        self.assertFalse(rows[1]['drive_presence'] or rows[1]['fail_slots'])
        self.assertIn('no verified status layout', json.dumps(rows[1]))

    def test_marker_five_refreshes_in_memory_without_touching_inventory_or_ai(self):
        r = report(app.parse_sep_info(REAL_TEN_BAY, 'v4_v5'))
        r.update(backplane_details_version=5, backplane_analysis={'schema': 2}, ai_analysis={'content': 'historical'})
        r['sep_info'][-1]['slot_observations'] = r['sep_info'][-1]['slot_observations'][:2]
        protected = copy.deepcopy((r['pci'], r['ai_analysis']))
        with patch.object(app, 'collect_update_evidence', return_value={}):
            updated = app.enrich_backplane_report(r)
        self.assertEqual(updated['backplane_details_version'], 6)
        self.assertEqual(len(updated['sep_info'][-1]['slot_observations']), 4)
        self.assertEqual((updated['pci'], updated['ai_analysis']), protected)

    def test_empty_old_report_recovers_its_own_structured_sep_evidence(self):
        ctrl, status = capture('BB', (0xC4, 0xC0))
        data = {'DriveBackplanes': [], 'DriveBays': [], 'Backplane1': {
            'Control': [' '.join(f'{v:02X}' for v in ctrl)],
            'Status': [' '.join(f'{v:02X}' for v in status)]}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); extract = root / 'spec-test' / 'extract'; extract.mkdir(parents=True)
            (extract / 'backplanes.json').write_text(json.dumps(data))
            r = report([])
            r.update(format='v1_v3', files={'backplanes': 'backplanes.json'},
                     backplane_details_version=5, backplane_analysis={'schema': 2}, ai_analysis={'content': 'historical'})
            before = copy.deepcopy((r['pci'], r['ai_analysis'], r['format'], r['files']))
            with patch.object(app, 'REPORT_DIR', root), patch.object(app, 'collect_update_evidence', return_value={}):
                updated = app.enrich_backplane_report(r)
            self.assertEqual(updated['sep_info'][1]['bp_type_fault_slots'], '0')
            self.assertTrue(any('BP type fault indication' in c['title'] for c in updated['automated_checks']))
            self.assertEqual((updated['pci'], updated['ai_analysis'], updated['format'], updated['files']), before)

    def test_recovery_cannot_read_another_reports_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'spec-test' / 'extract').mkdir(parents=True)
            outside = root / 'other.json'; outside.write_text('{}')
            r = report([]); r['files'] = {'backplanes': '../../other.json'}
            with patch.object(app, 'REPORT_DIR', root), patch.object(app, 'parse_v4_backplanes_json') as parser:
                app.enrich_backplane_report(r)
            parser.assert_not_called()


if __name__ == '__main__':
    unittest.main()
