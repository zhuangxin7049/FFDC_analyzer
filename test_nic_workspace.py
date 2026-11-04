import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from domain_packs import DomainPackRegistry
from workspace_analysis import INSTRUCTIONS, WorkspaceEvidenceTools, focus_for


class NicWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_inventory_without_errors_is_opened_with_real_source_lines(self):
        self.write('tmp/io_devices.txt',
                   'EID 12 TID 9 Addr 0x00EA0000\n'
                   'Name: Broadcom Ethernet Adapter\n'
                   'Port 1 MAC 00:11:22:33:44:55 LinkDown 0 Gbps\n')
        tools = WorkspaceEvidenceTools(self.root)
        prepared = tools.prepare('查看网卡和端口信息')
        self.assertEqual(prepared['excerpts'][0]['path'], 'tmp/io_devices.txt')
        self.assertIn('0x00EA0000', json.dumps(prepared['excerpts']))
        self.assertEqual(tools.unsupported_citations('`tmp/io_devices.txt:1-3`'), [])
        self.assertFalse(prepared['domain_pack_evidence']['findings'])
        self.assertIn('unknown', ' '.join(prepared['nic_evidence']['limitations']))

    def test_discovered_update_sources_precede_generic_errors_and_keep_budget(self):
        self.write('network.log', 'NIC eth0 failed\n' * 20)
        self.write('tmp/ffdc_live_dbg/dmdb_pci_dumper.txt', 'Ethernet EID 16\nFirmware 1.2.3\n')
        for name in ('flash_history.log', 'mctp_trace.log', 'fm.log', 'pldm.log', 'bmu_fwrpm.log'):
            self.write('tmp/' + name, 'EID 16 firmware update completed\n')
        tools = WorkspaceEvidenceTools(self.root)
        prepared = tools.prepare('NIC firmware 有什么信息？')
        self.assertEqual(prepared['excerpts'][0]['category'], 'NIC inventory')
        self.assertEqual(prepared['excerpts'][1]['category'], 'NIC update evidence')
        self.assertLessEqual(len(prepared['excerpts']), 8)
        read_paths = {row['path'] for row in prepared['excerpts']}
        self.assertIn('tmp/flash_history.log', read_paths)
        self.assertIn('tmp/pldm.log', read_paths)
        self.assertEqual(prepared['nic_evidence']['files_available'], 6)

    def test_parsed_event_anchor_reopens_materialized_nested_source(self):
        source = '_nic_firmware/123/IBMU.log'
        origin = 'tmp/tracebuffer/IBMU.tgz!IBMU.tar!IBMU.log'
        self.write(source, 'normal service event\n' * 100 + 'NIC update succeeded for EID 16\n')
        sections = {'nic_firmware': {
            'events': [{'source': source, 'line': 101, 'status': 'success'}],
            'log_sources': [{'source': source, 'origin': origin}],
            'expected_sources': ['invented_missing.log'],
        }}
        tools = WorkspaceEvidenceTools(self.root, sections=sections)
        prepared = tools.prepare('网卡升级结果是什么？')
        excerpt = prepared['excerpts'][0]
        self.assertEqual(excerpt['origin'], origin)
        self.assertIn('NIC update succeeded', json.dumps(excerpt))
        self.assertEqual(tools.unsupported_citations('`' + source + ':101`'), [])
        self.assertNotIn('invented_missing.log', json.dumps(prepared))

    def test_shared_update_errors_are_not_nic_fault_findings(self):
        self.write('tmp/mctp_trace.log', 'MCTP firmware failed for storage controller\n')
        self.write('tmp/fm.log', 'PCIe hardware error on RAID controller\n')
        self.write('tmp/io_devices.txt', 'Ethernet Port 1 CurrentState LinkDown CurrentSpeed 0 Gbps\n')
        tools = WorkspaceEvidenceTools(self.root)
        prepared = tools.prepare('NIC 固件升级失败了吗？')
        self.assertFalse(prepared['domain_pack_evidence']['findings'])
        self.assertTrue(any(row['category'] == 'NIC update evidence' for row in prepared['excerpts']))

    def test_nic_prompt_keeps_scope_and_jira_is_not_requested(self):
        self.write('tmp/io_devices.txt', 'Ethernet EID 12\nPort 1 LinkDown 0 Gbps\n')
        import app
        payloads = []

        def complete(url, key, payload):
            payloads.append(payload)
            return {'choices': [{'message': {'content': '当前日志显示端口未建立链路。'}, 'finish_reason': 'stop'}]}

        with patch.object(app, 'load_ai_config', return_value=('https://example.invalid', 'test', 'model')), \
                patch.object(app, 'post_json', side_effect=complete), \
                patch.object(app, 'wait_for_ai_request_start'):
            app.call_evidence_chat({'network': {'adapters': []}}, '查看网卡信息',
                                   root=self.root, auto_triage=True, workspace=True)
        prompt = payloads[0]['messages'][0]['content']
        context = payloads[0]['messages'][1]['content']
        self.assertIn('LinkDown with 0 Gbps', prompt)
        self.assertIn('BMU launch/status outcome is not a NIC firmware update outcome', prompt)
        self.assertIn('never fabricate a PCI BDF', prompt)
        self.assertIn('tmp/io_devices.txt', context)
        self.assertIn('Port 1 LinkDown 0 Gbps', context)
        self.assertNotIn('requires_jira_login', context)

    def test_aliases_select_network_but_storage_vendor_alone_does_not(self):
        for question in ('Mellanox', 'ConnectX-7', 'BCM57508', 'E810 固件', 'QLogic 网口'):
            self.assertIn('network', focus_for(question))
        self.assertNotIn('network', focus_for('Broadcom RAID 940-8e'))
        registry = DomainPackRegistry()
        self.assertEqual(registry._selected('Broadcom RAID 940-8e', []), [])
        self.assertFalse(registry.errors)


if __name__ == '__main__':
    unittest.main()
