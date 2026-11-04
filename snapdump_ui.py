"""Standalone SnapDump analysis inside the FFDC engineering workspace."""

from workspace_ui import render_workspace_subpage

VERSION = "20261030-psu-collapse1"


def render_snapdump_page():
    """Render the independent SnapDump page with the shared workspace navigation."""
    page = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SnapDump Analysis - FFDC Analyzer</title>
  <link rel="stylesheet" href="/static/snapdump.css?v=__VERSION__">
  <script defer src="/static/snapdump.js?v=__VERSION__"></script>
</head>
<body><main>
<section id="snapdump-page" class="snapdump-page">
  <header class="page-header compact snapdump-page-header">
    <div><p class="eyebrow">CONTROLLER DIAGNOSTICS</p><p class="snapdump-intro">Analyze a SnapDump archive and ask Davy AI about its logs.</p></div>
    <div class="snapdump-header-actions"><span class="evidence-pill"><i></i>Evidence from logs</span><button id="snapdump-reset" class="ghost" type="button">Clear results</button></div>
  </header>
  <section id="snapdump-upload-card" class="snapdump-upload-card">
    <div class="snapdump-upload-copy"><span class="snapdump-upload-icon">SD</span><div><h3>Import SnapDump</h3><p>MPI3 or MegaRAID <code>.zip</code> archives up to 50 MiB, or individual <code>.txt</code> / <code>.log</code> files up to 16 MiB.</p></div></div>
    <input id="snapdump-file" type="file" accept=".zip,.txt,.log" hidden>
    <div id="snapdump-dropzone" class="snapdump-dropzone" tabindex="0" aria-label="Choose or drop a SnapDump file"><strong>Drop a file here</strong><span>or</span><button id="snapdump-choose" class="secondary" type="button">Choose SnapDump</button><small id="snapdump-filename">No file selected</small></div>
    <div class="snapdump-upload-actions"><button id="snapdump-analyze" class="primary" type="button" disabled>Analyze</button><span id="snapdump-status" class="form-hint" aria-live="polite"></span></div>
    <p id="snapdump-error" class="error hidden" role="alert"></p>
  </section>
  <section id="snapdump-result" class="snapdump-result hidden">
    <div class="snapdump-result-banner"><div><p class="eyebrow">ANALYSIS RESULT</p><h3 id="snapdump-result-title">SnapDump</h3><p id="snapdump-result-subtitle"></p></div><span id="snapdump-health-badge" class="snapdump-health-badge">Pending analysis</span></div>
    <div id="snapdump-summary-cards" class="snapdump-summary-cards"></div>
    <div class="snapdump-main-grid">
      <section class="snapdump-panel"><div class="snapdump-panel-heading"><div><p class="eyebrow">HEALTH CHECKS</p><h3>Health checks</h3></div><span id="snapdump-check-count" class="snapdump-panel-count"></span></div><div id="snapdump-checks" class="snapdump-check-list"></div></section>
      <section class="snapdump-panel"><div class="snapdump-panel-heading"><div><p id="snapdump-info-eyebrow" class="eyebrow">FIRMWARE & LINK</p><h3 id="snapdump-info-title">Firmware & link</h3></div></div><div id="snapdump-firmware" class="snapdump-info-grid"></div></section>
    </div>
    <div class="snapdump-lower-grid">
      <section class="snapdump-panel"><div class="snapdump-panel-heading"><div><p class="eyebrow">CONTROLLER EVENTS</p><h3>Event history</h3></div><span id="snapdump-event-count" class="snapdump-panel-count"></span></div><div id="snapdump-events" class="snapdump-events"></div></section>
      <section id="snapdump-file-explorer" class="snapdump-panel"><div class="snapdump-panel-heading"><div><p class="eyebrow">RAW EVIDENCE</p><h3>File explorer</h3></div><input id="snapdump-file-filter" class="snapdump-file-filter" type="search" placeholder="Filter files" aria-label="Filter SnapDump files"></div><div class="snapdump-file-browser"><div id="snapdump-files" class="snapdump-file-list"></div><pre id="snapdump-file-preview" class="snapdump-file-preview" tabindex="0" aria-label="Original log contents">Select a file to view its original contents.</pre></div></section>
    </div>
    <section id="snapdump-avenger-panel" class="snapdump-panel hidden" aria-labelledby="snapdump-avenger-title"><div class="snapdump-panel-heading"><div><p class="eyebrow">MODE, TOPOLOGY &amp; DIAGNOSTIC EVIDENCE</p><h3 id="snapdump-avenger-title">Evidence details</h3></div></div><div id="snapdump-avenger"></div></section>
    <div id="snapdump-notes" class="snapdump-notes"></div>
    <section class="snapdump-panel snapdump-chat" aria-labelledby="snapdump-chat-title">
      <div class="snapdump-chat-heading">
        <div class="snapdump-chat-brand"><span class="snapdump-chat-avatar" aria-hidden="true">D</span><div><p class="eyebrow">ASK YOUR SNAPDUMP</p><h3 id="snapdump-chat-title">Davy AI Q&amp;A</h3></div></div>
        <button id="snapdump-chat-clear" class="ghost" type="button">Clear conversation</button>
      </div>
      <p class="snapdump-chat-description">Ask about faults, firmware, I/O, or events in this SnapDump. Follow up in English or Chinese and inspect the supporting log excerpts.</p>
      <div class="snapdump-chat-context"><span aria-hidden="true">⌁</span><span id="snapdump-chat-context">Current SnapDump</span><small>Conversation is limited to this analysis</small></div>
      <div id="snapdump-chat-messages" class="snapdump-chat-messages" role="log" aria-label="Davy AI conversation" aria-live="polite" aria-relevant="additions"></div>
      <div id="snapdump-chat-suggestions" class="snapdump-chat-suggestions" aria-label="Suggested questions">
        <button type="button" data-snapdump-question="Summarize the main findings and explain what needs attention.">Summarize findings</button>
        <button type="button" data-snapdump-question="Is there evidence of a controller fault? Show the supporting logs.">Check for faults</button>
        <button type="button" data-snapdump-question="What do the PCIe link fields tell us, and what cannot be confirmed from this dump?">Explain PCIe fields</button>
        <button type="button" data-snapdump-question="What should I check next based on this SnapDump?">What to check next</button>
      </div>
      <form id="snapdump-chat-form" class="snapdump-chat-form">
        <label for="snapdump-chat-question">Ask Davy about this SnapDump</label>
        <textarea id="snapdump-chat-question" rows="3" maxlength="4000" placeholder="Ask a question or follow up on Davy's answer…" aria-describedby="snapdump-chat-hint" required></textarea>
        <div class="snapdump-chat-actions"><span id="snapdump-chat-hint">Enter to send · Shift + Enter for a new line</span><button id="snapdump-chat-send" class="primary" type="submit">Send</button></div>
      </form>
      <div id="snapdump-chat-error" class="snapdump-chat-error hidden" role="alert"><span id="snapdump-chat-error-message"></span><button id="snapdump-chat-retry" class="secondary" type="button">Retry question</button></div>
      <p id="snapdump-chat-status" class="snapdump-chat-status" role="status" aria-live="polite"></p>
    </section>
  </section>
  <div id="snapdump-toast" class="snapdump-toast hidden" role="status"></div>
</section>
</main></body></html>'''.replace('__VERSION__', VERSION)
    return render_workspace_subpage(page, '/snapdump')
