/* Conversation state and safe Markdown rendering for the new workspace. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const messages = $('workspace-messages'), input = $('workspace-input');
  const fileInput = $('workspace-file'), composer = $('workspace-composer'), dropHint = $('workspace-drop-hint');
  let fileDragDepth = 0;
  const STORE = 'ffdcWorkspaceV3', RECENT = 'ffdcWorkspaceRecent';
  const maintenanceBanner = $('maintenance-banner');
  if (maintenanceBanner) {
    const hideAt = Number(maintenanceBanner.dataset.hideAt || 0);
    const hideMaintenance = () => {maintenanceBanner.hidden = true;};
    if (!hideAt || Date.now() >= hideAt) hideMaintenance();
    else setTimeout(hideMaintenance, Math.max(0, hideAt - Date.now()) + 100);
  }
  let state = {messages: [], report: null, reports: [], issue: null, analysis: null, pending: null, authoring: null};
  let controller = null, epoch = 0, busy = false, timer = null, stage = '', operationStart = 0;
  const icons = () => window.lucide?.createIcons();
  const chinese = text => /[\u3400-\u9fff]/.test(text || '');
  const wording = (zh, en, question = '') => chinese(question || state.messages.filter(m => m.role === 'user').at(-1)?.content) ? zh : en;
  const currentLanguage = () => {
    try {
      const selected = window.FFDCI18n?.language?.();
      if (selected === 'zh' || selected === 'en') return selected;
    } catch {}
    return document.documentElement.lang === 'zh-CN' ? 'zh' : 'en';
  };
  const defaultUploadQuestion = authoring => currentLanguage() === 'zh'
    ? (authoring ? '请分析附件中的参考文档，并帮助定义规则。' : '请分析这个 FFDC 并总结关键发现。')
    : (authoring ? 'Review the attached reference document and help define the rules.' : 'Analyze this FFDC and summarize the key findings.');
  const node = (tag, text = '', cls = '') => {const el = document.createElement(tag); if (text) el.textContent = text; if (cls) el.className = cls; return el;};
  const icon = name => {const el = node('i'); el.dataset.lucide = name; return el;};
  const validId = value => /^[A-Za-z0-9_-]+$/.test(String(value || ''));
  const keyIn = text => (String(text || '').match(/\b[A-Z][A-Z0-9_]*-\d+\b/i) || [''])[0].toUpperCase();
  const authorMention = text => String(text || '').match(/^\s*@\s*(NIC|UEFI|PSU|FPGA|BMC|XCC|Storage|Memory)\s+Agent\b/i);
  const safeUrl = value => {try {const url = new URL(value, location.origin); return ['https:', 'http:'].includes(url.protocol) ? url.href : null;} catch {return null;}};
  function load(store, key, fallback) {try {return JSON.parse(store.getItem(key)) || fallback;} catch {return fallback;}}
  function persist() {try {sessionStorage.setItem(STORE, JSON.stringify({...state, messages: state.messages.slice(-24), at: Date.now()}));} catch {}}
  function saveRecent(report) {
    if (!validId(report?.id)) return;
    const rows = recentRows().filter(row => row.id !== report.id);
    rows.unshift({id: report.id, title: report.file || report.id, type: 'file', href: '/report?id=' + encodeURIComponent(report.id) + '&view=workspace', at: Date.now()});
    try {localStorage.setItem(RECENT, JSON.stringify(rows.slice(0, 20)));} catch {}
    renderRecent();
  }
  function recentRows() {
    const rows = load(localStorage, RECENT, []);
    return (Array.isArray(rows) ? rows : []).filter(row => row && typeof row.title === 'string' && row.at >= Date.now() - 30 * 86400000).slice(0, 20);
  }
  function renderRecent() {
    const list = $('recent-list'); list.replaceChildren();
    const rows = recentRows(); $('clear-recent').disabled = !rows.length;
    if (!rows.length) list.append(node('div', 'No recent items', 'recent-empty'));
    for (const row of rows) {
      const button = node('button', '', 'recent-item'); button.type = 'button'; button.title = row.title;
      button.append(icon(row.type === 'bug' ? 'bug' : 'file-text'), node('span', row.title));
      button.addEventListener('click', async () => {
        if (busy) return;
        closePanels();
        if (row.type === 'bug') {input.value = row.title; input.focus(); resize(); return;}
        let id = row.id;
        if (!id) {try {id = new URL(row.href, location.origin).searchParams.get('id');} catch {}}
        if (!validId(id)) return;
        await runTask(async task => {
          setStage('Loading report');
          const data = await request('/api/workspace-report?id=' + encodeURIComponent(id), {}, task);
          state.messages = []; state.reports = [data.report]; setReport(data.report); state.pending = null; persist(); renderMessages();
        });
      });
      list.append(button);
    }
    icons();
  }

  // Marked handles Markdown structure. Tokens become DOM nodes; model HTML is never executed.
  function renderTokens(tokens, parent, inline = false, depth = 0) {
    if (depth > 20) return;
    for (const token of tokens || []) {
      let el;
      switch (token.type) {
        case 'space': continue;
        case 'heading': el = node('h3'); break;
        case 'paragraph': el = node('p'); break;
        case 'text':
          if (token.tokens) {renderTokens(token.tokens, parent, true, depth + 1); continue;}
          parent.append(document.createTextNode(token.text || '')); continue;
        case 'strong': el = node('strong'); break;
        case 'em': el = node('em'); break;
        case 'del': el = node('del'); break;
        case 'escape': parent.append(document.createTextNode(token.text || '')); continue;
        case 'codespan': parent.append(node('code', token.text)); continue;
        case 'code': el = node('pre'); el.append(node('code', token.text)); parent.append(el); continue;
        case 'br': parent.append(node('br')); continue;
        case 'hr': parent.append(node('hr')); continue;
        case 'blockquote': el = node('blockquote'); break;
        case 'link':
          el = node('a');
          if (safeUrl(token.href)) {el.href = safeUrl(token.href); el.target = '_blank'; el.rel = 'noopener noreferrer';}
          break;
        case 'image': parent.append(node('span', token.text || '')); continue;
        case 'list':
          el = node(token.ordered ? 'ol' : 'ul');
          if (token.ordered && token.start > 1) el.start = token.start;
          for (const item of token.items || []) {const li = node('li'); renderTokens(item.tokens, li, false, depth + 1); el.append(li);}
          parent.append(el); continue;
        case 'table':
          for (const [index, row] of token.rows.entries()) {
            const headers = token.header.map(h => h.text.replace(/[*`]/g, '').trim());
            let titleIndex = headers.findIndex(h => /^(risk|finding|issue|summary|component|ticket|风险|问题|发现|组件|摘要)$/i.test(h));
            if (titleIndex < 0) titleIndex = headers.findIndex(h => !/^(#|no\.?|序号)$/i.test(h));
            if (titleIndex < 0) titleIndex = 0;
            const section = node('div', '', 'finding-row'), title = node('h3');
            title.append(document.createTextNode((index + 1) + '. ')); renderTokens(row[titleIndex]?.tokens, title, true, depth + 1); section.append(title);
            const fields = node('dl');
            row.forEach((cell, position) => {if (position === titleIndex || /^(#|no\.?|序号)$/i.test(headers[position])) return; const value = node('dd'); renderTokens(cell.tokens, value, true, depth + 1); fields.append(node('dt', headers[position]), value);});
            section.append(fields); parent.append(section);
          }
          continue;
        default: parent.append(document.createTextNode(token.text || token.raw || '')); continue;
      }
      if (token.tokens) renderTokens(token.tokens, el, inline, depth + 1);
      else el.textContent = token.text || '';
      parent.append(el);
    }
  }
  function markdown(text, parent) {
    try {renderTokens(window.marked.lexer(String(text || ''), {gfm: true}), parent);} catch {parent.textContent = String(text || '');}
  }
  function sourceButton(source, reportId) {
    const label = source.kind === 'log' ? `${source.path}:${source.start}-${source.end}` : source.label || source.section || 'Source';
    const button = node('button', label, 'source-button'); button.type = 'button';
    button.addEventListener('click', () => openEvidence(source, reportId)); return button;
  }
  async function openEvidence(source, reportId) {
    const content = $('evidence-content'); content.replaceChildren(node('p', 'Loading evidence...'));
    if (!$('evidence-dialog').open) $('evidence-dialog').showModal();
    try {
      if (source.kind !== 'log' || !validId(reportId)) {
        content.replaceChildren(node('h3', source.label || source.section || 'Source'), node('p', source.description || 'Parsed report evidence. Open the full report for details.'));
        if (source.url && safeUrl(source.url)) {const link = node('a', 'Open source'); link.href = safeUrl(source.url); link.target = '_blank'; link.rel = 'noopener noreferrer'; content.append(link);}
        return;
      }
      const params = new URLSearchParams({id: reportId, path: source.path, start: String(source.start), count: String(Math.min(100, source.end - source.start + 1))});
      const response = await fetch('/api/workspace-evidence?' + params, {cache: 'no-store'});
      const data = await response.json(); if (!response.ok || data.error) throw new Error(data.error || 'Evidence unavailable');
      content.replaceChildren(node('h3', source.path), node('pre', data.lines.map(row => `${row.line}  ${row.text}`).join('\n')));
      if (data.file_exceeds_scan_limit) content.append(node('p', 'This is a bounded excerpt of the source log.', 'evidence-note'));
    } catch (error) {content.replaceChildren(node('p', error.message));}
  }
  async function copyText(text, button) {
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else {const area = node('textarea', text); area.style.position = 'fixed'; area.style.opacity = '0'; document.body.append(area); area.select(); document.execCommand('copy'); area.remove();}
      button.title = 'Copied'; button.replaceChildren(icon('check')); icons();
    } catch {button.title = 'Copy unavailable';}
  }
  function renderReportNotice(item, row) {
    if (item.mode === 'domain_authoring' || !validId(item.reportId)) return;
    const firstAnswer = state.messages.find(message => message.role === 'assistant' && message.mode !== 'domain_authoring' && message.reportId === item.reportId);
    if (firstAnswer !== item) return;
    const candidates = Array.isArray(item.reportLinks) ? item.reportLinks : [{id: item.reportId}];
    const seen = new Set(), reports = candidates.filter(report => {
      if (!report || !validId(report.id) || seen.has(report.id)) return false;
      seen.add(report.id); return true;
    });
    if (!reports.length) return;
    const notice = node('section', '', 'report-ready');
    const title = reports.length > 1 ? wording('分析报告已生成', 'Analysis reports generated', item.question) : wording('分析报告已生成', 'Analysis report generated', item.question);
    notice.setAttribute('aria-label', title);
    const heading = node('div', '', 'report-ready-heading'); heading.append(icon('circle-check'), node('span', title));
    const links = node('div', '', 'report-ready-links');
    for (const report of reports) {
      const link = node('a', '', 'report-ready-link');
      link.href = '/report?id=' + encodeURIComponent(report.id) + '&view=workspace'; link.target = '_blank'; link.rel = 'noopener noreferrer';
      const text = node('span', '', 'report-ready-link-text');
      text.append(node('span', wording('打开完整分析报告', 'Open full analysis report', item.question), 'report-ready-link-label'));
      if (typeof report.file === 'string' && report.file) text.append(node('span', report.file, 'report-ready-file'));
      link.append(text, icon('arrow-up-right')); links.append(link);
    }
    notice.append(heading, links); row.append(notice);
  }
  function renderMessage(item) {
    const row = node('article', '', 'workspace-msg ' + item.role), body = node('div', '', 'workspace-msg-body');
    if (item.role === 'assistant') {const label = node('div', '', 'assistant-label'); label.append(icon(item.mode === 'domain_authoring' ? 'file-pen-line' : 'sparkles'), node('span', item.mode === 'domain_authoring' ? 'Rule authoring' : 'Analysis')); row.append(label); markdown(item.content, body);} else body.textContent = item.content;
    row.append(body);
    if (item.role === 'assistant') {
      renderReportNotice(item, row);
      if (item.analysis?.sources?.length) {const details = node('details', '', 'message-evidence'); details.append(node('summary', wording('查看已读取的证据', 'Evidence read', item.question) + ` (${item.analysis.sources.length})`)); for (const source of item.analysis.sources) details.append(sourceButton(source, item.reportId)); row.append(details);}
      const footer = node('div', '', 'message-footer'), copy = node('button', '', 'icon-button'); copy.type = 'button'; copy.title = 'Copy response'; copy.setAttribute('aria-label', 'Copy response'); copy.append(icon('copy')); copy.addEventListener('click', () => copyText(item.content, copy));
      footer.append(copy, node('span', [item.model, item.analysis?.elapsed_seconds != null ? `${item.analysis.elapsed_seconds}s` : ''].filter(Boolean).join(' · '))); row.append(footer);
      if (item.draft) {
        const download = node('button', '', 'icon-button'); download.type = 'button'; download.title = 'Download draft JSON'; download.setAttribute('aria-label', download.title); download.append(icon('download'));
        download.addEventListener('click', () => {
          const metadata = item.authoring || {};
          const url = URL.createObjectURL(new Blob([JSON.stringify({status: 'draft', tested: false, published: false,
            created_by: metadata.created_by || null, updated_by: metadata.updated_by || null, pack: item.draft}, null, 2)], {type: 'application/json'}));
          const link = node('a'); link.href = url; link.download = 'domain-pack-draft.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        });
        footer.append(download);
      }
    }
    messages.append(row); return row;
  }
  function renderMessages() {
    messages.replaceChildren();
    if (!state.messages.length) {
      const welcome = node('div', '', 'welcome'); welcome.id = 'welcome'; const symbol = node('div', '', 'welcome-symbol'); symbol.append(icon('scan-line')); welcome.append(symbol, node('h2', state.report ? 'Continue this investigation' : 'What would you like to investigate?'));
      const actions = node('div', '', 'quick-actions');
      const examples = state.report ? [['Key findings', 'What are the key findings?'], ['Raw evidence', 'List the relevant raw log evidence and line numbers'], ['Network status', 'What network adapter issues are present in this FFDC?']] : [['Analyze a Bug', 'Analyze IOSS-'], ['Project Milestones', 'What are the latest project milestones?']];
      for (const [label, question] of examples) {const button = node('button', label, 'quick-action'); button.type = 'button'; button.addEventListener('click', () => {input.value = question; input.focus(); resize();}); actions.append(button);} welcome.append(actions); messages.append(welcome);
    } else for (const item of state.messages) renderMessage(item);
    icons(); messages.scrollTop = messages.scrollHeight;
  }
  function append(item) {state.messages.push(item); state.messages = state.messages.slice(-24); persist(); $('welcome')?.remove(); const row = renderMessage(item); icons(); messages.scrollTop = messages.scrollHeight; return row;}
  function setReport(report, issue = null) {
    state.report = report || null; state.issue = issue || report?.issue || null; state.analysis = null;
    if (Array.isArray(report?.related_reports) && report.related_reports.length) {
      state.reports = report.related_reports.map(item => ({...item, file: item.file || item.attachment || item.id}));
    } else if (report?.id && !state.reports.some(item => item.id === report.id)) {
      state.reports = [{id: report.id, file: report.file || report.id}];
    }
    if (report) saveRecent(report); persist(); renderContext();
  }
  function ensureAnalysisReportList() {
    let section = $('analysis-report-section'), count = $('analysis-report-count'), list = $('analysis-report-list');
    if (section && count && list) return {section, count, list};
    const contextData = $('context-data');
    if (!contextData) return {section: null, count: null, list: null};
    section = node('section', '', 'analysis-report-section'); section.id = 'analysis-report-section'; section.hidden = true;
    const heading = node('div', '', 'analysis-report-heading'); heading.append(node('h3', 'FFDC Analysis Report List'));
    count = node('span', '0'); count.id = 'analysis-report-count'; heading.append(count);
    list = node('div', '', 'analysis-report-list'); list.id = 'analysis-report-list'; section.append(heading, list);
    contextData.insertBefore(section, contextData.querySelector('.evidence-panel'));
    return {section, count, list};
  }
  function renderContext() {
    const report = state.report, issue = state.issue;
    $('context-empty').hidden = !!(report || issue); $('context-data').hidden = !(report || issue);
    $('chat-context').textContent = report ? (issue?.key ? issue.key + ' · ' : '') + report.file : issue?.key || 'New conversation';
    $('composer-scope').textContent = report?.file || issue?.key || 'No report selected';
    $('context-bug').replaceChildren();
    if (issue?.key) {const link = node('a', issue.key); link.href = 'https://jira1.labs.lenovo.com/browse/' + encodeURIComponent(issue.key); link.target = '_blank'; link.rel = 'noopener noreferrer'; $('context-bug').append(link);} else $('context-bug').textContent = 'Not linked';
    $('context-status').textContent = issue?.status || '—'; $('context-engineer').textContent = issue?.engineer || '—'; $('context-file').textContent = report?.file || '—'; $('context-created').textContent = report?.created_at || '—';
    const select = $('report-selector'); select.replaceChildren();
    for (const item of state.reports) {const option = node('option', item.file || item.attachment || item.id); option.value = item.id; option.selected = item.id === report?.id; select.append(option);}
    const reportRows = state.reports.length ? state.reports : (report?.id ? [{id: report.id, file: report.file || report.id}] : []);
    const reportElements = ensureAnalysisReportList(), reportSection = reportElements.section, reportList = reportElements.list;
    if (!reportSection || !reportList || !reportElements.count) return;
    reportSection.hidden = !reportRows.length; reportElements.count.textContent = String(reportRows.length); reportList.replaceChildren();
    for (const item of reportRows) {
      if (!validId(item.id)) continue;
      const link = node('a', '', 'analysis-report-item' + (item.id === report?.id ? ' active' : ''));
      link.href = '/report?id=' + encodeURIComponent(item.id) + '&view=workspace'; link.target = '_blank'; link.rel = 'noopener noreferrer';
      const label = node('span', item.file || item.attachment || item.id, 'analysis-report-name');
      link.append(icon('file-text'), label, icon('arrow-up-right')); reportList.append(link);
    }
    const sources = state.analysis?.sources || []; $('evidence-count').textContent = sources.length; $('evidence-sources').replaceChildren();
    for (const source of sources) $('evidence-sources').append(sourceButton(source, report?.id));
    if (!sources.length) $('evidence-sources').append(node('p', 'No source excerpts read yet.', 'evidence-empty'));
    $('model-meta').textContent = state.analysis ? `${state.analysis.model || ''}${state.analysis.elapsed_seconds != null ? ' · ' + state.analysis.elapsed_seconds + 's' : ''}` : '';
    if (state.analysis?.scan?.limited) $('evidence-sources').append(node('p', wording('日志扫描有范围限制，未覆盖全部文件。', 'The bounded scan did not cover all log content.'), 'evidence-note'));
    const author = state.authoring;
    $('authoring-bar').hidden = !author;
    $('authoring-status').textContent = author ? `${author.display_name || author.domain.toUpperCase()} · ${author.revision ? 'Draft r' + author.revision : 'Collecting knowledge'} · Not published${author.updated_by ? ' · by ' + author.updated_by : ''}` : '';
    $('exit-authoring').disabled = busy;
    $('attach-button').disabled = busy;
    $('attach-button').title = author ? 'Attach reference document' : 'Attach FFDC';
    $('attach-button').setAttribute('aria-label', author ? 'Attach reference document' : 'Attach FFDC');
    $('workspace-file').accept = author ? '.pdf,.docx,.pptx,.txt,.md,.markdown,.csv,.json,.xml,.html,.htm' : '.tzz,.tar,.tar.zst,.tzst,.tgz,.gz,.log,.trace,.out,.journal,.dmesg';
    input.placeholder = author ? 'Describe the rule or attach a reference document...' : 'Ask a question, enter a Bug ID, or attach an FFDC...';
    if (author) {
      $('chat-context').textContent = (author.display_name || author.domain.toUpperCase()) + ' rule authoring';
      $('composer-scope').textContent = 'Rule draft';
    }
  }
  function resize() {input.style.height = 'auto'; input.style.height = Math.min(144, Math.max(52, input.scrollHeight)) + 'px';}
  function updateAttachment() {
    const file = fileInput.files[0]; $('file-chip').hidden = !file; $('file-chip-name').textContent = file?.name || '';
  }
  function isFileDrag(event) {
    const transfer = event.dataTransfer;
    return Array.from(transfer?.types || []).includes('Files') || Array.from(transfer?.items || []).some(item => item.kind === 'file') || !!transfer?.files?.length;
  }
  function showFileDrop() {
    composer.classList.toggle('file-drag-over', !busy);
    dropHint.textContent = busy ? wording('当前任务运行中，请完成或停止后再添加文件。', 'Wait for the current task to finish or stop it before attaching a file.') : wording('松开以添加一个文件', 'Drop one file to attach');
    dropHint.hidden = false;
  }
  function clearFileDrop() {fileDragDepth = 0; composer.classList.remove('file-drag-over'); dropHint.hidden = true;}
  function attachDroppedFile(event) {
    const transfer = event.dataTransfer, files = Array.from(transfer?.files || []);
    if (busy) {showError(new Error(wording('当前任务运行中，请完成或停止后再添加文件。', 'Wait for the current task to finish or stop it before attaching a file.'))); return;}
    if (files.length !== 1) {showError(new Error(wording('请每次拖入一个文件。', 'Please drop one file at a time.'))); return;}
    const accepted = fileInput.accept.toLowerCase().split(',').map(value => value.trim()).filter(Boolean);
    const standaloneTextLog = /\.(?:log|txt|trace|out|journal|dmesg)(?:\.\d+)?$/i.test(files[0].name) || files[0].type.toLowerCase().startsWith('text/');
    if (accepted.length && !accepted.some(suffix => files[0].name.toLowerCase().endsWith(suffix)) && !(accepted.includes('text/*') && standaloneTextLog)) {
      showError(new Error(wording('不支持此文件类型。支持的类型：', 'Unsupported file type. Supported types: ') + fileInput.accept)); return;
    }
    try {
      fileInput.files = transfer.files;
      fileInput.dispatchEvent(new Event('change', {bubbles: true}));
      input.focus();
    } catch {showError(new Error(wording('浏览器无法添加拖入的文件，请使用附件按钮选择文件。', 'The browser could not attach this file. Use the attachment button to choose it.')));}
  }
  const jiraPassword = $('jira-login-dialog')?.querySelector('[name="password"]');
  const jiraPasswordToggle = $('toggle-jira-password');
  function resetJiraPasswordVisibility() {
    if (!jiraPassword || !jiraPasswordToggle) return;
    jiraPassword.type = 'password';
    jiraPasswordToggle.replaceChildren(icon('eye'));
    jiraPasswordToggle.setAttribute('aria-label', 'Show password');
    jiraPasswordToggle.title = 'Show password';
    icons();
  }
  jiraPasswordToggle?.addEventListener('click', () => {
    const visible = jiraPassword.type === 'password';
    jiraPassword.type = visible ? 'text' : 'password';
    jiraPasswordToggle.replaceChildren(icon(visible ? 'eye-off' : 'eye'));
    jiraPasswordToggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
    jiraPasswordToggle.title = visible ? 'Hide password' : 'Show password';
    icons();
  });
  function closePanels() {$('workspace-sidebar').classList.remove('open'); $('workspace-context').classList.remove('open'); $('drawer-backdrop').hidden = true; $('toggle-sidebar').setAttribute('aria-expanded', 'false'); $('toggle-context').setAttribute('aria-expanded', String(innerWidth > 1250 && !$('workspace-context').classList.contains('closed')));}
  function toggleContext() {
    if (innerWidth > 1250) {const hidden = $('workspace-context').classList.toggle('closed'); document.querySelector('.workspace-shell').classList.toggle('details-closed', hidden); $('toggle-context').setAttribute('aria-expanded', String(!hidden));}
    else {const open = !$('workspace-context').classList.contains('open'); closePanels(); $('workspace-context').classList.toggle('open', open); $('workspace-context').classList.remove('closed'); $('drawer-backdrop').hidden = !open; $('toggle-context').setAttribute('aria-expanded', String(open));}
  }
  function setStage(value) {stage = value; updateElapsed();}
  function updateElapsed() {$('operation-status').replaceChildren(node('span', stage), node('span', Math.floor((Date.now() - operationStart) / 1000) + 's'));}
  function ensure(task) {if (task !== epoch || controller?.signal.aborted) throw new DOMException('Aborted', 'AbortError');}
  async function request(url, options = {}, task = epoch) {
    ensure(task);
    const response = await fetch(url, {...options, signal: controller.signal, cache: 'no-store'});
    let data; try {data = await response.json();} catch {throw new Error(wording('服务暂未返回有效结果，请重试。', 'The service returned an invalid response. Please retry.'));}
    ensure(task); if (!response.ok || data.error) {const failure = new Error(data.error || `HTTP ${response.status}`); failure.status = response.status; failure.requiresAuthoringLogin = !!data.requires_authoring_login; throw failure;} return data;
  }
  const post = (url, payload, task) => request(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}, task);
  async function ensureJiraAuth(question, task, purpose = 'jira') {
    const dialog = document.getElementById('jira-login-dialog');
    const form = dialog.querySelector('form');
    const error = dialog.querySelector('[role="alert"]');
    const submit = form.querySelector('[type="submit"]');
    const title = dialog.querySelector('h2');
    const description = dialog.querySelector('form > p');
    const originalTitle = title.textContent, originalDescription = description.textContent;
    if (purpose === 'authoring') {
      title.textContent = 'Sign in to Rule Authoring';
      description.textContent = 'Use your own JIRA account to verify your identity. Your password is discarded immediately after verification and is never stored in the rule-authoring session or draft.';
    }
    await new Promise((resolve, reject) => {
      const signal = controller.signal;
      const finish = (reason) => {
        form.reset(); resetJiraPasswordVisibility(); error.textContent = ''; submit.disabled = false;
        form.removeEventListener('submit', login);
        dialog.removeEventListener('cancel', cancel);
        dialog.querySelector('[data-cancel]').removeEventListener('click', cancel);
        signal.removeEventListener('abort', cancel);
        dialog.close();
        title.textContent = originalTitle; description.textContent = originalDescription;
        reason ? reject(reason) : resolve();
      };
      const cancel = (event) => {
        event.preventDefault();
        finish(new Error(wording('已取消 JIRA 登录。', 'JIRA login cancelled.')));
      };
      const login = async (event) => {
        event.preventDefault(); submit.disabled = true; error.textContent = '';
        try {
          const pending = post(purpose === 'authoring' ? '/workspace-author-login' : '/workspace-jira-login', {
            username: form.elements.username.value.trim(),
            password: form.elements.password.value, issue: keyIn(question)
          }, task);
          form.elements.password.value = '';
          await pending;
          finish();
        } catch (failure) {
          error.textContent = failure.message; submit.disabled = false;
        }
      };
      form.addEventListener('submit', login);
      dialog.addEventListener('cancel', cancel);
      dialog.querySelector('[data-cancel]').addEventListener('click', cancel);
      signal.addEventListener('abort', cancel, {once: true});
      form.reset(); resetJiraPasswordVisibility(); error.textContent = ''; dialog.showModal();
      form.elements.username.focus();
    });
  }
  const pause = () => new Promise(resolve => setTimeout(resolve, 900));
  function historyFor(reportId) {return state.messages.filter(m => m.mode !== 'domain_authoring' && ['user', 'assistant'].includes(m.role) && (m.reportId || null) === (reportId || null)).slice(-8).map(({role, content}) => ({role, content: content.slice(0, 10000)}));}
  function evidenceFor(reportId) {
    const sources = state.messages.filter(m => m.role === 'assistant' && m.reportId === reportId).slice(-2).flatMap(m => {
      const verified = (Array.isArray(m.analysis?.sources) ? m.analysis.sources : []).filter(s => s?.kind === 'log');
      const cited = [...String(m.content || '').matchAll(/`([^`\s]+):(\d+)(?:[-–]\d+)?`/g)].flatMap(match => {
        const line = Number(match[2]);
        return verified.filter(s => s.path === match[1] && line >= s.start && line <= s.end).map(s => ({kind: 'log', path: s.path, start: Math.max(s.start, line - 3), end: Math.min(s.end, line + 7)}));
      });
      return cited.length ? cited : verified;
    });
    const seen = new Set();
    return sources.filter(s => s.kind === 'log' && typeof s.path === 'string' && Number.isInteger(s.start) && Number.isInteger(s.end)).map(s => ({kind: 'log', path: s.path, start: s.start, end: s.end})).filter(s => {
      const key = `${s.path}:${s.start}`;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).slice(-6);
  }
  function showError(error, retry) {
    const text = error.name === 'AbortError' ? wording('已停止等待。后台解析可能仍在继续。', 'Stopped waiting. Background parsing may still be running.') : error.message;
    const row = node('div', '', 'workspace-msg error'); row.append(node('div', text));
    if (retry) {const button = node('button', wording('重试', 'Retry'), 'quick-action'); button.type = 'button'; button.addEventListener('click', () => {row.remove(); retry();}); row.append(button);}
    messages.append(row); messages.scrollTop = messages.scrollHeight;
  }
  async function runTask(action, retry = null) {
    if (busy) return; busy = true; const task = ++epoch; controller = new AbortController(); operationStart = Date.now();
    $('workspace-send').disabled = true; $('attach-button').disabled = true; $('report-selector').disabled = true; $('workspace-stop').hidden = false; $('operation-status').hidden = false;
    timer = setInterval(updateElapsed, 1000);
    const taskController = controller;
    const watchdog = setTimeout(() => taskController.abort(), 12 * 60 * 1000);
    try {await action(task);} catch (error) {if (task === epoch) showError(error, retry);} finally {
      clearTimeout(watchdog);
      if (task === epoch) {busy = false; clearInterval(timer); $('workspace-send').disabled = false; $('attach-button').disabled = false; $('exit-authoring').disabled = false; $('report-selector').disabled = false; $('workspace-stop').hidden = true; $('operation-status').hidden = true; input.focus(); renderContext();}
    }
  }
  function acceptAnswer(data, question) {
    if (data.authoring) {
      state.authoring = {domain: data.authoring.domain, display_name: data.authoring.display_name, token: data.authoring.token,
        revision: data.authoring.revision, created_by: data.authoring.created_by, updated_by: data.authoring.updated_by};
      state.pending = null;
      append({role: 'assistant', content: data.answer, model: data.model, mode: 'domain_authoring', draft: data.authoring.pack, authoring: data.authoring, question, reportId: null});
      renderContext(); persist(); return;
    }
    if (data.report) setReport(data.report, data.issue || state.issue);
    if (data.issue) state.issue = data.issue;
    const latestUser = state.messages.filter(item => item.role === 'user').at(-1);
    if (latestUser && data.report) latestUser.reportId = data.report.id;
    if (!data.answer?.trim()) throw new Error(wording('模型未返回分析内容，请重试。', 'The model returned no answer. Please retry.', question));
    state.analysis = {...data.analysis, model: data.model}; state.pending = null;
    const reportLinks = state.report ? [state.report, ...state.reports].filter(report => report && validId(report.id)).map(report => ({id: report.id, file: report.file || report.attachment || ''})) : [];
    append({role: 'assistant', content: data.answer, model: data.model, analysis: state.analysis, reportId: state.report?.id || null, reportLinks, question});
    renderContext(); persist();
  }
  async function answerReport(question, task) {
    setStage(wording('正在核对报告与原始日志', 'Reviewing report and original evidence', question));
    state.pending = {kind: 'answer', question, reportId: state.report.id}; persist();
    let data = await post('/workspace-report-chat', {id: state.report.id, message: question, history: historyFor(state.report.id), previous_sources: evidenceFor(state.report.id)}, task);
    if (data.analysis?.requires_jira_login) {
      await ensureJiraAuth(question, task);
      data = await post('/workspace-report-chat', {id: state.report.id, message: question, history: historyFor(state.report.id), previous_sources: evidenceFor(state.report.id)}, task);
    }
    if (data.analysis?.requires_jira_login) throw new Error('JIRA access is unavailable. Please retry with an authorized account.');
    acceptAnswer(data, question);
  }
  async function waitForJob(pending, task) {
    const route = pending.kind === 'upload' ? '/api/workspace-upload-job' : '/api/jira-job';
    for (;;) {
      const job = await request(route + '?id=' + encodeURIComponent(pending.jobId), {}, task);
      setStage((job.message || 'Analyzing') + ' · ' + Math.round(job.percent || 0) + '%');
      if (job.status === 'done') {
        const reports = job.report ? [job.report] : (job.reports || []).map(row => ({...row, file: row.file || row.attachment}));
        if (!reports[0]?.id) throw new Error(wording('任务完成，但没有返回报告。', 'The job completed without a report.', pending.question));
        const details = await request('/api/workspace-report?id=' + encodeURIComponent(reports[0].id), {}, task);
        state.reports = reports; setReport(details.report); state.pending = {kind: 'answer', question: pending.question, reportId: state.report.id}; persist();
        const latestUser = state.messages.filter(item => item.role === 'user').at(-1);
        if (latestUser) latestUser.reportId = state.report.id;
        // The original upload/Bug question is answered here without navigating away.
        await answerReport(pending.question, task); return;
      }
      if (job.status === 'error') throw new Error(job.message || 'Analysis failed');
      await pause(); ensure(task);
    }
  }
  async function ask(question, attachment = null, retry = false) {
    if (busy || !question.trim()) return;
    if (state.authoring && /^(\/exit|退出规则编写|退出规则模式)$/i.test(question.trim())) {exitAuthoring(); return;}
    const mention = authorMention(question);
    if (mention || state.authoring) {
      const domain = mention ? (mention[1].toLowerCase() === 'xcc' ? 'bmc' : mention[1].toLowerCase()) : state.authoring.domain;
      if (!retry && mention) state.authoring = {domain, token: null, revision: 0};
      if (!retry) append({role: 'user', content: question, reportId: null, mode: 'domain_authoring'});
      renderContext();
      await runTask(async task => {
        $('exit-authoring').disabled = true;
        setStage(wording('正在编写规则草案', 'Preparing rule draft', question));
        state.pending = {kind: 'authoring', question}; persist();
        const sendAuthoring = async token => {
          if (attachment) {
            const form = new FormData(); form.append('message', question); form.append('domain', domain); form.append('token', token || ''); form.append('document', attachment, attachment.name);
            return request('/workspace-domain-author', {method: 'POST', body: form}, task);
          }
          return post('/workspace-domain-author', {message: question, domain, token: token || null}, task);
        };
        let data;
        try {data = await sendAuthoring(state.authoring?.token);} catch (error) {
          if (error.requiresAuthoringLogin || error.status === 401) {
            await ensureJiraAuth(question, task, 'authoring');
            data = await sendAuthoring(state.authoring?.token);
          } else if (!mention && /session expired/i.test(error.message || '')) {
            state.authoring = {domain, token: null, revision: 0}; persist();
            data = await sendAuthoring(null);
          } else throw error;
        }
        acceptAnswer(data, question);
      }, () => ask(question, null, true));
      return;
    }
    const previousPending = retry ? state.pending : null;
    const requestedKey = keyIn(question);
    if (!retry && (attachment || (requestedKey && requestedKey !== state.issue?.key))) {state.report = null; state.issue = null; state.reports = []; state.analysis = null; renderContext();}
    const scope = state.report?.id || null;
    if (!retry) append({role: 'user', content: question + (attachment ? '\n' + attachment.name : ''), reportId: scope});
    await runTask(async task => {
      if (previousPending?.jobId) {await waitForJob(previousPending, task); return;}
      if (attachment && !state.report) {
        setStage(wording('正在上传 FFDC', 'Uploading FFDC', question));
        const form = new FormData(); form.append('ffdc', attachment, attachment.name);
        const data = await request('/workspace-upload-start', {method: 'POST', body: form}, task);
        state.pending = {kind: 'upload', jobId: data.job_id, question}; persist(); await waitForJob(state.pending, task); return;
      }
      if (state.report) {await answerReport(question, task); return;}
      setStage(wording('正在查询 Bug 与项目资料', 'Checking Bug and project evidence', question));
      state.pending = {kind: 'answer', question, reportId: null}; persist();
      let data = await post('/workspace-chat', {message: question, history: historyFor(null)}, task);
      if (data.analysis?.requires_jira_login) {
        await ensureJiraAuth(question, task);
        data = await post('/workspace-chat', {message: question, history: historyFor(null)}, task);
      }
      if (data.analysis?.requires_jira_login) throw new Error('JIRA access is unavailable. Please retry with an authorized account.');
      if (data.issue) {state.issue = data.issue; renderContext();}
      if (data.ffdc_job_id) {state.pending = {kind: 'jira', jobId: data.ffdc_job_id, question}; persist(); await waitForJob(state.pending, task);} else acceptAnswer(data, question);
    }, () => ask(question, attachment, true));
  }
  function reset() {
    ++epoch; controller?.abort(); busy = false; clearInterval(timer); state = {messages: [], report: null, reports: [], issue: null, analysis: null, pending: null, authoring: null};
    clearFileDrop();
    input.value = ''; $('workspace-file').value = ''; $('file-chip').hidden = true; $('workspace-send').disabled = false; $('attach-button').disabled = false; $('report-selector').disabled = false; $('workspace-stop').hidden = true; $('operation-status').hidden = true;
    persist(); renderMessages(); renderContext(); closePanels(); resize(); input.focus();
  }
  function exitAuthoring() {
    if (busy) return;
    state.authoring = null; state.pending = null; persist(); renderContext(); input.focus();
  }
  async function restore() {
    const saved = load(sessionStorage, STORE, null);
    if (saved && saved.at > Date.now() - 30 * 86400000 && Array.isArray(saved.messages)) {
      state = {...state, ...saved, messages: saved.messages.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.content === 'string').slice(-24), reports: Array.isArray(saved.reports) ? saved.reports : []};
    } else {
      const legacy = load(sessionStorage, 'ffdcWorkspaceChat', []);
      if (Array.isArray(legacy)) state.messages = legacy.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.content === 'string').slice(-24);
    }
    renderMessages(); renderContext(); renderRecent(); resize();
    if (state.report?.id && !state.pending?.jobId) {
      await runTask(async task => {
        setStage('Restoring report context');
        try {const data = await request('/api/workspace-report?id=' + encodeURIComponent(state.report.id), {}, task); state.report = data.report; renderContext(); persist();}
        catch (error) {if (error.name === 'AbortError') throw error; state.report = null; state.issue = null; state.analysis = null; state.reports = []; renderContext(); persist(); throw error;}
      });
    }
    if (state.pending?.jobId) {const pending = state.pending; await runTask(task => waitForJob(pending, task), () => ask(pending.question, null, true));}
    else if (state.pending?.question) {const pending = state.pending; showError(new Error(wording('上次回复未完成，可以继续重试。', 'The previous response was interrupted. You can retry.', pending.question)), () => ask(pending.question, null, true));}
  }
  $('workspace-composer').addEventListener('submit', event => {
    event.preventDefault(); if (busy) return; const attachment = $('workspace-file').files[0] || null; const question = input.value.trim() || (attachment ? defaultUploadQuestion(!!state.authoring) : ''); if (!question) return;
    input.value = ''; resize(); $('workspace-file').value = ''; $('file-chip').hidden = true; ask(question, attachment);
  });
  input.addEventListener('input', resize); input.addEventListener('keydown', event => {if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault(); $('workspace-composer').requestSubmit();}});
  $('attach-button').addEventListener('click', () => $('workspace-file').click());
  fileInput.addEventListener('change', updateAttachment);
  $('file-remove').addEventListener('click', () => {$('workspace-file').value = ''; $('file-chip').hidden = true;});
  // Files dropped anywhere on the page must never trigger browser navigation.
  // Keep ordinary text/URL drags available to the message editor.
  document.addEventListener('dragenter', event => {
    if (!isFileDrag(event)) return;
    event.preventDefault(); ++fileDragDepth; showFileDrop();
  });
  document.addEventListener('dragover', event => {
    if (!isFileDrag(event)) return;
    event.preventDefault(); event.dataTransfer.dropEffect = busy ? 'none' : 'copy';
    fileDragDepth = Math.max(1, fileDragDepth); showFileDrop();
  });
  document.addEventListener('dragleave', event => {
    if (!fileDragDepth) return;
    --fileDragDepth;
    if (!fileDragDepth || (event.target === document.documentElement && !event.relatedTarget)) clearFileDrop();
  });
  document.addEventListener('drop', event => {
    const fileDrop = isFileDrag(event); clearFileDrop();
    if (!fileDrop) return;
    event.preventDefault(); attachDroppedFile(event);
  });
  document.addEventListener('dragend', clearFileDrop);
  window.addEventListener('blur', clearFileDrop);
  $('workspace-stop').addEventListener('click', () => controller?.abort()); $('new-analysis').addEventListener('click', reset);
  $('exit-authoring').addEventListener('click', exitAuthoring);
  $('clear-recent').addEventListener('click', () => {localStorage.removeItem(RECENT); renderRecent();});
  $('toggle-context').addEventListener('click', toggleContext); $('close-context').addEventListener('click', closePanels); $('drawer-backdrop').addEventListener('click', closePanels);
  $('toggle-sidebar').addEventListener('click', () => {const open = !$('workspace-sidebar').classList.contains('open'); closePanels(); $('workspace-sidebar').classList.toggle('open', open); $('drawer-backdrop').hidden = !open; $('toggle-sidebar').setAttribute('aria-expanded', String(open));});
  $('close-evidence').addEventListener('click', () => $('evidence-dialog').close());
  $('report-selector').addEventListener('change', () => runTask(async task => {setStage('Loading attachment'); const data = await request('/api/workspace-report?id=' + encodeURIComponent($('report-selector').value), {}, task); setReport(data.report); renderMessages();}));
  window.addEventListener('resize', () => {
    if (innerWidth <= 1250) {
      $('workspace-context').classList.remove('closed');
      document.querySelector('.workspace-shell').classList.remove('details-closed');
    }
    closePanels();
  });
  window.addEventListener('storage', event => {if (event.key === RECENT) renderRecent();});
  document.addEventListener('keydown', event => {if (event.key === 'Escape') closePanels();});
  restore();
})();
