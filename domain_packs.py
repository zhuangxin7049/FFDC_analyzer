"""Read-only, declarative FFDC domain packs.

Domain packs describe where to look and what deterministic signals mean. They
do not execute shell commands or arbitrary Python. The resulting findings keep
the original file and line range so the AI layer can distinguish evidence from
inference.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path


MAX_PACK_FILES = 48
MAX_PACK_BYTES = 6 * 1024 * 1024
MAX_PACK_MATCHES = 80
MAX_RULE_PATTERN_LENGTH = 600
MAX_PACK_NAME_LENGTH = 64


class DomainPackError(ValueError):
    """Raised when a domain pack is invalid or unsafe to load."""


def _compile(pattern, label):
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_RULE_PATTERN_LENGTH:
        raise DomainPackError(f"Invalid {label} pattern.")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise DomainPackError(f"Invalid {label} regular expression: {exc}") from exc


def _validate_pack(raw, source):
    if not isinstance(raw, dict):
        raise DomainPackError(f"{source}: pack must be an object.")
    name = raw.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", name):
        raise DomainPackError(f"{source}: invalid pack name.")
    version = raw.get("version")
    if not isinstance(version, str) or len(version) > 32:
        raise DomainPackError(f"{source}: invalid pack version.")
    keywords = raw.get("question_keywords", [])
    file_patterns = raw.get("file_patterns", [])
    rules = raw.get("rules", [])
    extractors = raw.get("extractors", [])
    if not all(isinstance(item, str) and item and len(item) <= 120 for item in keywords):
        raise DomainPackError(f"{source}: invalid question keyword.")
    if not all(isinstance(item, str) and item and len(item) <= 240 for item in file_patterns):
        raise DomainPackError(f"{source}: invalid file pattern.")
    for index, extractor in enumerate(extractors):
        if not isinstance(extractor, dict) or not isinstance(extractor.get("field"), str):
            raise DomainPackError(f"{source}: invalid extractor {index}.")
        _compile(extractor.get("pattern"), f"extractor {index}")
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            raise DomainPackError(f"{source}: invalid rule {index}.")
        patterns = rule.get("patterns", [])
        if not isinstance(patterns, list) or not patterns:
            raise DomainPackError(f"{source}: rule {index} needs patterns.")
        for pattern in patterns:
            _compile(pattern, f"rule {index}")
        for pattern in rule.get("exclude_patterns", []):
            _compile(pattern, f"rule {index} exclusion")
    return raw


class DomainPackRegistry:
    """Load and run approved JSON packs against an extracted FFDC root."""

    def __init__(self, packs_dir=None):
        self.packs_dir = Path(packs_dir or Path(__file__).with_name("domain_packs"))
        self.packs = []
        self.errors = []
        self._load()

    def _load(self):
        if not self.packs_dir.is_dir():
            return
        for path in sorted(self.packs_dir.glob("*/pack.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.packs.append(_validate_pack(raw, str(path)))
            except (OSError, json.JSONDecodeError, DomainPackError) as exc:
                self.errors.append({"path": str(path), "error": str(exc)})

    def catalog(self):
        return [{
            "name": pack["name"],
            "version": pack["version"],
            "display_name": pack.get("display_name", pack["name"]),
        } for pack in self.packs]

    @staticmethod
    def _matches_path(relative, patterns):
        relative = relative.replace("\\", "/")
        basename = Path(relative).name
        return any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(basename, pattern) for pattern in patterns)

    def _selected(self, question, relative_paths):
        question = str(question or "").lower()
        selected = []
        for pack in self.packs:
            keyword_hit = any(str(keyword).lower() in question for keyword in pack.get("question_keywords", []))
            file_hits = [
                path for path in relative_paths
                if self._matches_path(path, pack.get("file_patterns", []))
            ]
            if keyword_hit or file_hits:
                selected.append((pack, file_hits))
        return selected

    @staticmethod
    def _relative(root, path):
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")

    def analyze(self, root, paths, line_reader, question="", redact_line=None):
        """Run selected packs with bounded, read-only access to supplied paths."""
        if not root or not Path(root).is_dir():
            return {"available": False, "packs": [], "findings": [], "facts": [], "sources": []}
        root = Path(root).resolve()
        path_rows = []
        for path in paths:
            try:
                relative = self._relative(root, path)
                path_rows.append((Path(path), relative))
            except (OSError, ValueError):
                continue
        selected = self._selected(question, [relative for _, relative in path_rows])
        all_findings, all_facts, all_sources, pack_rows = [], [], [], []
        for pack, matched_names in selected:
            pack_paths = [(path, relative) for path, relative in path_rows if relative in matched_names]
            findings, facts, sources = self._run_pack(pack, root, pack_paths, line_reader, redact_line)
            all_findings.extend(findings)
            all_facts.extend(facts)
            all_sources.extend(sources)
            pack_rows.append({
                "name": pack["name"],
                "version": pack["version"],
                "files_considered": len(pack_paths),
                "findings": len(findings),
                "facts": len(facts),
                "missing_data": [] if pack_paths else pack.get("required_sources", []),
            })
        return {
            "available": True,
            "catalog": self.catalog(),
            "pack_errors": self.errors,
            "packs": pack_rows,
            "findings": all_findings[:MAX_PACK_MATCHES],
            "facts": all_facts[:MAX_PACK_MATCHES],
            "sources": all_sources[:MAX_PACK_MATCHES],
            "note": "Domain-pack matches are deterministic evidence leads. Davy must distinguish them from hypotheses and verify surrounding lines.",
        }

    def _run_pack(self, pack, root, pack_paths, line_reader, redact_line):
        compiled_rules = []
        for rule in pack.get("rules", []):
            compiled_rules.append((
                rule,
                [_compile(pattern, rule["id"]) for pattern in rule.get("patterns", [])],
                [_compile(pattern, rule["id"] + " exclusion") for pattern in rule.get("exclude_patterns", [])],
            ))
        compiled_extractors = [
            (extractor, _compile(extractor["pattern"], extractor["field"]))
            for extractor in pack.get("extractors", [])
        ]
        findings, facts, sources = [], [], []
        seen = set()
        consumed = 0
        for path, relative in pack_paths[:MAX_PACK_FILES]:
            try:
                if path.stat().st_size > MAX_PACK_BYTES:
                    continue
                for number, raw_line, size in line_reader(path):
                    consumed += size
                    if consumed > MAX_PACK_BYTES:
                        break
                    line = redact_line(raw_line) if redact_line else str(raw_line)
                    for extractor, pattern in compiled_extractors:
                        match = pattern.search(line)
                        if not match:
                            continue
                        group = int(extractor.get("value_group", 1))
                        value = match.group(group) if group <= len(match.groups()) else match.group(0)
                        facts.append({"domain": pack["name"], "field": extractor["field"], "value": value,
                                      "source": relative, "line": number})
                    for rule, patterns, exclusions in compiled_rules:
                        if not any(pattern.search(line) for pattern in patterns):
                            continue
                        if any(pattern.search(line) for pattern in exclusions):
                            continue
                        key = (rule["id"], relative, number)
                        if key in seen:
                            continue
                        seen.add(key)
                        evidence = {"kind": "log", "path": relative, "start": number, "end": number}
                        sources.append(evidence)
                        findings.append({
                            "domain": pack["name"],
                            "rule_id": rule["id"],
                            "severity": rule.get("severity", "Info"),
                            "category": rule.get("category", pack.get("display_name", pack["name"])),
                            "title": rule.get("title", rule["id"]),
                            "message": rule.get("message", "A domain rule matched this log line."),
                            "evidence": {**evidence, "text": line[:1200]},
                        })
                        if len(findings) >= MAX_PACK_MATCHES:
                            return findings, facts, sources
            except OSError:
                continue
        return findings, facts, sources
