import json
import tempfile
import unittest
from pathlib import Path

from domain_packs import DomainPackRegistry
from workspace_analysis import WorkspaceEvidenceTools


class DomainPackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nic_pack_extracts_facts_and_line_evidence(self):
        (self.root / "dmesg.log").write_text(
            "[1.0] eth2 link is down\n"
            "[2.0] ice firmware error on adapter\n"
            "[3.0] eth2 link is up\n",
            encoding="utf-8",
        )
        registry = DomainPackRegistry(Path(__file__).parent / "domain_packs")
        paths = [self.root / "dmesg.log"]
        result = registry.analyze(self.root, paths, lambda path: self._lines(path), "网卡有什么发现？")
        self.assertEqual([row["name"] for row in result["packs"]], ["nic"])
        self.assertEqual(result["findings"][0]["evidence"]["path"], "dmesg.log")
        self.assertEqual(result["findings"][0]["evidence"]["start"], 1)
        self.assertIn({"domain": "nic", "field": "link_state", "value": "down", "source": "dmesg.log", "line": 1}, result["facts"])
        self.assertIn({"kind": "log", "path": "dmesg.log", "start": 2, "end": 2}, result["sources"])

    def test_pack_can_be_selected_by_file_name_for_broad_findings(self):
        (self.root / "network_events.txt").write_text("carrier lost on eth0\n", encoding="utf-8")
        registry = DomainPackRegistry(Path(__file__).parent / "domain_packs")
        result = registry.analyze(self.root, [self.root / "network_events.txt"], lambda path: self._lines(path), "有什么发现？")
        self.assertEqual(result["packs"][0]["name"], "nic")
        self.assertEqual(result["findings"][0]["rule_id"], "nic.link_down")

    def test_workspace_prepare_exposes_domain_pack_evidence(self):
        (self.root / "ethtool_eth0.txt").write_text("Link detected: no\n", encoding="utf-8")
        tools = WorkspaceEvidenceTools(self.root)
        prepared = tools.prepare("网卡有什么问题？")
        pack = prepared["domain_pack_evidence"]
        self.assertEqual(pack["packs"][0]["name"], "nic")
        self.assertTrue(pack["findings"])
        self.assertIn({"kind": "log", "path": "ethtool_eth0.txt", "start": 1, "end": 1}, tools.sources)

    @staticmethod
    def _lines(path):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            yield number, line, len(line.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
