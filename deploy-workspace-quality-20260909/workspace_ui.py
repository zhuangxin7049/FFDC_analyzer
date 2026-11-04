"""Conversation workspace, kept separate from the classic report interface."""
import html

VERSION = "20260909-quality1"


def render_workspace_page(message=""):
    notice = ('<div class="workspace-notice" role="alert">' + html.escape(str(message)) + '</div>') if message else ''
    return r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ThinkSystem FFDC Analysis Workspace</title>
  <link rel="stylesheet" href="/static/workspace.css?v=__VERSION__">
  <script defer src="/static/workspace-marked.js?v=__VERSION__"></script>
  <script defer src="/static/workspace-lucide.js?v=__VERSION__"></script>
  <script defer src="/static/workspace.js?v=__VERSION__"></script>
</head>
<body>
<header class="workspace-topbar">
  <div class="brand-group"><button class="icon-button mobile-nav" id="toggle-sidebar" title="Navigation" aria-label="Navigation" aria-expanded="false"><i data-lucide="panel-left"></i></button>
  <a class="workspace-brand" href="/new-version"><img src="/static/lenovo_logo.png" alt="Lenovo"><span>FFDC Analysis<span class="brand-subtitle">Engineering workspace</span></span></a></div>
  <a href="/" class="classic-link">Classic view <i data-lucide="arrow-up-right"></i></a>
</header>
<main class="workspace-shell">
  <aside class="workspace-sidebar" id="workspace-sidebar" aria-label="Navigation">
    <button class="new-analysis" id="new-analysis" type="button"><i data-lucide="square-pen"></i>New analysis</button>
    <nav class="workspace-nav">
      <a href="/Defect_review"><i data-lucide="list-checks"></i>Defect Review</a>
      <a href="/Current_bug_status_summary"><i data-lucide="calendar-days"></i>Milestones</a>
      <a href="/reports"><i data-lucide="files"></i>Reports</a>
      <a href="/usage-stats"><i data-lucide="chart-no-axes-combined"></i>Usage</a>
    </nav>
    <div class="recent-block"><div class="recent-head"><span>Recent <span>30 days</span></span><button id="clear-recent" class="text-button" type="button" title="Clear recent items">Clear</button></div><div class="recent-list" id="recent-list"></div></div>
  </aside>
  <section class="workspace-chat" aria-label="Analysis conversation">
    <header class="chat-header"><div><h1 id="chat-title">FFDC Analysis Assistant</h1><div class="chat-context" id="chat-context">New conversation</div></div><button class="icon-button" id="toggle-context" title="Analysis details" aria-label="Analysis details" aria-expanded="false"><i data-lucide="panel-right"></i></button></header>
    __NOTICE__
    <div class="workspace-messages" id="workspace-messages" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions"></div>
    <div class="workspace-composer-wrap">
      <div class="file-chip" id="file-chip" hidden><i data-lucide="file-archive"></i><span id="file-chip-name"></span><button id="file-remove" class="icon-button" type="button" title="Remove attachment" aria-label="Remove attachment"><i data-lucide="x"></i></button></div>
      <div class="operation-status" id="operation-status" role="status" hidden></div>
      <form class="workspace-composer" id="workspace-composer">
        <input id="workspace-file" type="file" accept=".tzz,.tar,.tar.zst,.tzst,.tgz,.gz" hidden>
        <textarea id="workspace-input" rows="2" maxlength="12000" aria-label="Message" placeholder="Ask a question, enter a Bug ID, or attach an FFDC..."></textarea>
        <div class="composer-toolbar"><button class="icon-button" id="attach-button" type="button" title="Attach FFDC" aria-label="Attach FFDC"><i data-lucide="paperclip"></i></button><span class="composer-scope" id="composer-scope">No report selected</span><button class="icon-button stop-button" id="workspace-stop" type="button" title="Stop waiting" aria-label="Stop waiting" hidden><i data-lucide="square"></i></button><button class="send-button" id="workspace-send" type="submit" title="Send message" aria-label="Send message"><i data-lucide="arrow-up"></i></button></div>
      </form>
    </div>
  </section>
  <aside class="workspace-context" id="workspace-context" aria-label="Current analysis">
    <header class="context-header"><h2>Current analysis</h2><button class="icon-button close-context" id="close-context" title="Close details" aria-label="Close details"><i data-lucide="x"></i></button></header>
    <div class="context-empty" id="context-empty"><i data-lucide="file-search"></i><p>No active report</p></div>
    <div class="context-data" id="context-data" hidden>
      <label class="report-selector" id="report-selector-wrap" hidden>Attachment<select id="report-selector"></select></label>
      <dl class="context-fields"><dt>Bug</dt><dd id="context-bug"></dd><dt>Status</dt><dd id="context-status"></dd><dt>Engineer</dt><dd id="context-engineer"></dd><dt>File</dt><dd id="context-file"></dd><dt>Collected</dt><dd id="context-created"></dd></dl>
      <a class="report-action" id="open-analysis-report" target="_blank" rel="noopener noreferrer" hidden><i data-lucide="file-text"></i>Open analysis report<i data-lucide="arrow-up-right"></i></a>
      <div class="evidence-panel"><h3>Evidence read <span id="evidence-count">0</span></h3><div id="evidence-sources"></div><div class="model-meta" id="model-meta"></div></div>
    </div>
  </aside>
</main>
<button class="drawer-backdrop" id="drawer-backdrop" aria-label="Close panel" hidden></button>
<dialog id="evidence-dialog"><header><h2>Source evidence</h2><button class="icon-button" id="close-evidence" title="Close evidence" aria-label="Close evidence"><i data-lucide="x"></i></button></header><div id="evidence-content"></div></dialog>
</body></html>'''.replace('__VERSION__', VERSION).replace('__NOTICE__', notice)
