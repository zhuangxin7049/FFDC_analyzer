import unittest
from unittest.mock import patch

import app
from workspace_ui import render_workspace_page


class WorkspacePageTests(unittest.TestCase):
    def test_conversation_workspace_replaces_marketing_hero(self):
        page = render_workspace_page()
        self.assertIn("FFDC Analysis Assistant", page)
        self.assertIn("/static/workspace.js", page)
        self.assertIn("Current analysis", page)
        self.assertNotIn("Analyze ThinkSystem FFDC packages", page)
        self.assertNotIn("linear-gradient", page)
        self.assertIn("/Current_bug_status_summary", page)
        self.assertIn("Open analysis report", page)
        self.assertEqual(page.count('id="attach-button"'), 1)
        self.assertEqual(page.count('href="/reports"'), 1)
        self.assertNotIn('name="username"', page)
        self.assertNotIn('name="password"', page)

    def test_error_message_is_escaped(self):
        page = render_workspace_page('<script>alert("x")</script>')
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("&lt;script&gt;", page)

    def test_old_homepage_stays_default_and_links_to_new_version(self):
        old_page = app.index_page()
        self.assertIn("Analyze ThinkSystem FFDC packages", old_page)
        self.assertNotIn("workspace-shell", old_page)
        served_page = app.add_new_version_nav(old_page)
        self.assertIn("href='/new-version'>New version</a><a href='/reports'>Reports", served_page)

    def test_workspace_chat_preloads_live_issue(self):
        issue = {"key": "IOSS-8345", "status": "Investigate", "engineer": "Engineer A"}
        report = {
            "id": "report-1",
            "source_file": "sample.tzz",
            "jira": {"issue": "IOSS-8345", "attachment": "sample.tzz"},
        }
        jira_tool = unittest.mock.Mock()
        jira_tool.get_jira_issue.return_value = {"issue": issue}
        with patch.object(app, "EvidenceTools", return_value=jira_tool), patch.object(
            app, "find_latest_workspace_jira_report", return_value=report
        ), patch.object(
            app, "call_workspace_report_chat", return_value=("answer", "model")
        ) as chat:
            answer, model, result, report = app.call_workspace_chat("查看 ioss-8345")
        self.assertEqual((answer, model, result), ("answer", "model", issue))
        self.assertEqual(report["id"], "report-1")
        self.assertEqual(jira_tool.get_jira_issue.call_args.args[0], "IOSS-8345")
        chat.assert_called_once()
        self.assertEqual(chat.call_args.kwargs["live_issue"], issue)

    def test_general_workspace_chat_does_not_require_issue(self):
        with patch.object(app, "call_evidence_chat", return_value=("answer", "model")) as chat:
            answer, model, issue, report = app.call_workspace_chat("Explain PCIe link width")
        self.assertEqual((answer, model, issue, report), ("answer", "model", None, None))
        self.assertNotIn("requested_jira_issue", chat.call_args.args[0])

    def test_bug_analysis_intent_requires_ffdc_context(self):
        self.assertTrue(app.workspace_question_requests_ffdc_analysis("分析一下 IOSS-8345"))
        self.assertTrue(app.workspace_question_requests_ffdc_analysis("Show FFDC evidence for IOSS-8345"))
        self.assertTrue(app.workspace_question_requests_ffdc_analysis("查看 IOSS-8345 当前状态"))
        self.assertFalse(app.workspace_question_requests_ffdc_analysis("Explain PCIe link width"))

    def test_bug_analysis_reuses_latest_ffdc_report(self):
        issue = {"key": "IOSS-8345", "status": "Investigate", "engineer": "Engineer A"}
        report = {
            "id": "report-1",
            "source_file": "sample.tzz",
            "jira": {"issue": "IOSS-8345", "attachment": "sample.tzz"},
        }
        jira_tool = unittest.mock.Mock()
        jira_tool.get_jira_issue.return_value = {"issue": issue}
        with patch.object(app, "EvidenceTools", return_value=jira_tool), patch.object(
            app, "find_latest_workspace_jira_report", return_value=report
        ), patch.object(
            app, "call_workspace_report_chat", return_value=("FFDC answer", "model")
        ) as report_chat:
            answer, model, result, summary = app.call_workspace_chat("分析一下 IOSS-8345")
        self.assertEqual((answer, model, result), ("FFDC answer", "model", issue))
        self.assertEqual(summary["id"], "report-1")
        self.assertEqual(summary["file"], "sample.tzz")
        report_chat.assert_called_once()

    def test_bug_analysis_without_report_requests_background_ffdc_job(self):
        jira_tool = unittest.mock.Mock()
        jira_tool.get_jira_issue.return_value = {"issue": {"key": "IOSS-8345"}}
        with patch.object(app, "EvidenceTools", return_value=jira_tool), patch.object(
            app, "find_latest_workspace_jira_report", return_value=None
        ):
            result = app.call_workspace_chat("分析一下 IOSS-8345")
        self.assertEqual(result, (None, "", {"key": "IOSS-8345"}, None))

    def test_chat_markdown_renders_level_three_heading(self):
        rendered = app.render_chat_markdown(
            "### 基本信息\n- **状态**: Investigate",
            app.render_ai_markdown,
        )
        self.assertIn("<h3>基本信息</h3>", rendered)
        self.assertNotIn("###", rendered)

    def test_workspace_chat_reflows_wide_markdown_tables_into_findings(self):
        answer = (
            "---\n## FFDC Evidence\n"
            "| # | Risk | Category | Concrete Evidence |\n"
            "| --- | --- | --- | --- |\n"
            "| 1 | Drive slot mapping conflict | Storage | Slot 00 appears on both HBAs. |"
        )
        rendered = app.render_workspace_chat_markdown(answer)
        self.assertNotIn("<table>", rendered)
        self.assertNotIn("---", rendered)
        self.assertIn("<h3>1. Drive slot mapping conflict</h3>", rendered)
        self.assertIn("<strong>Category:</strong> Storage", rendered)
        self.assertIn("<strong>Concrete Evidence:</strong> Slot 00 appears on both HBAs.", rendered)

    def test_workspace_upload_suggestions_cover_available_evidence(self):
        questions = app.workspace_report_suggested_questions({
            "network": {"adapters": []},
            "pci": {"slots": []},
            "bmc_inband_fw": {"events": []},
        })
        self.assertEqual(questions[0], "Summarize the most important risks in this FFDC.")
        self.assertIn("Analyze network adapters, link state, driver, and firmware evidence.", questions)
        self.assertIn("Check PCIe adapters, link width, and controller evidence.", questions)
        self.assertIn("Analyze BMC in-band firmware update and PLDM evidence.", questions)
        self.assertLessEqual(len(questions), 5)

    def test_workspace_recent_list_has_local_clear_control(self):
        page = app.render_workspace_page()
        self.assertIn('id="clear-recent"', page)

    def test_project_milestone_search_uses_latest_snapshot(self):
        job = {"id": "current-test", "status": "done", "updated": 1000}
        rows = [{
            "project_name": "Project Storm AV2 (Wave-3)",
            "project_id": "9849",
            "milestone": "SS",
            "date": "2026-09-20",
            "countdown": 13,
            "ss_date": "2026-09-20",
            "ss_countdown": 13,
            "issues": [{
                "key": "IOSS-8345",
                "summary": "Drive not detected",
                "assignee": "Engineer A",
                "display_tags": "IOSSM",
            }],
        }]
        with patch.object(app, "get_latest_current_status_summary_job", return_value=job), patch.object(
            app, "current_status_summary_project_rows", return_value=rows
        ):
            result = app.search_workspace_project_milestones(query="IOSS-8345", within_days=20)
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["projects"][0]["project_id"], "9849")
        self.assertEqual(result["projects"][0]["defects"][0]["engineer"], "Engineer A")

    def test_server_pat_ffdc_lookup_does_not_require_user_credentials(self):
        issue = {"key": "IOSS-8345", "fields": {"attachment": [{
            "filename": "sample.tzz", "content": "https://jira.test/file/1"
        }]}}
        with patch.object(app, "jira_similar_pat_request_json", return_value=issue), patch.object(
            app, "build_jira_issue_ai_context", return_value={"key": "IOSS-8345"}
        ):
            key, sources, context = app.jira_find_ffdc_sources_with_server_pat("ioss-8345")
        self.assertEqual(key, "IOSS-8345")
        self.assertEqual(sources[0]["filename"], "sample.tzz")
        self.assertEqual(context["key"], "IOSS-8345")

    def test_server_pat_bug_without_ffdc_keeps_jira_context(self):
        issue = {"key": "IOSS-9000", "fields": {"attachment": []}}
        with patch.object(app, "jira_similar_pat_request_json", return_value=issue), patch.object(
            app, "build_jira_issue_ai_context", return_value={"key": "IOSS-9000"}
        ):
            key, sources, context = app.jira_find_ffdc_sources_with_server_pat("IOSS-9000")
        self.assertEqual(key, "IOSS-9000")
        self.assertEqual(sources, [])
        self.assertFalse(context["ffdc_available"])

    def test_report_chat_includes_latest_jira_issue_without_mutating_report(self):
        report = {"id": "report-1", "jira": {"issue": "IOSS-8345"}}
        live_issue = {"key": "IOSS-8345", "summary": "Latest title", "comments": [{"body": "Latest comment"}]}
        with patch.object(app, "call_openai_chat", return_value=("answer", "model")) as chat:
            result = app.call_workspace_report_chat(
                report, "分析 IOSS-8345", live_issue=live_issue
            )
        self.assertEqual(result, ("answer", "model"))
        self.assertEqual(chat.call_args.args[0]["jira"]["live_issue"], live_issue)
        self.assertNotIn("live_issue", report["jira"])
        self.assertEqual(chat.call_args.args[1], "分析 IOSS-8345")
        self.assertTrue(chat.call_args.kwargs["workspace"])
        self.assertEqual(chat.call_args.kwargs["language"], "Chinese")

    def test_server_pat_is_not_sent_to_external_ffdc_links(self):
        with patch.object(app, "jira_similar_pat_headers", side_effect=lambda: {
            "Authorization": "Bearer secret", "Accept": "application/json"
        }):
            jira_headers = app.jira_server_pat_attachment_headers(
                app.JIRA_BASE_URL + "/secure/attachment/1/sample.tzz"
            )
            external_headers = app.jira_server_pat_attachment_headers(
                "https://ffdc-data.example.test/download/sample.tzz"
            )
        self.assertEqual(jira_headers["Authorization"], "Bearer secret")
        self.assertNotIn("Authorization", external_headers)

    def test_comment_form_requests_user_login_only_for_write(self):
        page = app.render_jira_comment_section({"id": "r1", "jira": {"issue": "IOSS-8345"}})
        self.assertIn("Add comment to JIRA", page)
        self.assertIn("name='username'", page)
        self.assertIn("name='password'", page)
        self.assertIn("required only for this write action", page)


if __name__ == "__main__":
    unittest.main()
