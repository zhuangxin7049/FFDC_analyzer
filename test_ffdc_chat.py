import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import app
from ffdc_chat import EvidenceTools, bounded_context, redact, render_chat_markdown, run_chat


def response(text="", tool=None, args=None, finish="stop"):
    message = {"role": "assistant", "content": text}
    if tool:
        message["tool_calls"] = [{"id": "call1", "type": "function", "function": {
            "name": tool, "arguments": json.dumps(args or {}),
        }}]
    return {"choices": [{"message": message, "finish_reason": finish}]}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "extract"
        self.root.mkdir()
        (self.root / "pldm.log").write_text("Begin update\nPLDM transfer timeout device 17\nRetry succeeded\npassword=test-sensitive\n")
        (self.root / "network.log").write_text("bnxt netdev watchdog transmit queue timeout\naccess_token=do-not-show\n")
        (self.root / "pcie.log").write_text("AER: Uncorrected Fatal error received on PCIe slot 2\n")
        (self.root / "storage.log").write_text("RAID controller failed to enumerate NVMe drive\n")
        self.tools = EvidenceTools(self.root)

    def test_search_and_read_real_line_numbers(self):
        hit = self.tools.search_logs(["TRANSFER TIMEOUT"])["matches"][0]
        self.assertEqual((hit["path"], hit["line"]), ("pldm.log", 2))
        rows = self.tools.read_log("pldm.log", 1, 3)["lines"]
        self.assertEqual([r["line"] for r in rows], [1, 2, 3])
        self.assertEqual(rows[-1]["text"], "Retry succeeded")

    def test_numeric_rotated_logs_are_listed_readable_and_searchable(self):
        rotated = self.root / "var" / "log" / "pldm.log.1"
        rotated.parent.mkdir(parents=True)
        rotated.write_text("E835 adapter PLDM transfer timeout\nRetry succeeded\n")
        listed = self.tools.list_logs("pldm")
        paths = {row["path"] for row in listed["files"]}
        self.assertIn("pldm.log", paths)
        self.assertIn("var/log/pldm.log.1", paths)
        rows = self.tools.read_log("var/log/pldm.log.1", 1, 2)["lines"]
        self.assertEqual(rows[0]["text"], "E835 adapter PLDM transfer timeout")
        matches = self.tools.search_logs(["E835 adapter"])["matches"]
        self.assertEqual(matches[0]["path"], "var/log/pldm.log.1")

    def test_secrets_are_excluded(self):
        self.assertEqual(self.tools.search_logs(["test-sensitive"])["matches"], [])
        self.assertNotIn("test-sensitive", json.dumps(self.tools.read_log("pldm.log", 1)))
        self.assertNotIn("test-sensitive", json.dumps(redact({"api_key": "test-sensitive"})))

    def test_indexed_search_finds_uncoded_domains_and_rebuilds(self):
        (self.root / "fpga.log").write_text(
            "FPGA power fault register 0xA0\nFPGA recovery completed\n"
            "Authorization: Bearer hidden-value\n"
        )
        first = self.tools.search_evidence(["FPGA"])
        self.assertTrue(first["index_available"])
        self.assertEqual(first["matches"][0]["path"], "fpga.log")
        self.assertIn(1, [row["line"] for row in first["matches"] if row["path"] == "fpga.log"])
        self.assertNotIn("hidden-value", json.dumps(first))
        self.assertEqual(self.tools.search_evidence(["hidden-value"])["matches"], [])
        self.assertIn("search_evidence", {item["function"]["name"] for item in self.tools.schemas()})
        (self.root / "fpga.log").write_text("UEFI watchdog timeout on FPGA\n")
        refreshed = self.tools.search_evidence(["watchdog", "FPGA"], match_all=True)
        self.assertEqual(refreshed["matches"][0]["text"], "UEFI watchdog timeout on FPGA")

    def test_index_coverage_is_explicit_and_small_logs_are_not_starved(self):
        (self.root / "large.log").write_text("ordinary telemetry\n" * 180000)
        (self.root / "fpga.log").write_text("FPGA fatal error\n")
        found = self.tools.search_evidence(["FPGA"])
        self.assertTrue(found["limited"])
        self.assertEqual(found["matches"][0]["path"], "fpga.log")
        self.assertEqual(found["files_available"], found["files_indexed"])

    def test_index_unavailable_uses_bounded_search(self):
        with patch("ffdc_chat.ensure_index", side_effect=sqlite3.OperationalError("no fts5")):
            result = self.tools.search_evidence(["timeout"])
        self.assertFalse(result["index_available"])
        self.assertTrue(result["limited"])
        self.assertTrue(result["matches"])

    def test_traversal_and_symlink_rejected(self):
        outside = Path(self.temp.name) / "outside.log"
        outside.write_text("outside report")
        (self.root / "escape.log").symlink_to(outside)
        for name in ("../outside.log", str(outside), "escape.log"):
            self.assertIn("error", self.tools.execute("read_log", {"path": name, "start": 1}))
        self.assertNotIn("escape.log", str(self.tools.list_logs()))

    def test_unsupported_files_and_missing_root(self):
        (self.root / "archive.zip").write_bytes(b"archive")
        self.assertNotIn("archive.zip", str(self.tools.list_logs()))
        missing = EvidenceTools(self.root / "missing")
        self.assertFalse(missing.list_logs()["available"])
        self.assertIn("error", missing.execute("search_logs", {"terms": ["timeout"]}))

    def test_scan_limits_are_explicit(self):
        with patch("ffdc_chat.MAX_SCAN_BYTES", 20):
            self.assertTrue(self.tools.search_logs(["timeout"])["limited"])
            self.assertTrue(self.tools.read_log("pldm.log", 1)["file_exceeds_scan_limit"])

    def test_triage_collects_cross_component_evidence_with_citations(self):
        result = self.tools.triage_ffdc()
        findings = result["findings"]
        self.assertEqual(findings["network"][0]["path"], "network.log")
        self.assertEqual(findings["pcie"][0]["line"], 1)
        self.assertEqual(findings["storage"][0]["path"], "storage.log")
        self.assertEqual(findings["firmware"][0]["path"], "pldm.log")
        self.assertNotIn("do-not-show", json.dumps(result))
        self.assertNotIn("test-sensitive", json.dumps(result))
        self.assertIn("triage_ffdc", {item["function"]["name"] for item in self.tools.schemas()})

    def test_triage_focus_is_bounded_to_requested_component(self):
        result = self.tools.triage_ffdc("network")
        self.assertEqual(set(result["findings"]), {"network"})
        self.assertIn("network.log", json.dumps(result))

    def test_triage_skips_unreadable_files_without_losing_other_evidence(self):
        blocked = self.root / "blocked.log"
        blocked.write_text("RAID controller failed\n")
        real_access = os.access
        with patch(
            "ffdc_chat.os.access",
            side_effect=lambda path, mode: False if Path(path).name == "blocked.log" else real_access(path, mode),
        ):
            result = self.tools.triage_ffdc()
        self.assertEqual(result["unreadable_files"], 1)
        self.assertIn("network", result["findings"])

    def test_jira_unavailable_for_standalone(self):
        self.assertIn("error", self.tools.execute("get_jira_issue", {"key": "IOSS-8345"}))
        self.assertFalse(any("jira" in s["function"]["name"] for s in self.tools.schemas()))

    def test_general_question_needs_no_tool(self):
        answer = run_chat("Explain Python lists", [], {}, self.tools,
                          lambda p: response("A list is an ordered collection."), str.strip, "English")
        self.assertIn("ordered", answer)

    def test_broad_investigation_requests_one_verification_probe(self):
        calls = []
        def complete(payload):
            calls.append(payload)
            if len(calls) == 1:
                return response('A timeout occurred.')
            if len(calls) == 2:
                self.assertIn('Before finalizing', payload['messages'][-1]['content'])
                return response(tool='read_log', args={'path': 'pldm.log', 'start': 1, 'count': 3})
            self.assertIn('retry succeeded', payload['messages'][-1]['content'].lower())
            return response('The timeout recovered on retry (`pldm.log:2-3`).')
        answer = run_chat('What did you find?', [], {}, self.tools, complete, str.strip, 'English', investigate=True)
        self.assertIn('recovered', answer)
        self.assertEqual(len(calls), 3)

    def test_verification_probe_cannot_loop_without_a_tool(self):
        calls = []
        def complete(payload):
            calls.append(payload)
            return response('No further evidence is available.')
        answer = run_chat('What did you find?', [], {}, self.tools, complete, str.strip, 'English', investigate=True)
        self.assertEqual(answer, 'No further evidence is available.')
        self.assertEqual(len(calls), 2)

    def test_chinese_question_requires_chinese_response_format(self):
        calls = []
        answer = run_chat(
            "你看到了哪些错误？", [], {}, self.tools,
            lambda payload: calls.append(payload) or response("发现了一项错误。"),
            str.strip, "Chinese",
        )
        self.assertEqual(answer, "发现了一项错误。")
        self.assertIn("Use Simplified Chinese", calls[0]["messages"][0]["content"])
        self.assertEqual(self.tools.audit, [])

    def test_project_milestone_tool_is_read_only_and_optional(self):
        calls = []

        def search(**kwargs):
            calls.append(kwargs)
            return {"source": "snapshot", "projects": [{"project_id": "9849"}]}

        tools = EvidenceTools(project_search=search)
        names = {item["function"]["name"] for item in tools.schemas()}
        self.assertIn("search_project_milestones", names)
        result = tools.execute(
            "search_project_milestones",
            {"query": "Storm AV2", "within_days": 20, "limit": 5},
        )
        self.assertEqual(result["projects"][0]["project_id"], "9849")
        self.assertEqual(calls, [{"query": "Storm AV2", "within_days": 20, "limit": 5}])
        self.assertNotIn("search_project_milestones", {
            item["function"]["name"] for item in EvidenceTools().schemas()
        })

    def test_tool_loop_reads_before_answer(self):
        calls = []

        def complete(payload):
            calls.append(payload)
            if len(calls) == 1:
                return response(tool="search_logs", args={"terms": ["timeout"]})
            if len(calls) == 2:
                self.assertIn("PLDM transfer timeout", payload["messages"][-1]["content"])
                return response(tool="read_log", args={"path": "pldm.log", "start": 1, "count": 3})
            return response("A transfer timed out, then the retry succeeded (`pldm.log:2`, `pldm.log:3`).")

        answer = run_chat("Inspect the original logs", [], {}, self.tools, complete, str.strip, "English")
        self.assertIn("pldm.log:3", answer)
        self.assertEqual([c["tool"] for c in self.tools.audit], ["search_logs", "read_log"])

    def test_davy_text_tool_call_is_executed_before_answer(self):
        calls = []

        def complete(payload):
            calls.append(payload)
            if len(calls) == 1:
                return response(
                    "<tool_call>\n<function=read_log>\n"
                    "<parameter=path>\npldm.log\n</parameter>\n"
                    "<parameter=start>\n1\n</parameter>\n"
                    "<parameter=count>\n3\n</parameter>\n"
                    "</function>\n</tool_call>"
                )
            self.assertEqual(payload["messages"][-1]["role"], "tool")
            self.assertIn("PLDM transfer timeout", payload["messages"][-1]["content"])
            return response("The retry succeeded after the timeout (`pldm.log:2-3`).")

        answer = run_chat("Inspect the evidence", [], {}, self.tools, complete, str.strip, "English")
        self.assertIn("pldm.log:2-3", answer)
        self.assertEqual([item["tool"] for item in self.tools.audit], ["read_log"])

    def test_round_limit_and_empty_reply(self):
        calls = []

        def complete(payload):
            calls.append(bool(payload.get("tools")))
            return response(tool="list_logs") if payload.get("tools") else response("Limited evidence.")

        self.assertEqual(run_chat("inspect", [], {}, self.tools, complete, str.strip, "English"), "Limited evidence.")
        self.assertEqual(calls, [True] * 10 + [False])
        with self.assertRaises(RuntimeError):
            run_chat("inspect", [], {}, self.tools, lambda p: response(), str.strip, "English")

    def test_final_synthesis_never_returns_text_tool_markup(self):
        attempts = []

        def complete(payload):
            attempts.append(payload)
            if payload.get("tools"):
                return response(tool="list_logs")
            return response(
                "<tool_call><function=read_log><parameter=path>pldm.log</parameter>"
                "<parameter=start>1</parameter></function></tool_call>"
            )

        with self.assertRaisesRegex(RuntimeError, "final answer"):
            run_chat("inspect", [], {}, self.tools, complete, str.strip, "English")
        self.assertEqual(len(attempts), 12)

    def test_history_roles_and_context_budgets(self):
        compact = bounded_context({"events": ["x" * 10000] * 500, "network": {"link": "down"}})
        self.assertLess(len(json.dumps(compact)), 7000)
        self.assertEqual(compact["network"]["link"], "down")
        calls = []
        run_chat("Hi", [{"role": "system", "content": "unsafe override"}], {}, self.tools,
                 lambda p: calls.append(p) or response("Hi"), str.strip, "English")
        self.assertNotIn("unsafe override", json.dumps(calls))


