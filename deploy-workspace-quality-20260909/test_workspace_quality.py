import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from workspace_analysis import WorkspaceEvidenceTools


class WorkspaceQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'network.log').write_text('NIC eth0 link down\nNIC eth0 link up 25Gbps\nNIC rx errors=0 tx errors=0\n')
        (self.root / 'storage.log').write_text('RAID controller failed to detect drive\nRetry succeeded\n')

    def test_network_question_prepares_recovery_context_without_storage_noise(self):
        tools = WorkspaceEvidenceTools(self.root)
        prepared = tools.prepare('网卡有什么错误？')
        self.assertIn('link up 25Gbps', json.dumps(prepared))
        self.assertNotIn('RAID controller', json.dumps(prepared))
        self.assertEqual(tools.sources[0], {'kind': 'log', 'path': 'network.log', 'start': 1, 'end': 3})

    def test_zero_counters_are_not_triage_failures(self):
        tools = WorkspaceEvidenceTools(self.root)
        rows = tools.triage_ffdc('network')['findings']['network']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['line'], 1)

    def test_large_log_does_not_starve_other_files(self):
        (self.root / '000.log').write_text('RAID reset\n' * 100000)
        tools = WorkspaceEvidenceTools(self.root)
        result = tools.triage_ffdc()
        self.assertTrue(result['limited'])
        self.assertIn('network', result['findings'])
        self.assertLessEqual(len(result['findings']['storage']), 4)

    def test_report_sections_can_page_beyond_initial_snapshot(self):
        tools = WorkspaceEvidenceTools(sections={'inventory': [{'slot': i} for i in range(90)]})
        page = tools.execute('read_report_section', {'section': 'inventory', 'offset': 60})
        self.assertEqual(page['data'][0]['slot'], 60)
        self.assertEqual(page['next_offset'], 80)
        self.assertIn('error', tools.execute('read_report_section', {'section': '../secret'}))

    def test_only_read_log_ranges_pass_citation_check(self):
        tools = WorkspaceEvidenceTools(self.root)
        tools.read_log('network.log', 1, 2)
        self.assertEqual(tools.unsupported_citations('`network.log:1-2`'), [])
        self.assertEqual(tools.unsupported_citations('`network.log:1-3` `invented.log:99`'), ['network.log:1-3', 'invented.log:99'])

    def test_explicit_new_bug_cannot_use_previous_report(self):
        report = {'id': 'old-report', 'jira': {'issue': 'IOSS-1000'}}
        with patch.object(app, 'load_workspace_report', return_value=report), patch.object(app, 'call_workspace_chat', return_value=('new answer', 'model', None, None)) as chat, patch.object(app, 'call_workspace_report_chat') as old:
            response = app.workspace_chat_response('分析 IOSS-2000', [{'role': 'assistant', 'content': 'old fact'}], 'old-report')
        self.assertEqual(response['answer'], 'new answer')
        self.assertEqual(chat.call_args.args[1], [])
        old.assert_not_called()

    def test_workspace_original_question_and_real_excerpts_reach_model(self):
        payloads = []
        def complete(url, key, payload):
            payloads.append(payload)
            return {'choices': [{'message': {'content': '链路曾中断，随后恢复 `network.log:1-2`。'}, 'finish_reason': 'stop'}]}
        trace = {}
        with patch.object(app, 'load_ai_config', return_value=('https://davy.example', 'test', 'model')), patch.object(app, 'post_json', side_effect=complete):
            answer, model = app.call_evidence_chat({'system': {}}, '网卡有什么问题？', root=self.root, auto_triage=True, workspace=True, trace=trace)
        self.assertIn('link up 25Gbps', payloads[0]['messages'][1]['content'])
        self.assertEqual(payloads[0]['messages'][-1]['content'], '网卡有什么问题？')
        self.assertIn('focused follow-ups', payloads[0]['messages'][0]['content'])
        self.assertEqual(trace['citation_check'], 'checked')
        self.assertTrue(trace['sources'])

    def test_report_id_validation_prevents_path_traversal(self):
        for rid in ('../secret', '/tmp/secret', '', 'r/../../etc'):
            with self.assertRaises(ValueError):
                app.load_workspace_report(rid)

    def test_milestone_query_not_forced_through_ffdc_job(self):
        self.assertFalse(app.workspace_question_requests_ffdc_analysis('IOSS-1000 对应项目的里程碑是什么'))
        self.assertTrue(app.workspace_question_requests_ffdc_analysis('分析 IOSS-1000'))


if __name__ == '__main__':
    unittest.main()
