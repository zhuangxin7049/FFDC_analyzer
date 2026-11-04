import json
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from workspace_analysis import WorkspaceEvidenceTools


class JiraReportCollectionTests(unittest.TestCase):
    def add_nic_archive(self, root, report_id, line):
        def packed(name, content, mode):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode=mode) as archive:
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            return output.getvalue()
        content = packed("IBMU.log", (line + "\n").encode(), "w")
        path = root / report_id / "extract" / "tmp" / "ffdc_live_dbg" / "tracebuffer" / "IBMU.tgz"
        path.parent.mkdir(parents=True)
        path.write_bytes(packed("IBMU.tar", content, "w:gz"))

    def make_report(self, root, report_id, attachment, line):
        report_dir = root / report_id
        extract = report_dir / "extract" / "var" / "log"
        extract.mkdir(parents=True)
        (extract / "events.log").write_text(line + "\n", encoding="utf-8")
        report = {
            "id": report_id,
            "source_file": attachment,
            "created_at": "2026-09-23 10:00:00",
            "format": "ffdc",
            "files": {"events.log": {"lines": 1}},
            "automated_checks": [],
            "system": {},
            "firmware": [],
            "jira": {"issue": "IOSS-8361", "attachment": attachment},
        }
        (report_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

    def test_collection_namespaces_all_attachments_and_reuses_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_report(root, "report-one", "first.tzz", "first evidence")
            self.make_report(root, "report-two", "second.tzz", "second evidence")
            rows = [
                {"id": "report-one", "attachment": "first.tzz"},
                {"id": "report-two", "attachment": "second.tzz"},
            ]
            with patch.object(app, "REPORT_DIR", root):
                collection = app.build_jira_report_collection(rows)
                first = json.loads((root / "report-one" / "report.json").read_text())
                second = json.loads((root / "report-two" / "report.json").read_text())
            self.assertEqual(collection["report_ids"], ["report-one", "report-two"])
            self.assertEqual(first["workspace_collection"], second["workspace_collection"])
            files = sorted((root / "report-one" / "workspace_extract").rglob("events.log"))
            self.assertEqual(len(files), 2)
            self.assertEqual({path.read_text().strip() for path in files}, {"first evidence", "second evidence"})
            original = root / "report-two" / "extract" / "var" / "log" / "events.log"
            self.assertEqual(os.stat(files[1]).st_ino, os.stat(original).st_ino)

    def test_chat_uses_collection_root_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_report(root, "report-one", "first.tzz", "first evidence")
            self.make_report(root, "report-two", "second.tzz", "second evidence")
            rows = [
                {"id": "report-one", "attachment": "first.tzz"},
                {"id": "report-two", "attachment": "second.tzz"},
            ]
            with patch.object(app, "REPORT_DIR", root):
                app.build_jira_report_collection(rows)
                report = app.load_workspace_report("report-one")
                with patch.object(app, "call_evidence_chat", return_value=("ok", "model")) as chat:
                    app.call_openai_chat(report, "有哪些发现", workspace=True)
            context, question = chat.call_args.args[:2]
            self.assertTrue(context["raw_logs_available"])
            self.assertEqual(context["jira_ffdc_collection"]["attachment_count"], 2)
            self.assertEqual(len(context["jira_ffdc_collection"]["attachments"]), 2)
            self.assertEqual(question, "有哪些发现")
            self.assertIn("workspace_extract", str(chat.call_args.kwargs["root"]))

    def test_comment_associations_map_success_and_failure_to_attachments(self):
        collection = {
            "attachments": [
                {"attachment": "node_xcc_260917-105832.tzz", "namespace": "01-fail"},
                {"attachment": "node_xcc_260918-223001.tzz", "namespace": "02-pass"},
            ]
        }
        jira_context = {"live_issue": {"comments": [
            {"author": "Engineer A", "created": "2026-09-17", "body": "node_xcc_260917-105832.tzz failed."},
            {"author": "Engineer A", "created": "2026-09-18", "body": "node_xcc_260918-223001.tzz passed successfully."},
        ]}}
        associations = app.build_jira_ffdc_comment_associations(jira_context, collection)
        self.assertEqual([row["comment_outcome"] for row in associations], ["failed", "successful"])
        self.assertEqual(associations[0]["namespace"], "01-fail")
        self.assertEqual(associations[1]["namespace"], "02-pass")

    def test_legacy_nested_nic_sources_refresh_into_correct_attachment_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_report(root, "report-one", "first.tzz", "first evidence")
            self.make_report(root, "report-two", "second.tzz", "second evidence")
            self.add_nic_archive(root, "report-one", "NIC firmware update failed for EID 10")
            self.add_nic_archive(root, "report-two", "NIC firmware update completed for EID 20")
            rows = [{"id": "report-one", "attachment": "first.tzz"},
                    {"id": "report-two", "attachment": "second.tzz"}]
            with patch.object(app, "REPORT_DIR", root):
                collection = app.build_jira_report_collection(rows)
                originals = {row["id"]: (root / row["id"] / "report.json").read_bytes() for row in rows}
                report = app.load_workspace_report("report-one")
                with patch.object(app, "call_evidence_chat", return_value=("ok", "model")) as chat:
                    app.call_openai_chat(report, "比较两个FFDC的网卡固件升级", workspace=True)
                context = chat.call_args.args[0]
                evidence_root = root / "report-one" / "workspace_extract"
                tools = WorkspaceEvidenceTools(evidence_root, sections=context)
                summaries = context["jira_ffdc_collection"]["attachments"]
                for summary, expected in zip(summaries, ("failed for EID 10", "completed for EID 20")):
                    source = next(iter(summary["nic_firmware"]["archive_members"]))
                    self.assertTrue(source.startswith(summary["raw_namespace"] + "/_nic_firmware/"))
                    self.assertIn(expected, json.dumps(tools.execute("read_log", {"path": source, "start": 1})))
                    self.assertEqual(tools.unsupported_citations("`" + source + ":1`"), [])
                    single = WorkspaceEvidenceTools(evidence_root, sections=summary)
                    self.assertIn(expected, json.dumps(single.prepare("网卡固件升级详情")["excerpts"]))
                selected_source = context["nic_firmware"]["events"][0]["source"]
                self.assertTrue(selected_source.startswith(collection["attachments"][0]["namespace"] + "/"))
                self.assertNotEqual(selected_source, summaries[1]["nic_firmware"]["events"][0]["source"])
                self.assertTrue(all(event["status"] == "Observed" for summary in summaries
                                    for event in summary["nic_firmware"]["events"]))
                # Refresh again from stored legacy JSON; copied views must not
                # turn generated source files into collector-rejected hardlinks.
                for row in rows:
                    fresh = app.load_workspace_report(row["id"])
                    source = next(iter(fresh["nic_firmware"]["archive_members"]))
                    self.assertEqual((root / row["id"] / "extract" / source).stat().st_nlink, 1)
                    self.assertTrue(fresh["nic_firmware"]["events"])
                    self.assertEqual((root / row["id"] / "report.json").read_bytes(), originals[row["id"]])
                # Qualification copies context, leaving single-report evidence
                # paths relative to its own extract directory.
                self.assertTrue(report["nic_firmware"]["events"][0]["source"].startswith("_nic_firmware/"))

    def test_nic_sync_rejects_another_reports_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_report(root, "report-one", "first.tzz", "first evidence")
            self.make_report(root, "report-two", "second.tzz", "second evidence")
            self.add_nic_archive(root, "report-one", "NIC firmware update failed for EID 10")
            with patch.object(app, "REPORT_DIR", root):
                collection = app.build_jira_report_collection([
                    {"id": "report-one", "attachment": "first.tzz"},
                    {"id": "report-two", "attachment": "second.tzz"}])
                report = json.loads((root / "report-one" / "report.json").read_text())
                report["workspace_collection"]["attachments"][0]["namespace"] = collection["attachments"][1]["namespace"]
                app.enrich_nic_report(report)
                other = root / "report-one" / "workspace_extract" / collection["attachments"][1]["namespace"]
                self.assertFalse((other / "_nic_firmware").exists())
                self.assertIn("could not be synchronized", " ".join(report["nic_firmware"]["limitations"]))

    def test_nic_sync_does_not_follow_namespace_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_report(root, "report-one", "first.tzz", "first evidence")
            self.make_report(root, "report-two", "second.tzz", "second evidence")
            self.add_nic_archive(root, "report-one", "NIC firmware update failed for EID 10")
            with patch.object(app, "REPORT_DIR", root):
                collection = app.build_jira_report_collection([
                    {"id": "report-one", "attachment": "first.tzz"},
                    {"id": "report-two", "attachment": "second.tzz"}])
                namespace = root / "report-one" / "workspace_extract" / collection["attachments"][0]["namespace"]
                namespace.rename(namespace.with_name(namespace.name + ".original"))
                outside = root / "outside"
                outside.mkdir()
                namespace.symlink_to(outside, target_is_directory=True)
                report = app.load_workspace_report("report-one")
                self.assertFalse((outside / "_nic_firmware").exists())
                self.assertIn("could not be synchronized", " ".join(report["nic_firmware"]["limitations"]))


if __name__ == "__main__":
    unittest.main()
