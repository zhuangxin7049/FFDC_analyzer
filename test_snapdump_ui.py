"""Standalone SnapDump page integration and browser-contract checks."""

import json
import re
import shutil
import subprocess
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from snapdump_ui import VERSION, render_snapdump_page
from workspace_ui import WORKSPACE_NAV, render_workspace_page, workspace_page_identity


ROOT = Path(__file__).resolve().parent


class PageStructure(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.ids = []
        self.assets = []
        self.questions = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.append(attributes["id"])
        if tag == "script" and attributes.get("src"):
            self.assets.append(attributes["src"])
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.assets.append(attributes["href"])
        if "data-snapdump-question" in attributes:
            self.questions.append(attributes["data-snapdump-question"])


class SnapdumpPageTests(unittest.TestCase):
    def setUp(self):
        self.page = render_snapdump_page()
        self.structure = PageStructure(self.page)

    def test_navigation_order_and_active_page(self):
        self.assertEqual([item[0] for item in WORKSPACE_NAV], ["snapdump", "reports", "usage", "maintenance", "about"])
        self.assertEqual(workspace_page_identity("/snapdump?view=workspace"), ("snapdump", "SnapDump Analysis"))
        self.assertIn('href="/snapdump" data-workspace-nav="snapdump" class="active" aria-current="page"', self.page)
        self.assertEqual(self.page.count('aria-current="page"'), 1)
        self.assertIn('href="/snapdump"', render_workspace_page())

    def test_standalone_page_uses_one_workspace_shell_and_local_assets(self):
        self.assertEqual(self.page.count('class="workspace-subpage-shell"'), 1)
        self.assertEqual(self.page.count('<main'), 1)
        self.assertNotIn("iframe", self.page.lower())
        self.assertNotIn("8087", self.page)
        self.assertNotIn("knowledgebase.labs", self.page)
        self.assertNotIn("/static/workspace.js?", self.page)
        self.assertIn(f"/static/snapdump.js?v={VERSION}", self.structure.assets)
        self.assertIn(f"/static/snapdump.css?v={VERSION}", self.structure.assets)
        for asset in self.structure.assets:
            self.assertTrue(asset.startswith("/static/"), asset)
            self.assertTrue((ROOT / asset.split("?", 1)[0].lstrip("/")).is_file(), asset)

    def test_chat_stays_below_analysis_and_original_files(self):
        chat = self.page.index('class="snapdump-panel snapdump-chat"')
        for element in ("snapdump-summary-cards", "snapdump-checks", "snapdump-firmware", "snapdump-events", "snapdump-file-explorer", "snapdump-notes"):
            self.assertLess(self.page.index(f'id="{element}"'), chat)
        self.assertIn('maxlength="4000"', self.page)
        self.assertIn("Davy AI Q&amp;A", self.page)

    def test_extracted_script_has_all_required_elements(self):
        counts = Counter(self.structure.ids)
        self.assertFalse([key for key, count in counts.items() if count > 1])
        script = (ROOT / "static/snapdump.js").read_text()
        for element in set(re.findall(r'\$\("#([a-z-]+)"\)', script)):
            self.assertIn(element, counts, element)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("showAuth", script)
        self.assertNotIn("/api/login", script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for JavaScript checks")
    def test_standalone_script_syntax(self):
        subprocess.run([shutil.which("node"), "--check", str(ROOT / "static/snapdump.js")], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for JavaScript checks")
    def test_upload_chat_sources_retry_and_stale_response_contracts(self):
        fixture = json.dumps({"ids": self.structure.ids, "questions": self.structure.questions})
        harness = r'''
const fs = require('fs'); const vm = require('vm'); const assert = require('assert/strict');
const structure = JSON.parse(process.argv[1]);
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.value = ''; this.dataset = {}; this.events = {}; this.attrs = {}; this.className = ''; this._text = ''; this.innerHTML = ''; this.disabled = false; this.parent = null; this.style = {}; this.scrollHeight = 100; this.offsetTop = 0; }
  get classList() { return { add: c => { if (!this.className.split(' ').includes(c)) this.className += ' ' + c; }, remove: c => { this.className = this.className.split(' ').filter(v => v !== c).join(' '); }, contains: c => this.className.split(' ').includes(c) }; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  replaceChildren(...children) { this.children = []; this._text = ''; this.innerHTML = ''; this.append(...children); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
  querySelector(selector) { for (const child of this.children) { if (child.className.split(' ').includes(selector.slice(1))) return child; const result = child.querySelector(selector); if (result) return result; } return null; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(type, callback) { this.events[type] = callback; }
  focus() {} click() { this.events.click?.({target: this}); } scrollIntoView() { this.scrolled = true; }
}
const nodes = new Map(structure.ids.map(id => [id, new Element()]));
const get = id => nodes.get(id);
const questions = structure.questions.map(question => { const button = new Element('button'); button.dataset.snapdumpQuestion = question; return button; });
const requests = [];
const document = {
  querySelector: selector => selector.startsWith('#') ? get(selector.slice(1)) : get('snapdump-chat-messages').querySelector(selector),
  querySelectorAll: selector => selector === '[data-snapdump-question]' ? questions : [],
  createElement: tag => new Element(tag), createTextNode: text => { const element = new Element('#text'); element.textContent = text; return element; },
};
const context = { document, window: {addEventListener(){}}, AbortController, clearTimeout(){}, setTimeout(){}, FormData: class { constructor(){ this.fields = []; } append(...args){ this.fields.push(args); } }, fetch: (path, options) => new Promise(resolve => requests.push({path, options, resolve})) };
vm.createContext(context); vm.runInContext(fs.readFileSync('static/snapdump.js', 'utf8'), context);
const flush = () => new Promise(resolve => setImmediate(resolve));
const reply = (index, body, ok = true) => requests[index].resolve({ok, status: ok ? 200 : 503, headers: {get: () => ''}, text: async () => typeof body === 'string' ? body : JSON.stringify(body)});
const upload = () => { get('snapdump-file').events.change({target: {files: [{name: 'sample.zip', size: 1234}], value: ''}}); get('snapdump-analyze').click(); };
const ask = text => { get('snapdump-chat-question').value = text; get('snapdump-chat-form').events.submit({preventDefault(){}}); };
const legacy = {analysis_id: 'legacy-1', filename: 'legacy.zip', format: {id: 'megaraid_legacy', label: 'MegaRAID module format'}, snapshot: {ld_present: 1, ld_degraded: 1, ld_offline: 0, pd_disks: 2, pd_failed: 0, pd_predictive: 0, outstanding_io: 0, pending_io: 0}, logical_drives: [{id: '0', raid_level: '1', state: 'DEGRADED'}], file_urls: {'summary.txt': '/api/snapdump/file?id=legacy-1&name=summary.txt'}};
(async () => {
  assert(get('snapdump-analyze').disabled);
  upload(); assert.equal(requests[0].path, '/api/snapdump/analyze'); assert.equal(requests[0].options.body.fields[0][0], 'file');
  reply(0, legacy); await flush();
  assert(get('snapdump-summary-cards').innerHTML.includes('Logical drives'));
  assert(get('snapdump-summary-cards').innerHTML.includes('Physical disks'));
  assert(get('snapdump-summary-cards').innerHTML.includes('Failed: 0 · Predictive: 0'));
  assert(get('snapdump-firmware').innerHTML.includes('RAID 1 · DEGRADED'));
  assert(get('snapdump-firmware').innerHTML.includes('Not reported'));
  ask('What failed?'); assert.equal(requests[1].path, '/api/snapdump/ask'); assert.deepEqual(JSON.parse(requests[1].options.body), {analysis_id: 'legacy-1', question: 'What failed?', history: []});
  reply(1, {analysis_id: 'legacy-1', answer: 'Drive is **degraded** [S1].\n<script>untrusted</script>', sources: [{id: 'S1', name: 'summary.txt', start_line: 60003, end_line: 60005, excerpt: 'LD 0 DEGRADED'}]}); await flush();
  const answer = get('snapdump-chat-messages').children.at(-1); const supporting = answer.querySelector('.snapdump-chat-sources'); assert.equal(supporting.tagName, 'details'); assert(!supporting.attrs.open);
  const source = answer.querySelector('.snapdump-chat-source'); assert(source.textContent.includes('Lines 60003–60005')); assert(!source.attrs.open); assert(!answer.children.some(child => child.tagName === 'script'));
  source.children[2].click(); assert.equal(requests[2].path, legacy.file_urls['summary.txt']); assert(get('snapdump-file-explorer').scrolled); reply(2, 'padding\n'.repeat(60002) + 'LD 0 DEGRADED\nLD 1 OPTIMAL\nEND\n' + 'padding\n'.repeat(20)); await flush(); assert(get('snapdump-file-preview').textContent.includes('LD 0 DEGRADED')); assert(get('snapdump-file-preview').textContent.includes('[Original log lines 59993–60015]')); assert(get('snapdump-file-preview').textContent.length < 2000);
  ask('What next?'); assert.equal(JSON.parse(requests[3].options.body).history.length, 2); reply(3, {error: 'Temporary provider failure'}, false); await flush(); assert(!get('snapdump-chat-error').classList.contains('hidden'));
  const beforeRetry = get('snapdump-chat-messages').children.filter(child => child.className.endsWith(' user')).length;
  get('snapdump-chat-retry').click(); assert.equal(JSON.parse(requests[4].options.body).question, 'What next?');
  get('snapdump-chat-clear').click(); assert.equal(requests[4].options.signal.aborted, true); reply(4, {analysis_id: 'legacy-1', answer: 'STALE ANSWER', sources: []}); await flush(); assert(!get('snapdump-chat-messages').textContent.includes('STALE ANSWER')); assert.equal(beforeRetry, 2);
  let prevented = false; get('snapdump-chat-question').events.keydown({key: 'Enter', shiftKey: false, isComposing: true, keyCode: 229, currentTarget: get('snapdump-chat-question'), preventDefault(){ prevented = true; }}); assert(!prevented); assert.equal(requests.length, 5);
  upload(); reply(5, {analysis_id: 'mpi3-1', filename: 'mpi3.zip', format: {id: 'mpi3', label: 'MPI3 section format'}, snapshot: {mapped_slots: 3}, pcie: {max_speed_code: '10', max_width: 8}}); await flush();
  assert(get('snapdump-summary-cards').innerHTML.includes('PCIe capability')); assert(get('snapdump-summary-cards').innerHTML.includes('Mapped slots')); assert(!get('snapdump-summary-cards').innerHTML.includes('Logical drives'));
  assert.equal(get('snapdump-info-title').textContent, 'Firmware & link');
  ask('Follow-up on this file'); assert.equal(JSON.parse(requests[6].options.body).history.length, 0);
  get('snapdump-reset').click(); assert(requests[6].options.signal.aborted); reply(6, {analysis_id: 'mpi3-1', answer: 'OLD REPORT', sources: []}); await flush(); assert(!get('snapdump-chat-messages').textContent.includes('OLD REPORT')); assert(get('snapdump-result').classList.contains('hidden'));
  upload(); reply(7, {analysis_id: 'mpi3-raid', filename: 'mpi3-raid.zip', format: {id: 'mpi3'}, firmware: {mode_name: 'IOPI_FW_OPMODE_RAID'}, snapshot: {ld_present: 1, pd_disks: 12}}); await flush();
  assert(get('snapdump-summary-cards').innerHTML.includes('Logical drives')); assert(get('snapdump-summary-cards').innerHTML.includes('Physical disks')); assert.equal(get('snapdump-info-title').textContent, 'Controller & RAID');
  context.avengerFixture = {analysis_id: 'evp', filename: 'evp.zip', format: {id: 'mpi3'}, firmware: {}, snapshot: {ld_present: 1, pd_disks: 2}, operating_mode: {name: 'EVP', raid_counts_applicable: true, profile_id: '1'}, device_mapping: {devices: [{kind: 'disk', id_hex: '0x105', slot: 5, model: '<img src=x onerror=alert(1)>', sources: []}], ranges: [], limitation: 'Range candidates only'}, configuration: {regions: {}, pages: [], current_default_differences: []}, diagnostics: {observations: [], total_matches: 0, recommended_evidence: []}, intake: {unparsed_entries: [{name: '<script>.bin', bytes: 2, status: 'collected; not decoded'}]}};
  upload(); reply(8, context.avengerFixture); await flush();
  assert(get('snapdump-summary-cards').innerHTML.includes('Logical drives'));
  assert(!get('snapdump-firmware').innerHTML.includes('Correctable memory errors'));
  assert(get('snapdump-firmware').innerHTML.includes('EVP'));
  assert(get('snapdump-avenger').innerHTML.includes('&lt;img'));
  assert(!get('snapdump-avenger').innerHTML.includes('<img'));
  assert(get('snapdump-avenger').innerHTML.includes('&lt;script&gt;.bin'));
  assert(!get('snapdump-avenger-panel').classList.contains('hidden'));
  context.avengerFixture.controller_identity = {generation: 'AV2', chip_role: 'IOC', chip: 'SAS5032W', board: '460-16e HBA', board_tracer: 'SN1', limitation: 'Current snapshot identity', evidence: []};
  context.avengerFixture.host_functions = {functions: [{ioc_index: 0, role: 'Unverified', raw_fields: {BusNum: 35, DeviceFunc: 0}, sources: []}, {ioc_index: 1, role: 'Unverified', raw_fields: {}, sources: []}], summary: {mpi_functions_reported: 4}, generic_ioc_counters: [{raw: '1'}], limitation: 'Separate function and physical-card counts'};
  context.avengerFixture.device_mapping.devices[0].slot = 16;
  context.avengerFixture.device_mapping.devices[0].range_id_offset = 4;
  context.avengerFixture.operating_mode = {name: 'RAID', raid_counts_applicable: true, external_ddr_applicable: false};
  upload(); reply(9, context.avengerFixture); await flush();
  assert(get('snapdump-avenger').innerHTML.includes('SAS5032W'));
  assert(get('snapdump-avenger').innerHTML.includes('Host IOC functions · 2 observed instances'));
  assert(get('snapdump-avenger').innerHTML.includes('BusNum=0x23'));
  assert(get('snapdump-avenger').innerHTML.includes('offset 4'));
  assert(get('snapdump-avenger').innerHTML.includes('Enclosure / observed slot'));
  assert(!get('snapdump-firmware').innerHTML.includes('Correctable memory errors'));
  context.avengerFixture.operating_mode = {name: 'Unverified', raid_counts_applicable: false};
  context.avengerFixture.firmware.mode_name = 'IOPI_FW_OPMODE_RAID';
  upload(); reply(10, context.avengerFixture); await flush();
  assert(!get('snapdump-summary-cards').innerHTML.includes('Logical drives'));
  upload(); reply(11, {analysis_id: 'legacy-new', filename: 'legacy.zip', format: {id: 'megaraid_legacy'}}); await flush();
  assert(get('snapdump-avenger-panel').classList.contains('hidden'));
  assert.equal(get('snapdump-avenger').innerHTML, '');
  console.log('Standalone upload, both formats, safe answers, source navigation, history, retry, IME and stale-response checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run([shutil.which("node"), "-e", harness, fixture], cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertIn("checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
