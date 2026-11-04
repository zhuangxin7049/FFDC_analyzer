"""Focused, inspectable evidence preparation for the conversation workspace."""
import json
import re
import time

from ffdc_chat import (
    EvidenceTools, TRIAGE_COMPONENTS, TRIAGE_FAILURE, bounded_context, function, redact,
)
from domain_packs import DomainPackRegistry

FOCUS_WORDS = {
    'network': r'网卡|网口|网络|丢包|以太|\b(?:nic|ethernet|network|netdev|mlx\w*|bnxt\w*|mellanox|connectx\w*|qlogic|emulex|bcm57\w*|e810|e823|x710|xxv710|link down|carrier)\b',
    'storage': r'背板|磁盘|硬盘|盘符|\b(?:raid|hba|drive|disk|nvme|backplane|psoc|ubm)\b',
    'firmware': r'固件|刷写|升级|\b(?:firmware|flash|pldm|mctp|bmu|in.?band)\b',
    'pcie': r'通道|链路宽|\b(?:pcie|aer|link width|link speed)\b',
    'system': r'内存|电源|温度|\b(?:dimm|memory|cpu|thermal|power|watchdog|panic)\b',
}
BENIGN = re.compile(r'\b(?:no errors?|0 errors?|errors?\s*[:=]\s*0\b|failures?\s*[:=]\s*0\b|error handling|error injection|supported error)\b', re.I)
URGENT = re.compile(r'\b(?:fatal|uncorrectable|panic|critical|failed|timeout|unsupported|not detected)\b', re.I)
DISCOVERY_SIGNAL = re.compile(
    r'\b(?:fault|mismatch|invalid|exception|assert(?:ed|ion)?|over.?temp|over.?current|'
    r'under.?voltage|retry|retries|unexpected|changed|transition(?:ed)?|corrupt(?:ed|ion)?)\b', re.I,
)
NIC_IDENTITY = re.compile(
    r'\b(?:nic|ethernet|network|netdev|mellanox|connectx\w*|qlogic|emulex|'
    r'bnxt\w*|mlx\w*|bcm57\w*|e810|e823|x710|xxv710)\b', re.I,
)
NIC_UPDATE_SIGNAL = re.compile(
    r'\b(?:firmware|flash|update|upgrade|success\w*|fail\w*|error|timeout|'
    r'EID|TID|PLDM|MCTP|BMU|IBMU)\b', re.I,
)
INSTRUCTIONS = """You are investigating the currently selected FFDC, not writing a generic report.
Answer the latest question directly. For broad findings: a 1-2 sentence conclusion, at most 5 ranked findings with short evidence/meaning/next-check bullets, then the most useful unresolved question. For focused follow-ups answer only the requested point; do not repeat the entire investigation or unrelated JIRA boilerplate.
Use the user's requested language, including headings. Preserve exact device identifiers and original quoted log text. Never infer a server model from a controller model (for example RAID 940 is not a ThinkSystem server model).
Keep three evidence levels distinct: original log observations (cite `path:line`), parser/automatic-check observations (cite `report:section`), and hypotheses. A keyword match, a missing inventory field, or an automatic warning alone is not proof of a fault or root cause. No match in a limited scan is not proof the machine is healthy.
Check surrounding lines and timestamps, recovery/retry outcomes, slot/device scope, and collection time. Historical errors that recovered are not current failures. Do not conflate empty/unpopulated drive bays with failed disks, or independent controller-local slot numbers with a proven backplane conflict. Never claim an upgrade or version transition from a single firmware snapshot.
Scope health conclusions to the latest supplied record, not the live machine. Say "the latest supplied log shows recovery; it does not establish the current physical state" instead of "the NIC is not faulty" or "the system is healthy". A zero error counter alone does not exclude intermittent faults.
For NIC analysis correlate adapter slot, EID/TID, PCI IDs, firmware components, and ports only when the original records establish the association. LinkDown with 0 Gbps is an inventory snapshot, not proof of a faulty NIC or failed update. Preserve a V4 packed Addr as raw data; never fabricate a PCI BDF conversion. Shared PLDM/MCTP/FM events require an explicit device association before attributing them to a NIC. A BMU launch/status outcome is not a NIC firmware update outcome. Missing update logs or unknown outcomes must remain explicit limitations; expected filenames are not discovered evidence. Use nic_firmware.log_sources and their origin to trace materialized nested logs, and cite the readable source path and line.
For a Bug investigation use its title, description, recent engineer comments, and available FFDC. Describe explicitly which assertions are from JIRA vs logs. If comments conflict with logs or the root cause is unconfirmed, state the conflict and the concrete next check. If no Bug is linked, simply analyze the FFDC; do not add an empty JIRA section.
When `jira_ffdc_collection` is present, the Bug has multiple JIRA FFDC attachments. Treat every listed attachment and every namespaced raw-log path in the collection as available evidence. Compare the attachments by collection time and device identity; never say that only one FFDC is available merely because one report is selected in the UI. Cite the attachment namespace and path when the same filename appears in more than one FFDC. Use `comment_associations` to connect an explicit JIRA comment to a named FFDC and compare reported failed/successful outcomes, but label the comment as an engineering claim and verify it against the corresponding log evidence. If a comment cannot be mapped to a named attachment, keep it separate instead of guessing.
Backplane specification baseline: Lenovo SP-000008 Firmware Specification v1.06 is the user-confirmed current project baseline for V4/V5. Use report.backplane_analysis for explicit register meanings and limitations. Candidate bay mappings do not confirm physical controller/backplane identity. Configured bifurcation is distinct from negotiated width. A reported firmware result requires an explicit device match; script completion or a single version snapshot is insufficient.
Scope rule: a storage adapter model ending in E (for example 440-8e) is external storage. Do not use sep_info.txt, sep_vpd.txt, or backplanes.txt/backplanes.json to diagnose that external path. If the same report also contains an internal storage adapter (for example 9350-8i), those files remain valid for the internal backplane path and must be analyzed separately. State the scope for each controller before drawing a conclusion.
Do not fabricate an engineer, timestamp, register interpretation, citation, affected model, or solution. Use original evidence tools for missing details. Prepared excerpts are real source lines already read; search and read more only when needed. For FPGA, thermal, UEFI, XCC, and other areas without a dedicated parsed report, use search_evidence with relevant original-log terms and read_log around candidate lines. For broad questions, inspect unclassified anomaly leads and file names as well as familiar categories; form hypotheses, then check timestamps, recovery, and contrary evidence before concluding. Evidence from a previous turn has been reopened from the original log, but a previous assistant statement alone is not proof. An incomplete index or absent match never proves a component is healthy. Use read_report_section to inspect fields omitted from the compact snapshot. For project questions use the milestone tool and include its snapshot date.
In next checks, use only filenames actually returned by the tools or supplied context. Do not invent likely filenames such as system.log or fw_update.log. If no relevant filename has been identified, name the evidence category needed (for example firmware update history) without pretending a specific file exists.
Use concise paragraphs and numbered findings. No wide tables for narrative diagnostic findings. Avoid repeated severity/category columns and long hardware inventories. Do not expose internal reasoning or tool markup.
"""


