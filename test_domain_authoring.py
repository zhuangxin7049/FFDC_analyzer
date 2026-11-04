import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
from domain_authoring import DomainAuthoring, authoring_mention, extract_document, validate_draft
from domain_packs import DomainPackRegistry


def candidate():
    return {'name': 'nic', 'display_name': 'NIC', 'version': '0.1.0',
            'question_keywords': ['NIC'], 'file_patterns': ['nic.log'], 'required_sources': ['NIC events'],
            'extractors': [], 'rules': [{'id': 'nic.link_down', 'severity': 'Info', 'category': 'Network',
            'title': 'Link down observation', 'message': 'Verify recovery and port configuration.',
            'patterns': ['eth0 link down'], 'exclude_patterns': []}]}


class DomainAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.author = DomainAuthoring(self.root / 'domain_drafts')
        self.model = Mock(return_value=(json.dumps({'pack': candidate(), 'questions': [], 'limitations': []}), 'mock-model'))

    def start(self, domain='NIC', actor=None):
        return self.author.respond('@' + domain + ' Agent', self.model, actor=actor)['authoring']

    def test_bare_mention_requires_neither_model_nor_ffdc(self):
        response = self.author.respond('@NIC Agent', self.model)
        self.model.assert_not_called()
        self.assertIn('No FFDC is required', response['answer'])
        self.assertEqual(response['analysis']['mode'], 'domain_authoring')
        self.assertFalse(self.author.directory.exists())

    def test_each_domain_has_an_isolated_authoring_entry(self):
        expected = {
            'UEFI': 'UEFI / BIOS',
            'PSU': 'Power Supply / PSU',
            'FPGA': 'FPGA',
            'BMC': 'BMC',
            'XCC': 'BMC',
            'Storage': 'Storage / RAID',
            'Memory': 'Memory / DIMM',
        }
        for agent, display_name in expected.items():
            with self.subTest(agent=agent):
                response = self.author.respond('@' + agent + ' Agent', self.model)
                self.assertEqual(response['authoring']['display_name'], display_name)
                self.assertIn(display_name + ' Rule Authoring', response['answer'])
                self.assertIn('No FFDC is required', response['answer'])
        self.model.assert_not_called()

    def test_document_context_is_sent_to_davy_and_answer_is_english(self):
        source = extract_document('nic-guide.txt', b'NIC_TEST_LINK_DOWN means link state is down.')
        self.model.return_value = (json.dumps({'pack': None, 'questions': ['Which relative log path should contain this event?'], 'limitations': [], 'references': []}), 'mock-model')
        result = self.author.respond('@NIC Agent', self.model, document=source)
        request = self.model.call_args.args[0]['messages'][1]['content']
        self.assertIn('NIC_TEST_LINK_DOWN', request)
        self.assertIn('reference_documents', request)
        self.assertIn('More information needed', result['answer'])
        self.assertNotIn('规则编写', result['answer'])

    def test_followup_language_follows_chinese_request(self):
        token = self.start(actor='alice')['token']
        self.model.return_value = (json.dumps({'pack': None, 'questions': ['请提供日志路径'], 'limitations': ['当前只支持行级规则'], 'references': []}), 'mock-model')
        result = self.author.respond('请用中文继续说明规则', self.model, token, actor='alice')
        self.assertIn('需要更多信息', result['answer'])
        self.assertIn('请提供日志路径', result['answer'])
        self.assertIn('**限制**', result['answer'])
        prompt = self.model.call_args.args[0]['messages'][0]['content']
        self.assertIn('Use Chinese', prompt)
        self.assertNotIn('More information needed', result['answer'])

    def test_docx_text_extraction(self):
        import io
        import zipfile
        xml = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>NIC field definition</w:t></w:r></w:p></w:body></w:document>'
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('word/document.xml', xml)
        extracted = extract_document('guide.docx', stream.getvalue())
        self.assertIn('NIC field definition', '\n'.join(section['text'] for section in extracted['sections']))

    def test_dispatch_before_report_and_jira_checks(self):
        with patch.object(app, 'DOMAIN_AUTHORING', self.author), patch.object(app, 'load_workspace_report') as load, patch.object(app, 'call_workspace_chat') as chat:
            response = app.workspace_chat_response('@NIC Agent', report_id='expired', history=[{'role': 'user', 'content': 'IOSS-8361'}])
        self.assertEqual(response['authoring']['domain'], 'nic')
        load.assert_not_called()
        chat.assert_not_called()

    def test_clarification_then_revision_keeps_server_history(self):
        token = self.start()['token']
        self.model.return_value = (json.dumps({'pack': None, 'questions': ['Which path?'], 'limitations': []}), 'mock')
        result = self.author.respond('Teach a link rule', self.model, token)
        self.assertEqual(result['authoring']['status'], 'collecting')
        self.model.return_value = (json.dumps({'pack': candidate(), 'questions': [], 'limitations': []}), 'mock')
        self.author.respond('Use nic.log', self.model, token)
        self.assertIn('Teach a link rule', self.model.call_args.args[0]['messages'][1]['content'])
        result = self.author.respond('Keep it informational', self.model, token)
        self.assertEqual(result['authoring']['revision'], 2)
        self.assertEqual(len(list(self.author.directory.glob('*.json'))), 2)

    def test_clarification_is_limited_to_two_blocking_questions(self):
        self.model.return_value = (json.dumps({'pack': None, 'questions': [
            'Which log path?', 'Which exact sample line?', 'What else?', 'Any other context?'
        ], 'limitations': []}), 'mock')
        result = self.author.respond('@NIC Agent Please help define a rule', self.model)
        self.assertIn('1. Which log path?', result['answer'])
        self.assertIn('2. Which exact sample line?', result['answer'])
        self.assertNotIn('What else?', result['answer'])
        prompt = self.model.call_args.args[0]['messages'][0]['content']
        self.assertIn('Prefer a grounded draft', prompt)
        self.assertIn('at most 2 short clarification questions', prompt)

    def test_draft_saved_outside_runtime_and_token_not_persisted(self):
        token = self.start(actor='alice')['token']
        result = self.author.respond('nic.log 中 eth0 link down 只作为 Info 观察', self.model, token, actor='alice')
        files = list(self.author.directory.glob('*.json'))
        self.assertEqual(len(files), 1)
        record = json.loads(files[0].read_text())
        self.assertFalse(record['tested'])
        self.assertFalse(record['published'])
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertNotIn(token, files[0].read_text())
        self.assertNotIn(token, json.dumps(self.model.call_args.args[0]))
        self.assertEqual(DomainPackRegistry(self.root / 'domain_packs').catalog(), [])
        self.assertFalse(result['authoring']['published'])
        self.assertEqual(record['created_by'], 'alice')
        self.assertEqual(record['updated_by'], 'alice')
        self.assertEqual(record['audit'][0]['actor'], 'alice')

    def test_rule_session_cannot_be_reused_by_another_user(self):
        token = self.start(actor='alice')['token']
        self.author.respond('Draft this for NIC', self.model, token, actor='alice')
        with self.assertRaisesRegex(ValueError, 'another signed-in user'):
            self.author.respond('Change the rule', self.model, token, actor='bob')

    def test_invalid_json_never_saved(self):
        token = self.start()['token']
        self.model.return_value = ('Published to production!', 'mock')
        with self.assertRaises(ValueError):
            self.author.respond('Draft a rule', self.model, token)
        self.assertFalse(self.author.directory.exists())

    def test_missing_token_does_not_recover_another_session(self):
        self.start()
        with self.assertRaises(ValueError):
            self.author.respond('Follow up', self.model, 'invalid')
        self.model.assert_not_called()

    def test_sessions_are_isolated(self):
        first, second = self.start()['token'], self.start()['token']
        self.author.respond('Private first definition', self.model, first)
        self.author.respond('Second definition', self.model, second)
        self.assertNotIn('Private first definition', self.model.call_args.args[0]['messages'][1]['content'])

    def test_malformed_and_executable_candidates_rejected(self):
        for field, value in [('name', 'psu'), ('rules', 'bad'), ('extractors', [None]),
                             ('file_patterns', ['/etc/passwd']), ('file_patterns', ['../secret']), ('script', 'print(1)')]:
            with self.subTest(field=field, value=value):
                pack = candidate(); pack[field] = value
                with self.assertRaises(ValueError):
                    validate_draft(pack, 'nic')

    def test_invalid_group_rejected(self):
        pack = candidate()
        pack['extractors'] = [{'field': 'link', 'pattern': 'up', 'value_group': 3}]
        with self.assertRaises(ValueError):
            validate_draft(pack, 'nic')

    def test_secrets_redacted_before_model(self):
        token = self.start()['token']
        self.author.respond('password=example-value\nCheck eth0', self.model, token)
        self.assertNotIn('example-value', json.dumps(self.model.call_args.args[0]))

    def test_prompt_fixes_domain_identity_without_renaming_invalid_output(self):
        token = self.start()['token']
        self.author.respond('Rule description', self.model, token)
        prompt = self.model.call_args.args[0]['messages'][0]['content']
        self.assertIn('Required pack.name: "nic"', prompt)
        self.assertIn('Use English', prompt)
        pack = candidate()
        pack['name'] = 'nic-custom'
        self.model.return_value = (json.dumps({'pack': pack, 'questions': [], 'limitations': []}), 'mock')
        with self.assertRaisesRegex(ValueError, 'format validation'):
            self.author.respond('修订规则', self.model, token)
        self.assertEqual(len(list(self.author.directory.glob('*.json'))), 1)

    def test_expiration_and_busy(self):
        token = self.start()['token']
        self.author.sessions[token]['lock'].acquire()
        with self.assertRaisesRegex(ValueError, 'progress'):
            self.author.respond('hello', self.model, token)
        self.author.sessions[token]['lock'].release()
        self.author.sessions[token]['touched'] = 0
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.author.respond('hello', self.model, token)

    def test_alias_and_non_mentions(self):
        self.assertEqual(authoring_mention('@XCC Agent hello'), ('bmc', 'hello'))
        self.assertEqual(authoring_mention('@Memory Agent check ECC'), ('memory', 'check ECC'))
        self.assertIsNone(authoring_mention('Explain @NIC Agent'))

    def test_memory_draft_stays_in_memory_domain(self):
        memory = candidate()
        memory.update(name='memory', display_name='Memory / DIMM', question_keywords=['ECC'],
                      file_patterns=['memory.log'], required_sources=['DIMM inventory'])
        memory['rules'][0].update(id='memory.ecc_error', category='Memory')
        validate_draft(memory, 'memory')
        with self.assertRaisesRegex(ValueError, 'selected Agent'):
            validate_draft(memory, 'nic')

    def test_endpoint_requires_json_and_same_origin(self):
        handler = Mock(path='/workspace-domain-author')
        handler.headers = {'Host': 'localhost', 'Origin': 'https://other.example', 'Content-Type': 'application/json'}
        app.Handler.do_POST(handler)
        handler.send_json.assert_called_once_with({'error': 'Same-origin JSON request required.'}, 403)

    def test_endpoint_requires_sign_in_before_authoring(self):
        handler = Mock(path='/workspace-domain-author')
        handler.headers = {'Host': 'localhost', 'Content-Type': 'application/json'}
        handler.headers['Content-Length'] = '24'
        handler.rfile.read.return_value = b'{"message":"@NIC Agent"}'
        with patch.object(app, 'DOMAIN_AUTHORING', self.author):
            app.Handler.do_POST(handler)
        handler.send_json.assert_called_once_with({
            'error': 'Please sign in before creating or editing a rule draft.',
            'requires_authoring_login': True,
        }, 401)
        handler.get_cookie.assert_called_once_with(app.AUTHOR_SESSION_COOKIE)

    def test_endpoint_records_signed_in_author(self):
        handler = Mock(path='/workspace-domain-author')
        handler.headers = {'Host': 'localhost', 'Content-Type': 'application/json'}
        handler.headers['Content-Length'] = '24'
        handler.rfile.read.return_value = b'{"message":"@NIC Agent"}'
        handler.get_cookie.return_value = 'session'
        with patch.object(app, 'DOMAIN_AUTHORING', self.author), patch.object(app, 'get_author_session', return_value={'username': 'alice'}):
            app.Handler.do_POST(handler)
        response = handler.send_json.call_args.args[0]
        self.assertEqual(response['authoring']['domain'], 'nic')
        self.assertEqual(response['authoring']['created_by'], 'alice')

    def test_author_login_creates_identity_only_session(self):
        handler = Mock(path='/workspace-author-login')
        handler.read_json_body.return_value = {'username': 'alice', 'password': 'temporary-password'}
        handler.get_cookie.return_value = ''
        with patch.object(app, 'jira_request_json', return_value={'name': 'alice'}), \
                patch.object(app, 'create_author_session', return_value='author-session') as create:
            app.Handler.do_POST(handler)
        create.assert_called_once_with('alice')
        handler.set_author_session_cookie.assert_called_once_with('author-session')

    def test_author_session_never_stores_password(self):
        app.AUTHOR_SESSIONS.clear()
        self.addCleanup(app.AUTHOR_SESSIONS.clear)
        sid = app.create_author_session('alice')
        self.assertEqual(app.AUTHOR_SESSIONS[sid]['username'], 'alice')
        self.assertNotIn('password', app.AUTHOR_SESSIONS[sid])

    def test_multipart_document_request_extracts_source_without_jira(self):
        boundary = '----ffdc-test'
        body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="message"\r\n\r\n@NIC Agent\r\n'
                '--' + boundary + '\r\nContent-Disposition: form-data; name="domain"\r\n\r\nnic\r\n'
                '--' + boundary + '\r\nContent-Disposition: form-data; name="document"; filename="guide.txt"\r\nContent-Type: text/plain\r\n\r\nNIC_TEST_LINK_DOWN means link is down.\r\n'
                '--' + boundary + '--\r\n').encode()
        handler = Mock()
        handler.headers = {'Host': 'localhost', 'Content-Type': f'multipart/form-data; boundary={boundary}', 'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        payload, document = app.read_domain_author_request(handler)
        self.assertEqual(payload['domain'], 'nic')
        self.assertEqual(document['name'], 'guide.txt')
        self.assertIn('NIC_TEST_LINK_DOWN', document['sections'][0]['text'])


if __name__ == '__main__':
    unittest.main()
