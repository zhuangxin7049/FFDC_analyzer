import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import app


OVERFLOW = ('AI API error 400: This model\'s maximum context length is 262144 tokens. '
            'However, you requested 2200 output tokens and your prompt contains at least '
            '259945 input tokens, for a total of at least 262145 tokens.')


class AiPromptBudgetTests(unittest.TestCase):
    def evidence(self):
        return {'source_file': 'large-report.tzz', 'events': [
            {'severity': 'Critical' if i == 75 else 'Info', 'source': 'logs/controller.log',
             'line': i + 1, 'evidence': ('背板 firmware register 0x81 ' * 1500)}
            for i in range(100)]}

    def test_small_evidence_is_unchanged(self):
        value = {'slot': 1, 'eid': '0xa', 'events': []}
        self.assertEqual(app.bounded_ai_evidence_json(value), json.dumps(value, ensure_ascii=False))

    def test_large_unicode_evidence_is_valid_bounded_and_keeps_critical_citation(self):
        value = self.evidence()
        before = copy.deepcopy(value)
        encoded = app.bounded_ai_evidence_json(value)
        self.assertLessEqual(len(encoded.encode()), 160000)
        sampled = json.loads(encoded)
        self.assertTrue(sampled['_evidence_budget']['truncated'])
        critical = next(row for row in sampled['events'] if row.get('severity') == 'Critical')
        self.assertEqual((critical['source'], critical['line']), ('logs/controller.log', 76))
        self.assertIn('omitted', encoded)
        self.assertEqual(value, before)

    def test_agent_prompt_keeps_instructions_and_agent_coverage(self):
        tasks = [{'agent': 'Agent ' + str(i), 'evidence': self.evidence()} for i in range(8)]
        prompt = app.build_agent_analysis_prompt({'source_file': 'large.tzz'}, tasks)
        prefix, encoded = prompt.split('Agent context JSON:\n')
        self.assertIn('Do not override a local tool status', prefix)
        self.assertIn('## JIRA Comment Draft', prefix)
        self.assertLessEqual(len(encoded.encode()), 160000)
        context = json.loads(encoded)
        self.assertEqual([t['agent'] for t in context['agent_tasks']], ['Agent '+str(i) for i in range(8)])

    def test_jira_relevance_prompt_is_also_bounded(self):
        value = {'summary': 'Firmware update failure', 'attachment_evidence': self.evidence()}
        prompt = app.build_jira_monitor_evidence_prompt(value)
        encoded = prompt.split('Complete JIRA and FFDC evidence JSON:\n')[1]
        self.assertLessEqual(len(encoded.encode()), 160000)
        self.assertEqual(json.loads(encoded)['summary'], value['summary'])

    def test_exact_overflow_retries_smaller_evidence_and_keeps_output_and_model(self):
        prompt = app.build_agent_analysis_prompt({}, [{'agent': 'Network', 'evidence': self.evidence()}])
        with patch.object(app, '_call_ai_prompt_once', side_effect=[RuntimeError(OVERFLOW), ('analysis', 'configured-model')]) as call:
            result = app.call_ai_prompt(prompt, max_tokens=2200, retries=1, model_override='configured-model')
        self.assertEqual(result, ('analysis', 'configured-model'))
        first, second = call.call_args_list
        self.assertLess(len(second.args[0].encode()), len(first.args[0].encode()))
        self.assertEqual(first.args[0].split('Agent context JSON:\n')[0], second.args[0].split('Agent context JSON:\n')[0])
        self.assertEqual(second.kwargs, first.kwargs)
        json.loads(second.args[0].split('Agent context JSON:\n')[1])

    def test_context_retries_are_bounded_and_other_400_is_not_retried(self):
        prompt = app.build_agent_analysis_prompt({}, [{'evidence': self.evidence()}])
        with patch.object(app, '_call_ai_prompt_once', side_effect=RuntimeError(OVERFLOW)) as call:
            with self.assertRaisesRegex(RuntimeError, 'maximum context length'):
                app.call_ai_prompt(prompt)
            self.assertEqual(call.call_count, 3)
        with patch.object(app, '_call_ai_prompt_once', side_effect=RuntimeError('AI API error 400: invalid model')) as call:
            with self.assertRaisesRegex(RuntimeError, 'invalid model'):
                app.call_ai_prompt(prompt)
            self.assertEqual(call.call_count, 1)

    def test_unstructured_prompt_is_not_silently_cut(self):
        with patch.object(app, '_call_ai_prompt_once', side_effect=RuntimeError(OVERFLOW)) as call:
            with self.assertRaises(RuntimeError):
                app.call_ai_prompt('Full unstructured user instructions ' * 10000)
            self.assertEqual(call.call_count, 1)

    def test_responses_context_error_does_not_repeat_same_payload_via_chat(self):
        error = urllib.error.HTTPError('https://ai.example.test/responses', 400, 'Bad request', {}, io.BytesIO(OVERFLOW.encode()))
        with patch.object(app, 'load_ai_config', return_value=('https://ai.example.test', 'unused-key', 'model')), patch.object(app, 'post_json', side_effect=error) as post:
            with self.assertRaisesRegex(RuntimeError, 'maximum context length'):
                app._call_ai_prompt_once('prompt')
            self.assertEqual(post.call_count, 1)

    def test_deep_investigation_recovers_instead_of_saving_error(self):
        tasks = [{'agent': 'Network Agent', 'goal': 'Review evidence', 'evidence': self.evidence()}]
        with tempfile.TemporaryDirectory() as tmp:
            keyfile = Path(tmp) / 'key'; keyfile.touch()
            with patch.object(app, 'API_KEY_FILE', keyfile), patch.object(app, 'collect_agent_tasks', return_value=tasks), patch.object(app, 'collect_agent_tool_results', return_value=[]), patch.object(app, 'build_report_jira_relevance_item', return_value=None), patch.object(app, '_call_ai_prompt_once', side_effect=[RuntimeError(OVERFLOW), ('## Agent Findings\n1. Review the cited evidence.', 'model')]):
                result = app.generate_agent_analysis({'id': 'large-report'})
        self.assertEqual(result['status'], 'ok')
        self.assertIn('cited evidence', result['content'])


if __name__ == '__main__':
    unittest.main()