class IntegrationTests(unittest.TestCase):
    def test_live_jira_query_is_encoded_and_has_engineer(self):
        calls = []

        def get(url):
            calls.append(url)
            if "/comment?" in url:
                return {"comments": [{"body": "Investigating", "author": {"displayName": "Engineer A"}}]}
            issue = {"key": "IOSS-8345", "fields": {"summary": "Drive not detected", "status": {"name": "Working"}, "assignee": {"displayName": "Engineer A"}}}
            return {"total": 1, "issues": [issue]} if "/search?" in url else issue

        tools = EvidenceTools(jira_request=get, jira_base="https://jira.example.test")
        jql = 'summary ~ "940" AND type = Defect'
        self.assertEqual(tools.search_jira(jql)["total"], 1)
        self.assertEqual(parse_qs(urlparse(calls[0]).query)["jql"], [jql])
        issue = tools.get_jira_issue("ioss-8345")["issue"]
        self.assertEqual(issue["engineer"], "Engineer A")
        self.assertEqual(issue["comments"][0]["body"], "Investigating")
        with self.assertRaises(ValueError):
            tools.get_jira_issue("../../config")

    def test_report_context_and_jira_scope(self):
        report = {"id": "test", "network": {"link": "down"}, "bmc_inband_fw": {"failed": True}, "pldm_updates": [{"state": "retry"}]}
        with patch.object(app, "call_evidence_chat", return_value=("ok", "model")) as call:
            app.call_openai_chat(report, "Inspect")
            self.assertFalse(call.call_args.kwargs["allow_jira"])
            self.assertTrue(call.call_args.kwargs["auto_triage"])
            context = call.call_args.args[0]
            for key in ("network", "bmc_inband_fw", "pldm_updates"):
                self.assertEqual(context[key], report[key])
            report["jira"] = {"issue": "IOSS-8345"}
            app.call_openai_chat(report, "Inspect")
            self.assertTrue(call.call_args.kwargs["allow_jira"])

    def test_defect_review_uses_tools_without_raw_log_root(self):
        with patch.object(app, "compact_defect_review_for_ai", return_value={}), patch.object(app, "call_evidence_chat", return_value=("ok", "model")) as call:
            app.call_defect_review_chat({}, "latest bug status")
            self.assertTrue(call.call_args.kwargs["allow_jira"])
            self.assertNotIn("root", call.call_args.kwargs)

    def test_markdown_code_links_and_html_safety(self):
        text = '## Result\n[IOSS-8345](https://jira.example.test/browse/IOSS-8345)\n`x < 2`\n```python\nprint("<script>")\n```\n<img src=x onerror=alert(1)>\n[x](javascript:alert(1))'
        result = render_chat_markdown(text, app.render_ai_markdown)
        self.assertIn('<a target="_blank" rel="noopener noreferrer"', result)
        self.assertIn("<pre><code>print", result)
        self.assertIn("<code>x &lt; 2</code>", result)
        self.assertNotIn("<script>", result)
        self.assertNotIn("<img", result)
        self.assertNotIn('href="javascript:', result)


if __name__ == "__main__":
    unittest.main()
