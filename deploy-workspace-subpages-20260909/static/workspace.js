/* Conversation state and safe Markdown rendering for the new workspace. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const messages = $('workspace-messages'), input = $('workspace-input');
  const STORE = 'ffdcWorkspaceV3', RECENT = 'ffdcWorkspaceRecent';
  let state = {messages: [], report: null, reports: [], issue: null, analysis: null, pending: null};
  let controller = null, epoch = 0, busy = false, timer = null, stage = '', operationStart = 0;
  const icons = () => window.lucide?.createIcons();
  const chinese = text => /[\u3400-\u9fff]/.test(text || '');
  const wording = (zh, en, question = '') => chinese(question || state.messages.filter(m => m.role === 'user').at(-1)?.content) ? zh : en;
  const node = (tag, text = '', cls = '') => {const el = document.createElement(tag); if (text) el.textContent = text; if (cls) el.className = cls; return el;};
  const icon = name => {const el = node('i'); el.dataset.lucide = name; return el;};
  const validId = value => /^[A-Za-z0-9_-]+$/.test(String(value || ''));
  const keyIn = text => (String(text || '').match(/\b[A-Z][A-Z0-9_]*-\d+\b/i) || [''])[0].toUpperCase();
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
  function renderMessage(item) {
    const row = node('article', '', 'workspace-msg ' + item.role), body = node('div', '', 'workspace-msg-body');
    if (item.role === 'assistant') {const label = node('div', '', 'assistant-label'); label.append(icon('sparkles'), node('span', 'Analysis')); row.append(label); markdown(item.content, body);} else body.textContent = item.content;
    row.append(body);
    if (item.role === 'assistant') {
      if (item.analysis?.sources?.length) {const details = node('details', '', 'message-evidence'); details.append(node('summary', wording('查看已读取的证据', 'Evidence read', item.question) + ` (${item.analysis.sources.length})`)); for (const source of item.analysis.sources) details.append(sourceButton(source, item.reportId)); row.append(details);}
      const footer = node('div', '', 'message-footer'), copy = node('button', '', 'icon-button'); copy.type = 'button'; copy.title = 'Copy response'; copy.setAttribute('aria-label', 'Copy response'); copy.append(icon('copy')); copy.addEventListener('click', () => copyText(item.content, copy));
      footer.append(copy, node('span', [item.model, item.analysis?.elapsed_seconds != null ? `${item.analysis.elapsed_seconds}s` : ''].filter(Boolean).join(' · '))); row.append(footer);
    }
    messages.append(row); return row;
  }
  function renderMessages() {
    messages.replaceChildren();
    if (!state.messages.length) {
      const welcome = node('div', '', 'welcome'); welcome.id = 'welcome'; const symbol = node('div', '', 'welcome-symbol'); symbol.append(icon('scan-line')); welcome.append(symbol, node('h2', state.report ? 'Continue this investigation' : 'What would you like to investigate?'));
      const actions = node('div', '', 'quick-actions');
      const examples = state.report ? [['有什么发现？', '有什么发现？'], ['查看原始证据', '列出相关原始日志证据和行号'], ['网卡状态', '这个 FFDC 的网卡有什么异常？']] : [['分析一个 Bug', '分析一下 IOSS-'], ['项目里程碑', '最近有哪些项目里程碑？']];
      for (const [label, question] of examples) {const button = node('button', label, 'quick-action'); button.type = 'button'; button.addEventListener('click', () => {input.value = question; input.focus(); resize();}); actions.append(button);} welcome.append(actions); messages.append(welcome);
    } else for (const item of state.messages) renderMessage(item);
    icons(); messages.scrollTop = messages.scrollHeight;
  }
  function append(item) {state.messages.push(item); state.messages = state.messages.slice(-24); persist(); $('welcome')?.remove(); const row = renderMessage(item); icons(); messages.scrollTop = messages.scrollHeight; return row;}
  function setReport(report, issue = null) {
    state.report = report || null; state.issue = issue || report?.issue || null; state.analysis = null;
    if (report) saveRecent(report); persist(); renderContext();
  }
  function renderContext() {
    const report = state.report, issue = state.issue;
    $('context-empty').hidden = !!(report || issue); $('context-data').hidden = !(report || issue);
    $('chat-context').textContent = report ? (issue?.key ? issue.key + ' · ' : '') + report.file : issue?.key || 'New conversation';
    $('composer-scope').textContent = report?.file || issue?.key || 'No report selected';
    $('context-bug').replaceChildren();
    if (issue?.key) {const link = node('a', issue.key); link.href = 'https://jira1.labs.lenovo.com/browse/' + encodeURIComponent(issue.key); link.target = '_blank'; link.rel = 'noopener noreferrer'; $('context-bug').append(link);} else $('context-bug').textContent = 'Not linked';
    $('context-status').textContent = issue?.status || '—'; $('context-engineer').textContent = issue?.engineer || '—'; $('context-file').textContent = report?.file || '—'; $('context-created').textContent = report?.created_at || '—';
    const reportLink = $('open-analysis-report'); reportLink.hidden = !report?.id; if (report?.id) reportLink.href = '/report?id=' + encodeURIComponent(report.id) + '&view=workspace';
    const select = $('report-selector'); select.replaceChildren(); $('report-selector-wrap').hidden = state.reports.length < 2;
    for (const item of state.reports) {const option = node('option', item.file || item.attachment || item.id); option.value = item.id; option.selected = item.id === report?.id; select.append(option);}
    const sources = state.analysis?.sources || []; $('evidence-count').textContent = sources.length; $('evidence-sources').replaceChildren();
    for (const source of sources) $('evidence-sources').append(sourceButton(source, report?.id));
    if (!sources.length) $('evidence-sources').append(node('p', 'No source excerpts read yet.', 'evidence-empty'));
    $('model-meta').textContent = state.analysis ? `${state.analysis.model || ''}${state.analysis.elapsed_seconds != null ? ' · ' + state.analysis.elapsed_seconds + 's' : ''}` : '';
    if (state.analysis?.scan?.limited) $('evidence-sources').append(node('p', wording('日志扫描有范围限制，未覆盖全部文件。', 'The bounded scan did not cover all log content.'), 'evidence-note'));
  }
  function resize() {input.style.height = 'auto'; input.style.height = Math.min(144, Math.max(52, input.scrollHeight)) + 'px';}
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
    ensure(task); if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`); return data;
  }
  const post = (url, payload, task) => request(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}, task);
  const pause = () => new Promise(resolve => setTimeout(resolve, 900));
  function historyFor(reportId) {return state.messages.filter(m => ['user', 'assistant'].includes(m.role) && (m.reportId || null) === (reportId || null)).slice(-8).map(({role, content}) => ({role, content: content.slice(0, 10000)}));}
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
      if (task === epoch) {busy = false; clearInterval(timer); $('workspace-send').disabled = false; $('attach-button').disabled = false; $('report-selector').disabled = false; $('workspace-stop').hidden = true; $('operation-status').hidden = true; input.focus();}
    }
  }
  function acceptAnswer(data, question) {
    if (data.report) setReport(data.report, data.issue || state.issue);
    if (data.issue) state.issue = data.issue;
    const latestUser = state.messages.filter(item => item.role === 'user').at(-1);
    if (latestUser && data.report) latestUser.reportId = data.report.id;
    if (!data.answer?.trim()) throw new Error(wording('模型未返回分析内容，请重试。', 'The model returned no answer. Please retry.', question));
    state.analysis = {...data.analysis, model: data.model}; state.pending = null;
    append({role: 'assistant', content: data.answer, model: data.model, analysis: state.analysis, reportId: state.report?.id || null, question});
    renderContext(); persist();
  }
  async function answerReport(question, task) {
    setStage(wording('正在核对报告与原始日志', 'Reviewing report and original evidence', question));
    state.pending = {kind: 'answer', question, reportId: state.report.id}; persist();
    const data = await post('/workspace-report-chat', {id: state.report.id, message: question, history: historyFor(state.report.id)}, task);
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
      const data = await post('/workspace-chat', {message: question, history: historyFor(null)}, task);
      if (data.issue) {state.issue = data.issue; renderContext();}
      if (data.ffdc_job_id) {state.pending = {kind: 'jira', jobId: data.ffdc_job_id, question}; persist(); await waitForJob(state.pending, task);} else acceptAnswer(data, question);
    }, () => ask(question, attachment, true));
  }
  function reset() {
    ++epoch; controller?.abort(); busy = false; clearInterval(timer); state = {messages: [], report: null, reports: [], issue: null, analysis: null, pending: null};
    input.value = ''; $('workspace-file').value = ''; $('file-chip').hidden = true; $('workspace-send').disabled = false; $('attach-button').disabled = false; $('report-selector').disabled = false; $('workspace-stop').hidden = true; $('operation-status').hidden = true;
    persist(); renderMessages(); renderContext(); closePanels(); resize(); input.focus();
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
    event.preventDefault(); if (busy) return; const attachment = $('workspace-file').files[0] || null; const question = input.value.trim() || (attachment ? '分析一下这个 FFDC，有哪些重要发现？' : ''); if (!question) return;
    input.value = ''; resize(); $('workspace-file').value = ''; $('file-chip').hidden = true; ask(question, attachment);
  });
  input.addEventListener('input', resize); input.addEventListener('keydown', event => {if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault(); $('workspace-composer').requestSubmit();}});
  $('attach-button').addEventListener('click', () => $('workspace-file').click());
  $('workspace-file').addEventListener('change', () => {const file = $('workspace-file').files[0]; $('file-chip').hidden = !file; $('file-chip-name').textContent = file?.name || '';});
  $('file-remove').addEventListener('click', () => {$('workspace-file').value = ''; $('file-chip').hidden = true;});
  $('workspace-stop').addEventListener('click', () => controller?.abort()); $('new-analysis').addEventListener('click', reset);
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
