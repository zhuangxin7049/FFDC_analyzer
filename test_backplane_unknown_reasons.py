"""User-visible causes for Unknown SEP statuses, including retained-data gaps."""
import copy
import unittest

import app
from test_backplane_spec import capture, parse
from test_backplane_corpus_regression import REAL_TEN_BAY


class BackplaneUnknownReasonTests(unittest.TestCase):
    def test_missing_control_explains_identity_and_local_indices(self):
        rows = app.parse_sep_info('''#cio -n bp3_sep0_status -m block -t wr 32 0
rData[00]: 03 04 F9 C1 81 81 81 A1 04 01 16 81 81 81 82 FB''', 'v4_v5')
        page = app.render_backplane_registers(rows, 'v4_minilog')
        self.assertIn('Unknown reasons', page)
        self.assertIn('Control registers were not collected', page)
        self.assertIn('local index 0-3 (physical bay unknown)', page)
        self.assertIn('raw: 81, A1', page)
        self.assertNotIn('<b>Drive Fail</b>', page)
        self.assertNotIn('Snapshot validation:', page)

    def test_power_and_communication_reasons_show_raw_context(self):
        for kwargs, cause, raw in [
            ({'communication': 0x90}, 'PGOOD is low', 'communication 0x90'),
            ({'communication': 0x40, 'enabled': 0xB0}, 'Communication byte is unavailable or not valid', 'communication 0x40'),
        ]:
            with self.subTest(kwargs=kwargs):
                rows = parse(*capture('BF', (0x81,), **kwargs))
                page = app.render_backplane_registers(rows)
                self.assertIn('Unknown reasons', page)
                self.assertIn(cause, page)
                self.assertIn(raw, page)

    def test_unsupported_legacy_identity_names_apid_and_silicon(self):
        ctrl, status = capture('51', (0x80, 0xA0))
        ctrl[4:8] = [0xE2, 0x13, 0x21, 0]
        ctrl[26] = 0
        rows = parse(ctrl, status, 'v1_v3')
        page = app.render_backplane_registers(rows)
        self.assertIn('APID 0x51', page)
        self.assertIn('Silicon ID E2 13 21 00', page)
        self.assertIn('SEP identity has no verified status layout', page)
        self.assertIn('Protocol Support', page)
        self.assertIn('control[0x1A] = 00', page)

    def test_reserved_bit_conflict_is_attached_to_affected_slots(self):
        rows = parse(*capture('BF', (0xC1, 0xC1), start=4))
        explanation = app.backplane_unknown_reasons(*rows)
        entries = [r for r in explanation['entries'] if any('Reserved bit 6' in s for s in r['reasons'])]
        self.assertEqual(len(entries), 1)
        self.assertIn('slot 4-5', entries[0]['target'])
        self.assertEqual(entries[0]['raw'], 'C1')
        self.assertIn('Table 62', app.render_backplane_registers(rows))

    def test_only_edsff_slot_with_missing_extended_validity_is_explained(self):
        rows = parse(*capture('BE', (0xC0,) * 6, extended=[0x81] * 5 + [0]))
        explanation = app.backplane_unknown_reasons(*rows)
        self.assertEqual(len(explanation['entries']), 1)
        self.assertEqual(explanation['entries'][0]['target'], 'slot 5')
        self.assertIn('extended 00', explanation['entries'][0]['raw'])
        self.assertIn('Extended drive status valid bit', app.render_backplane_registers(rows))

    def test_unrecognized_code_names_value_and_selected_identity(self):
        rows = parse(*capture('BF', (0x80,)))
        page = app.render_backplane_registers(rows)
        self.assertIn('APID 0xBF', page)
        self.assertIn('raw: 80', page)
        self.assertIn('Drive status code is not recognized for this SEP profile', page)

    def test_unmapped_bytes_are_explained_separately_from_physical_slot(self):
        rows = app.parse_sep_info(REAL_TEN_BAY, 'v4_v5')
        explanation = app.backplane_unknown_reasons(rows[-2], rows[-1])
        self.assertEqual(len(explanation['entries']), 2)
        self.assertIn('slot 8', explanation['entries'][0]['target'])
        self.assertEqual(explanation['entries'][1]['target'], 'local index 2-3 (physical bay unknown)')
        self.assertTrue(any('boundary' in r for r in explanation['entries'][1]['reasons']))
        page = app.render_backplane_registers(rows)
        self.assertNotIn('slot 10', page)
        self.assertNotIn('slot 11', page)

    def test_no_ten_line_limit_hides_later_unknown_causes(self):
        status = {'bp': 'bp1', 'sep': 'sep0', 'register_type': 'status', 'unknown_slots': ', '.join(map(str, range(12))),
                  'slot_status': 'slot 0: Unknown', 'slot_observations': [
                      {'slot': i, 'local_index': i, 'raw': f'{i:02X}', 'diagnostics_valid': False,
                       'limitations': [f'Capture-specific cause {i}']} for i in range(12)]}
        page = app.render_backplane_registers([status])
        for i in range(12):
            self.assertIn(f'Capture-specific cause {i}', page)

    def test_historical_unknown_without_retained_reason_is_explicit(self):
        status = {'bp': 'bp1', 'sep': 'sep0', 'register_type': 'status', 'slot_status': 'slot 0: Unknown 80'}
        page = app.render_backplane_registers([status])
        self.assertIn('retains no per-slot reason', page)
        self.assertIn('original register evidence is required', page)

    def test_metadata_unknown_has_a_reason_even_without_status(self):
        ctrl = {'bp': 'bp1', 'sep': 'sep0', 'register_type': 'ctrl', 'application': 'Unknown (D5)',
                'application_id': 'D5', 'bp_capability': 'Unknown (AA)', 'bp_capability_code': 'AA'}
        page = app.render_backplane_registers([ctrl], 'v4_minilog')
        self.assertIn('Unknown reasons', page)
        self.assertIn('control[0x10] = D5', page)
        self.assertIn('control[0x1A] = AA', page)

    def test_untrusted_reason_is_escaped(self):
        rows = parse(*capture('BF', (0x80,)))
        rows[1]['slot_observations'][0]['limitations'].append('<script>alert(1)</script>')
        page = app.render_backplane_registers(rows)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        self.assertNotIn('<script>', page)

    def test_known_normal_empty_and_fault_statuses_have_no_unknown_explanation(self):
        for values in [(0x81, 0x83), (0xA1, 0x84)]:
            with self.subTest(values=values):
                rows = parse(*capture('BF', values))
                before = copy.deepcopy(rows)
                self.assertFalse(app.backplane_unknown_reasons(*rows)['entries'])
                self.assertNotIn('Unknown reasons', app.render_backplane_registers(rows))
                self.assertEqual(rows, before)


if __name__ == '__main__':
    unittest.main()
