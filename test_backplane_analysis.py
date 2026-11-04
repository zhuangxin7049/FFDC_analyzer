"""Spec-grounded configuration, topology and update correlation contracts."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import backplane_analysis as bp
from test_backplane_spec import capture, parse, report


def fixture(app_id='BF', values=None, extra=None, **kwargs):
    ctrl, status = capture(app_id, values or ((0x81, 0x83) if app_id == 'BF' else (0xC0, 0xC3)), **kwargs)
    ctrl.extend([0] * (0x4B - len(ctrl)))
    for offset, value in (extra or {}).items():
        ctrl[offset] = value
    rows = parse(ctrl, status)
    result = report(rows)
    result['files'] = {'backplanes': 'backplanes.json', 'io_devices': 'tmp/io_devices.txt'}
    result['backplane_scope'] = {'applicable': True, 'external_adapters': []}
    return result


def with_storage(r, serial='BOARD01', explicit='', controller='RAID 540-16i', bay='0'):
    r['sep_vpd'] = [{'bp': '1', 'name': 'Boone', 'raw': 'JSON node BP 1, PN PN01, SN BOARD01'}]
    adapter = {'name': controller, 'serial': serial, 'slot': '8', 'eid': '0xb'}
    r['pci'] = {'adapters': [adapter], 'storage': [{'adapter': adapter, 'controller': controller,
                 'drives': [{'bay': bay, 'serial': 'DRIVE01', 'backplane': explicit}]}]}
    return r


class BackplaneAnalysisTests(unittest.TestCase):
    def analyze(self, r):
        return bp.analyze_backplanes(r)

    def test_current_baseline_is_v106_and_reaches_ai_instructions(self):
        self.assertEqual(bp.BACKPLANE_SPEC['revision'], 'v1.06')
        self.assertIn('v1.06', app.WORKSPACE_ANALYSIS_INSTRUCTIONS)
        self.assertEqual(self.analyze(fixture())['spec']['document'], 'SP-000008')

    def test_nvme_only_x1_and_x2_are_configuration_not_negotiated_width(self):
        for value, width in [(0x80, 'x1'), (0x9F, 'x2')]:
            result = self.analyze(fixture(extra={0x4A: value}))
            links = result['devices'][0]['links']
            self.assertTrue(links['snapshot_valid'])
            self.assertTrue(all(row['width'] == width for row in links['configured_widths']))
            self.assertEqual(links['negotiated_width'], 'not collected')

    def test_nvme_only_invalid_valid_bit_does_not_claim_width(self):
        links = self.analyze(fixture(extra={0x4A: 0x1F}))['devices'][0]['links']
        self.assertFalse(links['configured_widths'])
        self.assertIn('valid bit is clear', ' '.join(links['limitations']))

    def test_cable_type_disagreement_is_configuration_warning(self):
        result = self.analyze(fixture(extra={0x4A: 0x90}))
        self.assertTrue(any('cable-type' in c['title'] for c in result['checks']))
        self.assertTrue(all(c['severity'] != 'Critical' for c in result['checks']))

    def test_anybay_x2_u3_conflict(self):
        result = self.analyze(fixture('BB', extra={0x49: 0x8F, 0x1B: 0x01}))
        self.assertTrue(any('U.3 x1 configuration conflict' in c['title'] for c in result['checks']))
        self.assertTrue(all(r['width'] == 'x2' for r in result['devices'][0]['links']['configured_widths']))

    def test_anybay_table53_conflict_is_not_resolved_by_guessing(self):
        result = self.analyze(fixture('BB', extra={0x49: 0x30}))
        links = result['devices'][0]['links']
        self.assertFalse(links['configured_widths'])
        self.assertTrue(links['reported_width_bits'])
        self.assertIn('disagree', ' '.join(links['limitations']))
        self.assertFalse(any('defective' in c['title'] for c in result['checks']))

    def test_edsff_marker_applies_only_to_supported_applications(self):
        for app_id, values in [('BC', (0xC2,)), ('C1', (0xC0,))]:
            result = self.analyze(fixture(app_id, values=values, extra={0x48: 0xBB}))
            self.assertTrue(any('EDSFF configuration is invalid' == c['title'] for c in result['checks']))
        result = self.analyze(fixture(extra={0x48: 0xBB}))
        self.assertFalse(any('EDSFF configuration' in c['title'] for c in result['checks']))

    def test_disabled_ubm_ports_are_explicit_overrides_not_cable_faults(self):
        result = self.analyze(fixture('BB', extra={0x45: 0x11}))
        links = result['devices'][0]['links']
        self.assertEqual(links['ubm_disabled_ports'], ['I2C_HP0', 'converged TM0'])
        self.assertEqual(links['configured_management'], ['SGPIO', 'I2C_HP', 'UBM'])
        self.assertTrue(links['observed_management'])
        self.assertTrue(all(c['severity'] == 'Info' for c in result['checks']))

    def test_missing_registers_are_distinct_from_explicit_zero(self):
        r = fixture('BB')
        for row in r['sep_info']:
            if row['register_type'] == 'ctrl':
                row['register_bytes'].pop(str(0x45), None)
        absent = self.analyze(r)['devices'][0]['links']
        zero = self.analyze(fixture('BB'))['devices'][0]['links']
        self.assertFalse(absent.get('ubm_disable_collected'))
        self.assertTrue(zero['ubm_disable_collected'])
        self.assertFalse(zero['ubm_disabled_ports'])

    def test_invalid_snapshot_does_not_raise_register_configuration_findings(self):
        r = fixture('BB', extra={0x49: 0x8F, 0x1B: 15}, communication=0x80)
        result = self.analyze(r)
        self.assertFalse(result['devices'][0]['links']['snapshot_valid'])
        self.assertFalse(any('U.3' in c['title'] for c in result['checks']))

    def test_unique_serial_and_reported_range_confirm_mapping(self):
        result = self.analyze(with_storage(fixture()))
        row = result['topology'][0]
        self.assertEqual((row['backplane'], row['sep'], row['mapping']), ('bp1', 'sep0', 'confirmed'))
        self.assertIn('serial', row['evidence'])

    def test_bay_number_alone_remains_candidate(self):
        result = self.analyze(with_storage(fixture(), serial=''))
        self.assertEqual(result['topology'][0]['mapping'], 'candidate')
        self.assertTrue(result['limitations'])

    def test_explicit_identity_conflict_cannot_confirm_mapping(self):
        result = self.analyze(with_storage(fixture(), explicit='bp2'))
        self.assertEqual(result['topology'][0]['mapping'], 'unresolved')
        self.assertIn('conflicts', result['topology'][0]['evidence'])

    def test_placeholder_or_duplicate_controller_serial_is_not_unique_identity(self):
        r = with_storage(fixture(), serial='000000')
        self.assertEqual(self.analyze(r)['topology'][0]['mapping'], 'candidate')
        r = with_storage(fixture())
        r['pci']['storage'].append(copy.deepcopy(r['pci']['storage'][0]))
        self.assertTrue(all(row['mapping'] == 'candidate' for row in self.analyze(r)['topology']))

    def test_overlapping_sep_ranges_are_not_confirmed(self):
        r = with_storage(fixture(), explicit='bp1')
        second = fixture(start=1, extra={0x19: 1})
        for row in second['sep_info']:
            row['sep'] = 'sep1'
        r['sep_info'] += second['sep_info']
        result = self.analyze(r)
        self.assertTrue(any('mapping is inconsistent' in c['title'] for c in result['checks']))
        self.assertEqual(result['topology'][0]['mapping'], 'unresolved')

    def test_virtual_backplane_hfc_wrap_is_not_a_duplicate_port(self):
        r = fixture(extra={0x16: 0, 0x19: 0, 0x17: 4})
        second = fixture(start=2, extra={0x16: 1, 0x19: 0, 0x17: 4})
        for row in second['sep_info']:
            row['sep'] = 'sep1'
        r['sep_info'] += second['sep_info']
        self.assertFalse(any('mapping is inconsistent' in c['title'] for c in self.analyze(r)['checks']))

    def test_boot_and_data_bay_namespaces_do_not_borrow_each_other(self):
        r = with_storage(fixture(), controller='M.2 RAID B545i')
        self.assertEqual(self.analyze(r)['topology'][0]['mapping'], 'unresolved')
        r = with_storage(fixture('BA', values=(0x40, 0x40), extra={0x1A: 6}), controller='M.2 RAID B545i')
        r['sep_vpd'][0]['name'] = 'MoSalah'
        self.assertEqual(self.analyze(r)['topology'][0]['mapping'], 'confirmed')

    def test_external_controller_is_excluded_even_in_mixed_report(self):
        r = with_storage(fixture(), controller='ThinkSystem 460-16e HBA')
        self.assertFalse(self.analyze(r)['topology'])
        r['backplane_scope'] = {'applicable': False, 'reason': 'external path'}
        self.assertFalse(self.analyze(r)['devices'])
        self.assertFalse(self.analyze(r)['checks'])

    def test_development_firmware_marker_blocks_automatic_update_without_failure(self):
        result = self.analyze(fixture(extra={0x1C: 0x5A}))
        self.assertEqual(result['devices'][0]['firmware']['development_flag'], '0x5A')
        c = next(c for c in result['checks'] if 'development firmware' in c['title'])
        self.assertEqual(c['severity'], 'Info')
        self.assertIn('v1.06', c['conclusion'])

    def test_debug_request_response_does_not_fabricate_payload(self):
        result = self.analyze(fixture(extra={0x3C: 6, 0x3D: 6, 0x3E: 10, 0x3F: 0}))
        debug = result['devices'][0]['firmware']['debug_log']
        self.assertEqual(debug['length'], 10)
        self.assertFalse(debug['payload_decoded'])
        self.assertIn('separately', debug['state'])

    def test_identity_mismatch_is_verification_warning(self):
        r = fixture()
        ctrl = r['sep_info'][0]
        ctrl['register_bytes'][str(4)] = 'AA'
        r['sep_vpd'] = [{'bp': '1', 'name': 'Ballistic', 'raw': ''}]
        checks = self.analyze(r)['checks']
        self.assertTrue(any('silicon' in c['title'] for c in checks))
        self.assertTrue(any('VPD' in c['title'] for c in checks))
        self.assertTrue(all(c['severity'] == 'Warning' for c in checks))

    def test_log_reported_results_require_exact_device_and_terminal_statement(self):
        devices = self.analyze(fixture())['devices']
        lines = ['2026-10-15 10:00:00 BP1 SEP0 firmware update from 16 to 17 succeeded',
                 'BP1 SEP0 firmware update failed', 'BP1 SEP0 BMU script completed successfully',
                 'BP1 SEP0 NIC firmware update succeeded', 'BP2 SEP0 firmware update succeeded',
                 'BP1 SEP0 and BP2 SEP0 firmware update succeeded', 'BP1 SEP0 firmware update not succeeded']
        events = bp.correlate_updates([{'source': 'tmp/fm.log', 'line': i+1, 'evidence': line} for i, line in enumerate(lines)], devices)
        self.assertEqual(events[0]['result'], 'success reported')
        self.assertEqual(events[0]['reported_versions'], {'from': '16', 'to': '17'})
        self.assertEqual(events[1]['result'], 'failure reported')
        self.assertTrue(all(e['result'] == 'observed' for e in events[2:]))
        self.assertEqual(events[4]['association'], 'unresolved')
        self.assertEqual(events[5]['association'], 'unresolved')

    def test_snapshot_alone_does_not_imply_an_upgrade(self):
        result = self.analyze(fixture())
        self.assertTrue(result['devices'][0]['firmware']['snapshot_version'])
        self.assertFalse(result['firmware_events'])

    def test_collector_is_bounded_and_preserves_line_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'tmp').mkdir()
            (root/'tmp/fm.log').write_text('unrelated\nBP1 SEP0 firmware update succeeded\npassword=secret BP1 SEP0 firmware update failed\n')
            found = bp.collect_update_evidence(root)
            self.assertEqual(len(found['events']), 1)
            self.assertEqual(found['events'][0]['line'], 2)
            self.assertEqual(found['events'][0]['source'], 'tmp/fm.log')
            self.assertNotIn('secret', json.dumps(found))
            (root/'tmp/fm.log').write_text('BP1 SEP0 firmware update succeeded\n' * 200)
            found = bp.collect_update_evidence(root)
            self.assertEqual(len(found['events']), 80)
            self.assertTrue(found['limitations'])

    def test_collector_rejects_outside_symlink_and_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); extract = root/'extract'; extract.mkdir(); (extract/'tmp').mkdir()
            outside = root/'private.log'; outside.write_text('BP1 SEP0 firmware update succeeded\n')
            (extract/'tmp/fm.log').symlink_to(outside)
            result = bp.collect_update_evidence(extract, {'flash_history': str(outside)})
            self.assertFalse(result['events'])
            self.assertFalse(result['sources'])

    def test_truncated_final_log_line_cannot_become_a_terminal_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'tmp').mkdir()
            line = 'BP1 SEP0 firmware update succeeded'
            prefix = 'x' * (512 * 1024 - len(line) - 1) + '\n'
            (root/'tmp/fm.log').write_text(prefix + line + '; script output only\n')
            result = bp.collect_update_evidence(root)
            self.assertFalse(result['events'])
            self.assertTrue(result['sources'][0]['truncated'])

    def test_unassigned_drive_does_not_acquire_a_controller_from_its_bay(self):
        r = fixture()
        r['pci']['other_drives'] = [{'bay': '0', 'serial': 'DIRECT01', 'backplane': 'bp1'}]
        row = self.analyze(r)['topology'][0]
        self.assertEqual(row['controller'], 'Controller not recorded')
        self.assertEqual(row['mapping'], 'backplane confirmed; controller unresolved')

    def test_underscore_log_device_identity_is_supported(self):
        devices = self.analyze(fixture())['devices']
        event = bp.correlate_updates([{'source': 'tmp/fm.log', 'line': 1, 'evidence': 'bp_1_sep_0 firmware update succeeded'}], devices)[0]
        self.assertEqual(event['result'], 'success reported')
        self.assertEqual(event['bp'], 'bp1')

    def test_zero_bay_is_kept_and_invalid_bay_cannot_match(self):
        self.assertEqual(self.analyze(with_storage(fixture(), bay=0))['topology'][0]['bay'], 0)
        self.assertEqual(self.analyze(with_storage(fixture(), bay='unknown'))['topology'][0]['mapping'], 'unresolved')

    def test_api_ai_summary_and_ui_share_schema_without_rewriting_history(self):
        r = with_storage(fixture(extra={0x4A: 0x9F, 0x1C: 0x5A}))
        r['backplane_details_version'] = 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = root/r['id']; folder.mkdir()
            path = folder/'report.json'; path.write_text(json.dumps(r)); before = path.read_bytes()
            with patch.object(app, 'REPORT_DIR', root), patch.object(app, 'collect_nic_firmware_evidence', side_effect=AssertionError('NIC recollected')):
                updated = app.enrich_nic_report(copy.deepcopy(r))
                self.assertEqual(updated['backplane_details_version'], 6)
                self.assertEqual(updated['backplane_analysis']['topology'][0]['mapping'], 'confirmed')
                self.assertIn('v1.06', app.build_system_summary_text(updated))
                updated['backplane_analysis']['firmware_events'] = [{'source': 'tmp/fm.log', 'line': 1, 'evidence': 'hidden-fw-evidence-sentinel'}]
                context = app.compact_report_for_ai(updated)
                self.assertEqual(context['backplane_analysis']['spec']['revision'], 'v1.06')
                self.assertIn('hidden-fw-evidence-sentinel', json.dumps(context['backplane_analysis']))
                page = app.render_report(updated)
                self.assertIn('Backplane Configuration and Mapping', page)
                self.assertIn('Controller to Bay Mapping', page)
                mapping = page.split('<h3>Controller to Bay Mapping</h3>')[1].split('</section>')[0]
                for column in ('controller_slot', 'eid', 'evidence'):
                    self.assertNotIn('<th>' + column + '</th>', mapping)
                for column in ('controller', 'bay', 'drive_serial', 'backplane', 'sep', 'mapping'):
                    self.assertIn('<th>' + column + '</th>', mapping)
                for text in ('Backplane Firmware Update Evidence', 'snapshot version', 'BMC update policy', 'SEP debug response', 'hidden-fw-evidence-sentinel', 'V3 / V4 source coverage'):
                    self.assertNotIn(text, page)
                self.assertEqual(path.read_bytes(), before)

    def test_legacy_ui_keeps_vpd_identity_without_inventing_modern_link_values(self):
        analysis = {'devices': [{'bp': 'bp1', 'sep': 'sep0', 'name': 'NEW28\t1 x 8 - 2.5 SATA/SAS',
                                'application': '', 'start_slot': 0, 'slot_count': 8,
                                'links': {'configured_widths': [], 'observed_management': [], 'ubm_disabled_ports': [],
                                          'limitations': ['Link configuration cannot be validated from this snapshot']}}],
                    'topology': [{'controller': 'RAID', 'controller_slot': '3', 'eid': '0xb', 'bay': 0,
                                  'drive_serial': 'DRIVE01', 'backplane': 'bp1', 'sep': 'sep0',
                                  'mapping': 'candidate', 'evidence': 'retained raw identity evidence'}]}
        before = copy.deepcopy(analysis)
        page = app.render_backplane_analysis(analysis)
        self.assertIn('NEW28 1 x 8 - 2.5 SATA/SAS', page)
        self.assertIn('0-7', page)
        self.assertNotIn('not identified', page)
        for column in ('configured width', 'observed protocol', 'UBM disabled', 'controller_slot', 'eid', 'evidence'):
            self.assertNotIn('<th>' + column + '</th>', page)
        self.assertIn('No verified PCIe width', page)
        self.assertNotIn('retained raw identity evidence', page)
        self.assertEqual(analysis, before)

    def test_modern_ui_keeps_collected_zero_ubm_and_invalid_configuration_values(self):
        for value in (0x80, 0):
            with self.subTest(value=value):
                analysis = self.analyze(with_storage(fixture('BB', extra={0x49: value, 0x45: 0})))
                page = app.render_backplane_analysis(analysis)
                self.assertIn('Boone / SEP 4MV4', page)
                self.assertIn('<th>configured width</th>', page)
                self.assertIn('<th>observed protocol</th>', page)
                self.assertIn('<th>UBM disabled</th>', page)
                self.assertIn('<td>none</td>', page)
                self.assertIn('x4' if value else 'not verified', page)

    def test_collection_sources_are_namespaced_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root/'collection'/'workspace_extract'/'attachment-1'/'tmp'; target.mkdir(parents=True)
            (target/'fm.log').write_text('line\n')
            original = {'backplane_analysis': {'firmware_events': [{'source': 'tmp/fm.log', 'line': 1}]}}
            context = copy.deepcopy(original)
            with patch.object(app, 'REPORT_DIR', root):
                app.qualify_nic_collection_sources(context, {'root_report_id': 'collection', 'attachments': [{'id': 'report1', 'namespace': 'attachment-1'}]}, 'report1')
            self.assertEqual(context['backplane_analysis']['firmware_events'][0]['source'], 'attachment-1/tmp/fm.log')
            self.assertEqual(original['backplane_analysis']['firmware_events'][0]['source'], 'tmp/fm.log')


if __name__ == '__main__':
    unittest.main()
