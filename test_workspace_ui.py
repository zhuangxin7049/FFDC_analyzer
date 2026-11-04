import json
import html
import io
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from workspace_ui import render_workspace_page, render_workspace_subpage, workspace_page_identity


class WorkspacePageTests(unittest.TestCase):
    def test_workspace_exposes_language_version_and_maintenance_tools(self):
        page = render_workspace_page()
        self.assertIn('data-language="zh"', page)
        self.assertIn('data-language="en"', page)
        self.assertIn('href="/maintenance?view=workspace"', page)
        self.assertIn('data-maintenance-unread', page)
        self.assertIn('href="/about?view=workspace"', page)
        self.assertIn('/static/workspace-language.js', page)
        self.assertIn('data-workspace-nav="about"', page)

    def test_utility_pages_keep_the_existing_workspace_shell(self):
        about = render_workspace_subpage(app.render_workspace_utility_page('about'), '/about?view=workspace')
        maintenance = render_workspace_subpage(app.render_workspace_utility_page('maintenance'), '/maintenance?view=workspace')
        self.assertIn('Product version and release notes', about)
        self.assertNotIn('Public version endpoint', about)
        self.assertNotIn('/api/version', about)
        self.assertIn('2026-10-30', about)
        self.assertIn('Register a maintenance item', maintenance)
        self.assertIn('method="post" action="/maintenance?view=workspace"', maintenance)
        self.assertIn('class="workspace-subpage-body"', maintenance)
        self.assertIn('data-maintenance-unread', maintenance)

    def test_maintenance_unread_badge_uses_local_read_marker(self):
        script = Path("static/workspace-language.js").read_text(encoding="utf-8")
        self.assertIn("ffdcMaintenanceLastSeen", script)
        self.assertIn("/api/maintenance", script)
        self.assertIn("location.pathname === '/maintenance'", script)

    def test_maintenance_record_is_bounded_and_persisted_atomically(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'MAINTENANCE_FILE', Path(folder) / 'records.json'):
            record = app.create_maintenance_record({
                'category': 'Parser / evidence', 'priority': 'High', 'title': 'Broadcom ID display',
                'description': 'Keep decimal source values while showing hexadecimal IDs.',
                'related': 'IOSS-1234', 'owner': 'RAID team', 'contact': 'team@example.com',
            })
            self.assertTrue(record['id'].startswith('M-'))
            self.assertEqual(app.maintenance_records()[0]['title'], 'Broadcom ID display')
            self.assertEqual(json.loads((Path(folder) / 'records.json').read_text())[-1]['priority'], 'High')

    def test_e_suffix_storage_is_external_and_excludes_built_in_backplane_scope(self):
        report = {
            "pci": {"adapters": [{"name": "ThinkSystem RAID 940-8e", "slot": "2"}]}
        }
        scope = app.classify_backplane_scope(report)
        self.assertFalse(scope["applicable"])
        self.assertEqual(scope["scope"], "external_storage")
        self.assertIn("sep_info.txt", scope["excluded_evidence"])
        self.assertIn("940-8e", scope["reason"])

    def test_external_storage_skips_backplane_automated_checks(self):
        report = {
            "format": "v1_v3",
            "pci": {"adapters": [{"name": "RAID 940-8E", "slot": "2"}], "storage": []},
            "sep_info": [{"register_type": "ctrl", "error": "CIO read failed"}],
            "sep_vpd": [{"name": "Unknown backplane"}],
            "raid_tty": {"findings": [{"severity": "Warning", "title": "Backplane UBM mode not detected"}]},
        }
        checks = app.run_automated_checks(report)
        self.assertFalse(any(check.get("category") == "Backplane" for check in checks))

    def test_mixed_internal_and_external_storage_keeps_internal_backplane_scope(self):
        report = {
            "pci": {"adapters": [
                {"name": "ThinkSystem 440-8e SAS/SATA 12Gb HBA", "slot": "2"},
                {"name": "ThinkSystem RAID 9350-8i 2GB Flash PCIe 12Gb Adapter", "slot": "3"},
            ]},
            "format": "v1_v3",
            "backplane_scope": {"scope": "external_storage", "applicable": False},
            "sep_info": [{"register_type": "ctrl", "raw": "internal register"}],
            "sep_vpd": [{"name": "Boone", "raw": "internal backplane"}],
        }
        scope = app.classify_backplane_scope(report)
        self.assertTrue(scope["applicable"])
        self.assertEqual(scope["scope"], "mixed_storage")
        self.assertIn("9350-8i", scope["internal_adapters"][0]["name"])
        self.assertIn("440-8e", scope["external_adapters"][0]["name"])
        self.assertTrue(app.backplane_evidence_applicable(report["pci"]))
        self.assertIn("internal backplane", app.compact_report_for_ai(report)["backplane_vpd"][0]["raw"])

    def test_conversation_workspace_replaces_marketing_hero(self):
        page = render_workspace_page()
        self.assertIn("FFDC Analyzer Assistant", page)
        self.assertIn("/static/workspace.js", page)
        self.assertIn("Current analysis", page)
        self.assertNotIn("Analyze ThinkSystem FFDC packages", page)
        self.assertNotIn("linear-gradient", page)
        self.assertEqual(page.count('href="/Current_bug_status_summary?view=workspace"'), 1)
        self.assertIn("FFDC Analysis Report List", page)
        self.assertNotIn("Open analysis report", page)
        self.assertEqual(page.count('id="attach-button"'), 1)
        self.assertEqual(page.count('href="/reports?view=workspace"'), 1)
        self.assertNotIn('href="/Defect_review?view=workspace"', page)
        self.assertIn('href="/reports?view=workspace"', page)
        self.assertIn('>History</a>', page)
        self.assertEqual(workspace_page_identity('/reports?view=workspace'), ('reports', 'History'))
        self.assertIn('id="jira-login-dialog"', page)
        self.assertIn('name="password" type="password"', page)

    def test_upload_default_question_follows_topbar_language(self):
        script = Path("static/workspace.js").read_text(encoding="utf-8")
        self.assertIn("window.FFDCI18n?.language?.()", script)
        self.assertIn("请分析这个 FFDC 并总结关键发现。", script)
        self.assertIn("Analyze this FFDC and summarize the key findings.", script)
        self.assertIn("defaultUploadQuestion(!!state.authoring)", script)

    def test_error_message_is_escaped(self):
        page = render_workspace_page('<script>alert("x")</script>')
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("&lt;script&gt;", page)

    def test_old_homepage_stays_default_and_links_to_new_version(self):
        old_page = app.index_page()
        self.assertIn("Analyze ThinkSystem FFDC packages", old_page)
        self.assertNotIn("workspace-shell", old_page)
        served_page = app.add_new_version_nav(old_page)
        self.assertIn("class='nav-tag nav-tag-primary' href='/new-version'>Try New version</a>", served_page)
        self.assertIn("class='nav-tag' href='/reports'>Reports</a>", served_page)
        self.assertIn(".nav-links .nav-tag{", served_page)
        history_page = "<div class='nav-links'><a href='/reports'>History</a></div>"
        self.assertIn("class='nav-tag' href='/reports'>History</a>", app.add_new_version_nav(history_page))

    def test_workspace_quick_actions_are_in_english(self):
        script = Path("static/workspace.js").read_text(encoding="utf-8")
        self.assertIn("['Analyze a Bug', 'Analyze IOSS-']", script)
        self.assertIn("['Project Milestones', 'What are the latest project milestones?']", script)
        self.assertNotIn("['分析一个 Bug'", script)
        self.assertNotIn("['项目里程碑'", script)

    def test_workspace_subpage_wraps_defect_review_without_changing_content(self):
        classic = app.render_jira_monitor_page()
        themed = render_workspace_subpage(classic, "/Defect_review?view=workspace")
        self.assertIn('class="workspace-subpage-body"', themed)
        self.assertNotIn('href="/Defect_review?view=workspace"', themed)
        self.assertIn('Defect Review - FFDC Analyzer</title>', themed)
        self.assertNotIn('class="classic-link"', themed)
        self.assertNotIn("Classic view", themed)
        self.assertIn("Login and Run Defect Review", themed)
        self.assertEqual(themed.count("id='jira-monitor-form'"), 1)
        self.assertNotIn("Defect review with FFDC analyzer tool</span>", themed)

    def test_workspace_subpage_hides_classic_link(self):
        legacy = app.HTML_HEAD + "<main><div class='topbar'>old</div><section><h2>Report body</h2></section></main></body></html>"
        themed = render_workspace_subpage(legacy, "/report?id=report-1&view=workspace#evidence")
        self.assertNotIn('class="classic-link"', themed)
        self.assertNotIn("Classic view", themed)
        self.assertIn("FFDC Analyzer Report", themed)
        self.assertIn("Report body", themed)

    def test_defect_result_wrapper_preserves_inline_handlers_once_in_order(self):
        job = {
            "id": "assignee-sort-fixture", "status": "done", "updated": 1,
            "issues": [
                {"key": "IOSS-3", "assignee": "Zoe", "ai_summary": {"status": "ok", "content": "Recommendation for IOSS-3"}},
                {"key": "IOSS-1", "assignee": "alice", "ai_summary": {"status": "ok", "content": "Recommendation for IOSS-1"}},
            ],
        }
        classic = app.render_jira_monitor_result(job)
        themed = render_workspace_subpage(classic, "/Defect_review_result?job=assignee-sort-fixture&view=workspace")

        def inline_scripts(page):
            return [body for body in re.findall(r"<script\b[^>]*>(.*?)</script\s*>", page, re.I | re.S) if body.strip()]

        original_scripts = inline_scripts(classic)
        self.assertEqual(len(original_scripts), 2)  # Assistant in main, sorting/email handler after main.
        self.assertTrue(any("data-defect-sort" in script for script in original_scripts))
        self.assertEqual(inline_scripts(themed), original_scripts)
        self.assertGreater(themed.index(original_scripts[-1]), themed.rfind("</main>"))
        # Wrapping must retain each defect directly beside its recommendation row.
        table = re.search(r"<table class='defect-review-table'>.*?</table>", classic, re.S).group()
        self.assertIn(table, themed)

    def test_assignee_names_open_all_assigned_bug_pages(self):
        page = app.render_jira_monitor_result({
            "id": "assignee-open-fixture", "updated": 1,
            "issues": [{"key": f"IOSS-{index}", "assignee": "Binbin BB1 Han"} for index in range(1, 13)]
            + [{"key": "IOSS-99", "assignee": "Yichi YC18 Zhang"}],
        })
        payloads = re.findall(r"data-bug-urls='([^']*)'", page)
        self.assertEqual(len(payloads), 2)
        urls = json.loads(html.unescape(payloads[0]))
        expected = [app.JIRA_BASE_URL.rstrip('/') + f'/browse/IOSS-{index}' for index in range(1, 13)]
        self.assertEqual(urls, expected)
        if not shutil.which('node'):
            self.skipTest('Node.js unavailable for click-handler check')
        script = re.findall(r'<script\b[^>]*>(.*?)</script\s*>', page, re.I | re.S)[-1]
        harness = r"""
const vm = require('node:vm');
const data = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const opened = []; let click;
const button = {dataset: {bugUrls: JSON.stringify(data.urls)}, addEventListener(event, handler) {if (event === 'click') click = handler;}};
const document = {getElementById() {return null;}, querySelector() {return null;}, querySelectorAll(selector) {return selector === '.assignee-bug-launch' ? [button] : [];}};
vm.runInNewContext(data.script, {document, window: {open(...args) {opened.push(args);}}});
if (opened.length) throw new Error('Bug tabs opened without a click');
if (!click) throw new Error('Missing assignee click handler');
click(); process.stdout.write(JSON.stringify(opened));
"""
        result = subprocess.run(['node', '-e', harness], input=json.dumps({'script': script, 'urls': urls}),
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [[url, '_blank'] for url in expected])

    def test_defect_review_navigation_can_be_removed_without_touching_other_pages(self):
        for route in ['/Defect_review', '/Defect_review_result?job=test', '/Defect_review_ffdcs?job=test']:
            handler = object.__new__(app.Handler)
            handler.path = route
            handler.wfile = io.BytesIO()
            handler.send_response = lambda *args: None
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            handler.send_html(app.render_jira_monitor_page())
            page = handler.wfile.getvalue().decode()
            self.assertNotIn("Try New version</a>", page)
            self.assertNotIn("href='/reports'", page)
            self.assertIn("Login and Run Defect Review", page)

    def test_defect_result_wrapper_preserves_page_styles_before_workspace_overrides(self):
        classic = app.render_jira_monitor_result({"id": "style-fixture", "updated": 1, "issues": []})
        themed = render_workspace_subpage(classic, "/Defect_review_result?job=style-fixture&view=workspace")
        style_pattern = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)
        prefix = classic[classic.index("</head>") + len("</head>"):classic.index("<main")]
        page_styles = style_pattern.findall(prefix)
        self.assertTrue(page_styles, "The real result page supplies body-prefix styles")
        self.assertEqual(style_pattern.findall(themed), style_pattern.findall(classic))
        themed_head = themed[:themed.index("</head>")]
        for style in page_styles:
            self.assertIn(style, themed_head)
            self.assertLess(themed_head.index(style), themed_head.index('/static/workspace.css'))
        self.assertNotIn("<div class='topbar'>", themed)

    def test_milestone_countdown_colours_are_available_in_workspace_view(self):
        css = Path("static/workspace-subpage.css").read_text(encoding="utf-8")
        self.assertIn(".milestone-countdown.critical{background:#f00;color:#fff}", css)
        self.assertIn(".milestone-countdown.warning{background:#ff0;color:#1b2430}", css)

    def test_workspace_result_urls_preserve_query_and_fragment(self):
        self.assertEqual(
            app.add_workspace_view("/report?id=report-1#ai-agent-analysis"),
            "/report?id=report-1&view=workspace#ai-agent-analysis",
        )
        self.assertEqual(
            app.add_workspace_view("/Defect_review_result?job=current-1"),
            "/Defect_review_result?job=current-1&view=workspace",
        )
        self.assertEqual(app.add_workspace_view("/download-tar?id=report-1"), "/download-tar?id=report-1")

    def test_workspace_chat_preloads_live_issue(self):
        issue = {"key": "IOSS-8345", "status": "Investigate", "engineer": "Engineer A"}
        report = {
            "id": "report-1",
            "source_file": "sample.tzz",
            "jira": {"issue": "IOSS-8345", "attachment": "sample.tzz"},
            "workspace_collection": {
                "root_report_id": "report-1",
                "attachments": [{"id": "report-1", "attachment": "sample.tzz"}],
            },
        }
        jira_tool = unittest.mock.Mock()
        jira_tool.get_jira_issue.return_value = {"issue": issue}
        with patch.object(app, "EvidenceTools", return_value=jira_tool), patch.object(
            app, "find_latest_workspace_jira_report", return_value=report
        ), patch.object(
            app, "call_workspace_report_chat", return_value=("answer", "model")
        ) as chat:
            answer, model, result, report = app.call_workspace_chat("查看 ioss-8345", jira_credentials=("user", "test-password"))
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
            "workspace_collection": {
                "root_report_id": "report-1",
                "attachments": [{"id": "report-1", "attachment": "sample.tzz"}],
            },
        }
        jira_tool = unittest.mock.Mock()
        jira_tool.get_jira_issue.return_value = {"issue": issue}
        with patch.object(app, "EvidenceTools", return_value=jira_tool), patch.object(
            app, "find_latest_workspace_jira_report", return_value=report
        ), patch.object(
            app, "call_workspace_report_chat", return_value=("FFDC answer", "model")
        ) as report_chat:
            answer, model, result, summary = app.call_workspace_chat("分析一下 IOSS-8345", jira_credentials=("user", "test-password"))
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
            result = app.call_workspace_chat("分析一下 IOSS-8345", jira_credentials=("user", "test-password"))
        self.assertEqual(result, (None, "", {"key": "IOSS-8345"}, None))

    def test_legacy_single_report_is_refreshed_from_jira(self):
        jira_tool = unittest.mock.Mock()
        jira_tool.get_jira_issue.return_value = {"issue": {"key": "IOSS-8345"}}
        legacy_report = {
            "id": "legacy-report",
            "source_file": "first-only.tzz",
            "jira": {"issue": "IOSS-8345", "attachment": "first-only.tzz"},
        }
        with patch.object(app, "EvidenceTools", return_value=jira_tool), patch.object(
            app, "find_latest_workspace_jira_report", return_value=legacy_report
        ), patch.object(app, "call_workspace_report_chat") as report_chat:
            result = app.call_workspace_chat("分析一下 IOSS-8345", jira_credentials=("user", "test-password"))
        self.assertEqual(result, (None, "", {"key": "IOSS-8345"}, None))
        report_chat.assert_not_called()

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
            app,
            "jira_similar_pat_headers",
            return_value={"Authorization": "Bearer server-pat"},
        ), patch.object(
            app, "build_jira_issue_ai_context", return_value={"key": "IOSS-8345"}
        ) as build_context:
            key, sources, context = app.jira_find_ffdc_sources_with_server_pat("ioss-8345")
        self.assertEqual(key, "IOSS-8345")
        self.assertEqual(sources[0]["filename"], "sample.tzz")
        self.assertEqual(context["key"], "IOSS-8345")
        self.assertEqual(build_context.call_args.kwargs["auth_headers"], {"Authorization": "Bearer server-pat"})

    def test_server_pat_merges_image_evidence_without_user_credentials(self):
        issue = {"key": "IOSS-8357", "fields": {"attachment": [{
            "id": "image-1",
            "filename": "error-screenshot.png",
            "content": "https://jira.test/file/image-1",
        }]}}
        with patch.object(
            app,
            "jira_image_comment",
            return_value={"body": "Visible error: drive not detected", "attachment": "error-screenshot.png"},
        ) as image_comment:
            comments = app.merge_jira_attachment_comments(
                issue,
                "",
                "",
                auth_headers={"Authorization": "Bearer server-pat"},
            )
        self.assertEqual(comments[0]["body"], "Visible error: drive not detected")
        self.assertEqual(image_comment.call_args.kwargs["auth_headers"], {"Authorization": "Bearer server-pat"})

    def test_server_pat_bug_without_ffdc_keeps_jira_context(self):
        issue = {"key": "IOSS-9000", "fields": {"attachment": []}}
        with patch.object(app, "jira_similar_pat_request_json", return_value=issue), patch.object(
            app,
            "jira_similar_pat_headers",
            return_value={"Authorization": "Bearer server-pat"},
        ), patch.object(
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