def focus_for(question):
    return [name for name, pattern in FOCUS_WORDS.items() if re.search(pattern, str(question), re.I)]


class WorkspaceEvidenceTools(EvidenceTools):
    def __init__(self, *args, sections=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sections = sections or {}
        self.sources = []
        self.source_keys = set()
        self.scan = None
        self.started = time.monotonic()
        self.cached_results = {}
        self.reopened_sources = 0
        self.domain_packs = DomainPackRegistry()

    def schemas(self):
        schemas = super().schemas()
        if self.sections:
            schemas.append(function('read_report_section', 'Read a parsed report section. For lists, use offset to inspect additional records. Parsed checks are not verified root causes.',
                                    {'section': {'type': 'string', 'enum': sorted(self.sections)},
                                     'offset': {'type': 'integer', 'minimum': 0}}, ['section']))
        return schemas

    def add_source(self, source):
        key = json.dumps(source, sort_keys=True)
        if key not in self.source_keys and len(self.sources) < 32:
            self.source_keys.add(key)
            self.sources.append(source)

    def read_report_section(self, section, offset=0):
        if section not in self.sections:
            raise ValueError('Unknown parsed report section.')
        value = self.sections[section]
        offset = max(0, int(offset))
        total = len(value) if isinstance(value, list) else None
        page = value[offset:offset + 20] if total is not None else value
        self.add_source({'kind': 'report', 'section': section, 'label': 'report:' + section,
                         'description': 'Parsed report data; automated findings still require interpretation.'})
        return {'section': section, 'data': bounded_context({section: page})[section],
                'offset': offset, 'total': total, 'next_offset': offset + 20 if total is not None and offset + 20 < total else None}

    def read_log(self, path, start, count=60):
        result = super().read_log(path, start, count)
        if result['lines']:
            self.add_source({'kind': 'log', 'path': path, 'start': result['lines'][0]['line'], 'end': result['lines'][-1]['line']})
        return result

    def get_jira_issue(self, key):
        result = super().get_jira_issue(key)
        issue = result.get('issue') or {}
        self.add_source({'kind': 'jira', 'label': issue.get('key', key), 'url': issue.get('url', ''), 'description': 'Live JIRA title, description, status and recent comments.'})
        return result

    def search_project_milestones(self, **kwargs):
        result = super().search_project_milestones(**kwargs)
        self.add_source({'kind': 'projects', 'label': 'Project milestone snapshot', 'url': '/Current_bug_status_summary',
                         'description': 'Project milestone snapshot queried for this answer.'})
        return result

    def execute(self, name, args):
        cache_key = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        if cache_key in self.cached_results:
            return self.cached_results[cache_key]
        result = super().execute(name, args)
        if not result.get('error'):
            self.cached_results[cache_key] = result
        return result

    def triage_ffdc(self, focus='all'):
        """Distribute a bounded scan across files and keep diverse, contextual leads."""
        if not self.root or not self.root.is_dir():
            raise ValueError('Raw FFDC files are unavailable for this report.')
        if focus != 'all' and focus not in TRIAGE_COMPONENTS:
            raise ValueError('Unknown focus.')
        categories = list(TRIAGE_COMPONENTS) + ['unclassified'] if focus == 'all' else [focus]
        matches = {category: [] for category in categories}
        seen = set()
        self.unreadable_paths = 0
        paths = list(self.paths())
        # Small event logs come before large inventories; every file receives its own byte budget.
        paths.sort(key=lambda path: (not any(word in path.name.lower() for word in ('event', 'dmesg', 'pldm', 'mctp', 'network', 'tty')), path.stat().st_size, str(path)))
        consumed, scanned, unreadable = 0, 0, self.unreadable_paths
        limited = len(paths) > 240
        for path in paths[:240]:
            scanned += 1
            file_bytes = 0
            try:
                for number, line, size in self.lines(path):
                    consumed += size; file_bytes += size
                    if consumed > 12 * 1024 * 1024 or file_bytes > 512 * 1024:
                        limited = True
                        break
                    if not (TRIAGE_FAILURE.search(line) or DISCOVERY_SIGNAL.search(line)) or (BENIGN.search(line) and not URGENT.search(line)) or redact(line) != line:
                        continue
                    identity = re.sub(r'^.*?\b(\d\d:\d\d:\d\d(?:\.\d+)?)\s*', '', line)
                    known_component = any(pattern.search(line) for pattern in TRIAGE_COMPONENTS.values())
                    for category in categories:
                        if category == 'unclassified':
                            if known_component or sum(row['path'] == str(path.relative_to(self.root)) for row in matches[category]) >= 2:
                                continue
                        elif not TRIAGE_COMPONENTS[category].search(line):
                            continue
                        duplicate = (category, identity)
                        if duplicate in seen:
                            continue
                        seen.add(duplicate)
                        matches[category].append({'path': str(path.relative_to(self.root)), 'line': number, 'text': line[:500],
                                                  'text_truncated': len(line) > 500, '_rank': int(bool(URGENT.search(line)))})
                        matches[category] = sorted(matches[category], key=lambda row: -row['_rank'])[:6 if category == 'unclassified' else 4]
            except OSError:
                unreadable += 1
            if consumed > 12 * 1024 * 1024:
                break
        for rows in matches.values():
            for row in rows:
                row.pop('_rank', None)
        result = {'focus': focus, 'findings': {key: rows for key, rows in matches.items() if rows},
                  'files_scanned': scanned, 'bytes_scanned': consumed, 'limited': limited, 'unreadable_files': unreadable,
                  'note': 'Candidates only. Unclassified leads are not diagnoses. Inspect surrounding lines, recovery, and competing explanations.'}
        self.scan = {key: result[key] for key in ('files_scanned', 'bytes_scanned', 'limited', 'unreadable_files')}
        return result

    def reopen_sources(self, sources):
        """Revalidate a few prior-turn citations against the current report's files."""
        excerpts, seen = [], set()
        if not isinstance(sources, list):
            return excerpts
        for source in sources[-8:]:
            if not isinstance(source, dict) or source.get('kind') != 'log':
                continue
            path = source.get('path')
            start, end = source.get('start'), source.get('end')
            if not isinstance(path, str) or len(path) > 500 or not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 1 or end < start:
                continue
            key = (path, start)
            if key in seen or len(excerpts) >= 6:
                continue
            seen.add(key)
            result = self.execute('read_log', {'path': path, 'start': start, 'count': min(11, end - start + 1)})
            if not result.get('error') and result.get('lines'):
                excerpts.append(result)
        self.reopened_sources = len(excerpts)
        return excerpts

    def prepare_nic_evidence(self, paths):
        """Open discovered inventory/update records even when no error keyword exists."""
        available = {str(path.relative_to(self.root)): path for path in paths}
        anchors, declared = {}, {}
        for section in ('network', 'nic_firmware'):
            data = self.sections.get(section) or {}
            if not isinstance(data, dict):
                continue
            for key in ('adapters', 'ports', 'events', 'log_sources'):
                for row in (data.get(key) or [])[:80]:
                    if not isinstance(row, dict):
                        continue
                    source = row.get('source')
                    if not isinstance(source, str) or source not in available:
                        continue
                    if section == 'nic_firmware':
                        declared[source] = row.get('origin') or source
                    number = row.get('line')
                    if isinstance(number, int) and not isinstance(number, bool) and number > 0:
                        anchors.setdefault(source, number)

        groups = {'NIC inventory': [], 'NIC update evidence': []}
        for relative, path in available.items():
            lower = relative.lower()
            name = path.name.lower()
            if name in ('dmdb_pci_dumper.txt', 'io_devices.txt'):
                groups['NIC inventory'].append(relative)
            elif (relative in declared or name in (
                    'flash_history.log', 'fm.log', 'mctp_trace.log', 'pldm.log',
                    'bmu_fwrpm.log', 'ibmu.log') or
                  re.fullmatch(r'(?:flash_history|fm|mctp_trace|pldm|bmu_fwrpm)\.log\.\d+', name) or
                  (name.startswith(('brcm-lnvgy_fw_nic_', 'brcm-lnvgy_fwutl_nic_')) and name.endswith('.log')) or
                  ('/var/log/lenovo_support/' in '/' + lower and name.endswith('.log'))):
                groups['NIC update evidence'].append(relative)
        # Round-robin categories so a large set of inventories cannot hide update logs.
        for rows in groups.values():
            rows.sort(key=lambda relative: (relative not in anchors, available[relative].stat().st_size, relative))
        ordered = []
        for index in range(max(map(len, groups.values()), default=0)):
            for category, rows in groups.items():
                if index < len(rows):
                    ordered.append((category, rows[index]))
        excerpts, consumed, limited = [], 0, len(ordered) > 6
        for category, relative in ordered[:6]:
            line = anchors.get(relative)
            if line is None:
                file_bytes, fallback = 0, None
                try:
                    for number, text, size in self.lines(available[relative]):
                        consumed += size
                        file_bytes += size
                        if consumed > 1024 * 1024 or file_bytes > 128 * 1024:
                            limited = True
                            break
                        if redact(text) != text:
                            continue
                        if NIC_IDENTITY.search(text):
                            line = number
                            break
                        if category == 'NIC update evidence' and fallback is None and NIC_UPDATE_SIGNAL.search(text):
                            fallback = number
                    line = line or fallback or 1
                except OSError:
                    continue
            excerpt = self.execute('read_log', {'path': relative, 'start': max(1, line - 3), 'count': 28})
            if not excerpt.get('error') and excerpt.get('lines'):
                excerpts.append({'category': category, 'origin': declared.get(relative, relative),
                                 'scope_note': 'Inventory is a snapshot; shared update logs need device association.',
                                 **excerpt})
        files = [{'category': category, 'path': relative, 'origin': declared.get(relative, relative)}
                 for category, relative in ordered[:20]]
        limitations = []
        if not groups['NIC inventory']:
            limitations.append('No V3/V4 NIC inventory text source was discovered in the available logs.')
        if not groups['NIC update evidence']:
            limitations.append('No NIC update evidence source was discovered; update outcome is unknown.')
        if limited:
            limitations.append('NIC evidence preparation is bounded; use listed source paths and read_log for further details.')
        return excerpts, {'files': files, 'files_available': len(ordered), 'limited': limited,
                          'bytes_scanned': consumed, 'limitations': limitations}

    def prepare(self, question):
        if not self.root or not self.root.is_dir():
            return {'available': False, 'note': 'No original FFDC text logs are available; use parsed report/JIRA evidence only.'}
        terms = [term for term in re.findall(r'[A-Za-z][A-Za-z0-9_.-]{2,}', str(question))
                 if term.lower() not in {'ffdc', 'bug', 'issue', 'what', 'which', 'analyze', 'analysis',
                                         'errors', 'error', 'problem', 'problems', 'logs', 'log', 'this',
                                         'there', 'show', 'find', 'check', 'about', 'please', 'system'}][:3]
        indexed = self.execute('search_evidence', {'terms': terms}) if terms else None
        catalog = self.execute('list_logs', {'offset': 0}) if not terms else None
        focuses = focus_for(question)
        triage = self.execute('triage_ffdc', {'focus': focuses[0] if len(focuses) == 1 else 'all'})
        if triage.get('error'):
            return triage
        paths = list(self.paths())
        domain_pack_evidence = self.domain_packs.analyze(
            self.root,
            paths,
            self.lines,
            question=question,
            redact_line=redact,
        )
        candidates = triage.get('findings', {})
        excerpts, seen = [], set()
        nic_evidence = None
        if 'network' in focuses or 'firmware' in focuses:
            excerpts, nic_evidence = self.prepare_nic_evidence(paths)
            seen.update((excerpt['path'], row['line']) for excerpt in excerpts for row in excerpt['lines'])
        for row in (indexed or {}).get('matches', [])[:3]:
            key = (row['path'], row['line'])
            if key in seen or len(excerpts) >= 8:
                continue
            seen.add(key)
            excerpt = self.execute('read_log', {'path': row['path'], 'start': max(1, row['line'] - 3), 'count': 11})
            if not excerpt.get('error'):
                excerpts.append({'category': 'indexed search', **excerpt})
        for category, rows in candidates.items():
            for row in rows[:2]:
                key = (row['path'], row['line'])
                if key in seen or len(excerpts) >= 8:
                    continue
                seen.add(key)
                excerpt = self.execute('read_log', {'path': row['path'], 'start': max(1, row['line'] - 3), 'count': 11})
                if not excerpt.get('error'):
                    excerpts.append({'category': category, **excerpt})
        for source in domain_pack_evidence.get('sources', []):
            self.add_source(source)
        index_summary = ({key: indexed.get(key) for key in ('index_available', 'limited', 'files_available',
                         'files_indexed', 'bytes_indexed', 'note')} | {'terms': terms}) if indexed else None
        return {'available': True, 'scan': self.scan, 'indexed_search': index_summary,
                'log_catalog': {'files': (catalog or {}).get('files', [])[:40],
                                'next_offset': (catalog or {}).get('next_offset')} if catalog else None,
                'excerpts': excerpts,
                'nic_evidence': nic_evidence,
                'domain_pack_evidence': domain_pack_evidence,
                'note': 'These surrounding log lines were read before answering. They may show recovery, normal empty slots, or old events.'}

    def unsupported_citations(self, answer):
        unsupported = []
        for match in re.finditer(r'`([^`\s]+):(\d+)(?:[-–](\d+))?`', answer):
            path, number, end = match.groups()
            if not any(row['kind'] == 'log' and row['path'] == path and row['start'] <= int(number) <= int(end or number) <= row['end'] for row in self.sources):
                unsupported.append(match.group(0)[1:-1])
        return unsupported

    def metadata(self):
        return {'sources': self.sources, 'scan': self.scan, 'tool_calls': len(self.audit),
                'reopened_sources': self.reopened_sources,
                'elapsed_seconds': round(time.monotonic() - self.started, 1)}
