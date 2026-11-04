import unittest
import io
import urllib.error
from unittest.mock import Mock, patch
import app


class WorkspaceJiraAuthTests(unittest.TestCase):
    def login_handler(self):
        handler = Mock()
        handler.path = '/workspace-jira-login'
        handler.read_json_body.return_value = {
            'username': 'alice', 'password': 'test-password', 'issue': 'IOSS-99999',
        }
        handler.get_cookie.return_value = ''
        handler.wfile = io.BytesIO()
        return handler

    def test_login_validates_account_not_requested_issue(self):
        handler = self.login_handler()
        with patch.object(app, 'jira_request_json', return_value={'name': 'alice'}) as jira, patch.object(app, 'create_jira_session', return_value='test-session'):
            app.Handler.do_POST(handler)
        jira.assert_called_once_with(app.JIRA_BASE_URL + '/rest/api/2/myself', 'alice', 'test-password')
        handler.send_response.assert_called_once_with(200)
        handler.set_jira_session_cookie.assert_called_once_with('test-session')

    def test_failed_authentication_does_not_create_session(self):
        handler = self.login_handler()
        with patch.object(app, 'jira_request_json', side_effect=ValueError('Jira login failed.')), patch.object(app, 'create_jira_session') as create:
            app.Handler.do_POST(handler)
        create.assert_not_called()
        handler.set_jira_session_cookie.assert_not_called()
        handler.send_json.assert_called_once_with({'error': 'Jira login failed.'}, 401)

    def test_not_found_errors_distinguish_issue_from_api(self):
        for path, message in [
            ('/rest/api/2/issue/IOSS-99999', 'not found, or this account'),
            ('/rest/api/2/myself', 'REST API returned HTTP 404'),
        ]:
            with self.subTest(path=path):
                url = app.JIRA_BASE_URL + path
                error = urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
                with patch.object(app.urllib.request, 'urlopen', side_effect=error), patch.object(app, 'JIRA_REQUEST_NEXT_AT', 0), patch.object(app, 'JIRA_REQUEST_MIN_INTERVAL_SECONDS', 0):
                    with self.assertRaisesRegex(ValueError, message):
                        app.jira_request_json(url, 'alice', 'test-password')

    def test_dynamic_jira_tool_requests_login(self):
        evidence = app.EvidenceTools(jira_request=app.workspace_jira_request(None), jira_base=app.JIRA_BASE_URL)
        with self.assertRaises(app.JiraLoginRequired):
            evidence.execute('get_jira_issue', {'key': 'IOSS-8361'})

    def test_login_required_before_jira_chat(self):
        with patch.object(app, 'call_workspace_chat') as chat:
            result = app.workspace_chat_response('Analyze IOSS-8361')
        self.assertTrue(result['analysis']['requires_jira_login'])
        chat.assert_not_called()

    def test_linked_report_followup_requires_login(self):
        with patch.object(app, 'load_workspace_report', return_value={'jira': {'issue': 'IOSS-8361'}}), patch.object(app, 'call_workspace_report_chat') as chat:
            result = app.workspace_chat_response('What did you find?', report_id='report-1')
        self.assertTrue(result['analysis']['requires_jira_login'])
        chat.assert_not_called()

    def test_local_ffdc_followup_ignores_historical_jira_login(self):
        report = {'id': 'report-1', 'source_file': 'sample.tzz', 'jira': {}}
        history = [{'role': 'user', 'content': 'Analyze IOSS-8361'}]
        with patch.object(app, 'load_workspace_report', return_value=report), patch.object(
            app, 'call_workspace_report_chat', return_value=('answer', 'model')
        ) as chat:
            result = app.workspace_chat_response(
                '分析这个FFDC附件', history=history, report_id='report-1'
            )
        self.assertEqual(result['answer'], 'answer')
        self.assertNotIn('requires_jira_login', result['analysis'])
        chat.assert_called_once()

    def test_credentials_scoped_to_jira_api(self):
        request = app.workspace_jira_request(('alice', 'test-password'))
        with patch.object(app, 'jira_request_json', return_value={}) as jira:
            request(app.JIRA_BASE_URL + '/rest/api/2/myself')
            jira.assert_called_once_with(app.JIRA_BASE_URL + '/rest/api/2/myself', 'alice', 'test-password')
            with self.assertRaises(ValueError):
                request('https://example.org/rest/api/2/myself')

    def test_no_shared_credentials_fallback(self):
        with patch.object(app, 'jira_similar_pat_request_json') as shared:
            with self.assertRaises(ValueError):
                app.call_workspace_chat('IOSS-8361')
            shared.assert_not_called()

    def test_denied_access_does_not_reuse_cached_report(self):
        with patch.object(app, 'jira_request_json', side_effect=ValueError('Access denied')), patch.object(app, 'find_latest_workspace_jira_report') as cached:
            with self.assertRaises(ValueError):
                app.call_workspace_chat('IOSS-8361', jira_credentials=('alice', 'test-password'))
        cached.assert_not_called()

    def test_attachment_job_uses_user_credentials(self):
        with patch.object(app, 'call_workspace_chat', return_value=(None, '', None, None)), patch.object(app, 'start_jira_job', return_value='job') as start:
            result = app.workspace_chat_response('IOSS-8361', jira_credentials=('alice', 'test-password'))
        start.assert_called_once_with('IOSS-8361', 'alice', 'test-password')
        self.assertEqual(result['ffdc_job_id'], 'job')


if __name__ == '__main__':
    unittest.main()
