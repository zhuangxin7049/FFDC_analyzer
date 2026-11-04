import json
import tempfile
import unittest
import urllib.error
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

    def test_fpga_question_reads_original_lines_without_parsed_fpga_report(self):
        (self.root / 'fpga.log').write_text('FPGA power fault set\nFPGA power rail recovered\n')
        tools = WorkspaceEvidenceTools(self.root)
        prepared = tools.prepare('FPGA 有什么发现？')
        self.assertEqual(prepared['indexed_search']['terms'], ['FPGA'])
        self.assertIn('FPGA power rail recovered', json.dumps(prepared))
        self.assertIn({'kind': 'log', 'path': 'fpga.log', 'start': 1, 'end': 2}, tools.sources)

    def test_broad_discovery_surfaces_unclassified_fpga_lead(self):
        (self.root / 'fpga.log').write_text('FPGA rail fault asserted\nFPGA rail recovered\n')
        tools = WorkspaceEvidenceTools(self.root)
        prepared = tools.prepare('有什么发现？')
        self.assertIn('fpga.log', json.dumps(prepared['log_catalog']))
        self.assertIn('FPGA rail fault asserted', json.dumps(prepared['excerpts']))
        self.assertIn('unclassified', json.dumps(prepared['excerpts']))

    def test_prior_sources_are_reopened_from_disk_and_invalid_paths_ignored(self):
        tools = WorkspaceEvidenceTools(self.root)
        sources = [
            {'kind': 'log', 'path': '../secret', 'start': 1, 'end': 2},
            {'kind': 'log', 'path': 'network.log', 'start': 1, 'end': 2, 'text': 'invented'},
        ]
        reopened = tools.reopen_sources(sources)
        self.assertEqual(len(reopened), 1)
        self.assertIn('NIC eth0 link down', json.dumps(reopened))
        self.assertNotIn('invented', json.dumps(reopened))
        self.assertEqual(tools.metadata()['reopened_sources'], 1)

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
            response = app.workspace_chat_response('分析 IOSS-2000', [{'role': 'assistant', 'content': 'old fact'}], 'old-report',
                                                   [{'kind': 'log', 'path': 'old.log', 'start': 1, 'end': 2}], jira_credentials=('user', 'test-password'))
        self.assertEqual(response['answer'], 'new answer')
        self.assertEqual(chat.call_args.args[1], [])
        old.assert_not_called()

    def test_report_chat_reopens_previous_evidence_for_model(self):
        payloads = []
        def complete(url, key, payload):
            payloads.append(payload)
            return {'choices': [{'message': {'content': '已核对上轮日志。'}, 'finish_reason': 'stop'}]}
        trace = {}
        with patch.object(app, 'load_ai_config', return_value=('https://davy.example', 'test', 'model')), patch.object(app, 'post_json', side_effect=complete):
            app.call_evidence_chat({'system': {}}, '继续检查网络', root=self.root, auto_triage=True, workspace=True,
                                   trace=trace, previous_sources=[{'kind': 'log', 'path': 'network.log', 'start': 1, 'end': 2}])
        self.assertIn('previous_verified_evidence', payloads[0]['messages'][1]['content'])
        self.assertIn('NIC eth0 link down', payloads[0]['messages'][1]['content'])
        self.assertEqual(trace['reopened_sources'], 1)

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

    def test_bug_analysis_question_requests_verification_round(self):
        payloads = []
        def complete(url, key, payload):
            payloads.append(payload)
            return {'choices': [{'message': {'content': '需要结合日志确认。'}, 'finish_reason': 'stop'}]}
        with patch.object(app, 'load_ai_config', return_value=('https://davy.example', 'test', 'model')), patch.object(app, 'post_json', side_effect=complete):
            app.call_evidence_chat({'system': {}}, '分析 IOSS-8361', root=self.root, auto_triage=True, workspace=True)
        self.assertEqual(len(payloads), 2)
        self.assertIn('Before finalizing', payloads[1]['messages'][-1]['content'])

    def test_workspace_retries_transient_ai_gateway_error(self):
        gateway_error = urllib.error.HTTPError('https://davy.example', 502, 'Bad Gateway', {}, None)
        response = {'choices': [{'message': {'content': 'Recovered answer.'}, 'finish_reason': 'stop'}]}
        with patch.object(app, 'load_ai_config', return_value=('https://davy.example', 'test', 'model')), \
                patch.object(app, 'post_json', side_effect=[gateway_error, gateway_error, response]) as post, \
                patch.object(app.time, 'sleep') as sleep, \
                patch.object(app, 'wait_for_ai_request_start'):
            answer, _ = app.call_evidence_chat({}, 'Hello', workspace=True)
        self.assertEqual(answer, 'Recovered answer.')
        self.assertEqual(post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 3])

    def test_workspace_reports_persistent_ai_gateway_error(self):
        gateway_error = urllib.error.HTTPError('https://davy.example', 502, 'Bad Gateway', {}, None)
        with patch.object(app, 'load_ai_config', return_value=('https://davy.example', 'test', 'model')), \
                patch.object(app, 'post_json', side_effect=[gateway_error] * 3) as post, \
                patch.object(app.time, 'sleep'), \
                patch.object(app, 'wait_for_ai_request_start'):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 502'):
                app.call_evidence_chat({}, 'Hello', workspace=True)
        self.assertEqual(post.call_count, 3)

    def test_workspace_chat_queue_rejects_only_after_admission_capacity(self):
        class FakeSemaphore:
            def __init__(self):
                self.acquired = False

            def acquire(self, timeout=None):
                if self.acquired:
                    return False
                self.acquired = True
                return True

            def release(self):
                self.acquired = False

        fake = FakeSemaphore()
        with patch.object(app, 'MAX_CONCURRENT_AI_REQUESTS', 1), \
                patch.object(app, 'MAX_QUEUED_AI_REQUESTS', 0), \
                patch.object(app, 'AI_REQUESTS_ADMITTED', 0), \
                patch.object(app, 'WORKSPACE_CHAT_LIMIT', fake):
            self.assertTrue(app.acquire_workspace_chat_slot())
            self.assertFalse(app.acquire_workspace_chat_slot())
            app.release_workspace_chat_slot()
            self.assertTrue(app.acquire_workspace_chat_slot())
            app.release_workspace_chat_slot()

    def test_report_id_validation_prevents_path_traversal(self):
        for rid in ('../secret', '/tmp/secret', '', 'r/../../etc'):
            with self.assertRaises(ValueError):
                app.load_workspace_report(rid)

    def test_milestone_query_not_forced_through_ffdc_job(self):
        self.assertFalse(app.workspace_question_requests_ffdc_analysis('IOSS-1000 对应项目的里程碑是什么'))
        self.assertTrue(app.workspace_question_requests_ffdc_analysis('分析 IOSS-1000'))

    def test_bug_id_is_detected_when_adjacent_to_chinese_text(self):
        self.assertEqual(app.workspace_issue_key('查看IOSS-8361'), 'IOSS-8361')
        self.assertEqual(app.workspace_issue_key('IOSS-8361有什么发现'), 'IOSS-8361')


if __name__ == '__main__':
    unittest.main()
