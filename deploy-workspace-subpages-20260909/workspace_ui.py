"""Conversation workspace and its opt-in themed subpages."""
import html
import re
from urllib.parse import parse_qsl, urlencode, urlparse

VERSION = "20260909-quality2"

WORKSPACE_NAV = (
    ('defect', '/Defect_review?view=workspace', 'list-checks', 'Defect Review'),
    ('milestones', '/Current_bug_status_summary?view=workspace', 'calendar-days', 'Milestones'),
    ('reports', '/reports?view=workspace', 'files', 'Reports'),
    ('usage', '/usage-stats?view=workspace', 'chart-no-axes-combined', 'Usage'),
)


def workspace_navigation(active=''):
    links = []
    for key, href, icon, label in WORKSPACE_NAV:
        current = ' class="active" aria-current="page"' if key == active else ''
        links.append(f'<a href="{href}"{current}><i data-lucide="{icon}"></i>{label}</a>')
    return ''.join(links)


def workspace_page_identity(path):
    route = urlparse(str(path)).path
    if route.startswith('/Defect_review') or route == '/jira-results':
        return 'defect', {
            '/Defect_review': 'Defect Review',
            '/Defect_review_result': 'Defect Review Result',
            '/Defect_review_similar': 'Similar JIRA Bugs',
            '/Defect_review_ffdcs': 'Defect FFDC Files',
            '/jira-results': 'JIRA FFDC Results',
        }.get(route, 'Defect Review')
    if route == '/Current_bug_status_summary':
        return 'milestones', 'IOSS key milestones and defects mapping'
    if route == '/usage-stats':
        return 'usage', 'Usage'
    if route == '/report':
        return 'reports', 'FFDC Analysis Report'
    return 'reports', 'Reports'


def classic_url(path):
    parsed = urlparse(str(path))
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != 'view']
    return parsed._replace(query=urlencode(query)).geturl() or '/'


def render_workspace_subpage(legacy_page, request_path):
    """Place a legacy content body inside the new shell without changing classic routes."""
    page = str(legacy_page)
    main = re.search(r'<main(?:\s+class=[\'\"][^\'\"]*[\'\"])?[^>]*>', page, re.I)
    end = page.rfind('</main>')
    if not main or end < main.end():
        return page
    inner = page[main.end():end]
    first_section = inner.find('<section')
    content = inner[first_section:] if first_section >= 0 else inner
    head_end = page.find('</head>')
    if head_end < 0:
        return page
    head = page[:head_end]
    active, title = workspace_page_identity(request_path)
    head = re.sub(r'<title>.*?</title>', '<title>' + html.escape(title) + ' - FFDC Analysis</title>', head, count=1, flags=re.I | re.S)
    head += (
        f'<link rel="stylesheet" href="/static/workspace.css?v={VERSION}">'
        f'<link rel="stylesheet" href="/static/workspace-subpage.css?v={VERSION}">'
        f'<script defer src="/static/workspace-lucide.js?v={VERSION}"></script>'
        f'<script defer src="/static/workspace-subpage.js?v={VERSION}"></script>'
    )
    return head + '</head><body class="workspace-subpage-body">' + f'''
<header class="workspace-topbar">
  <div class="brand-group"><button class="icon-button mobile-nav" id="subpage-toggle-sidebar" title="Navigation" aria-label="Navigation" aria-expanded="false"><i data-lucide="panel-left"></i></button>
  <a class="workspace-brand" href="/new-version"><img src="/static/lenovo_logo.png" alt="Lenovo"><span>FFDC Analysis<span class="brand-subtitle">Engineering workspace</span></span></a></div>
  <a href="{html.escape(classic_url(request_path), quote=True)}" class="classic-link" data-classic-view>Classic view <i data-lucide="arrow-up-right"></i></a>
</header>
<main class="workspace-subpage-shell">
  <aside class="workspace-sidebar" id="workspace-subpage-sidebar" aria-label="Navigation">
    <a class="new-analysis" href="/new-version"><i data-lucide="square-pen"></i>New analysis</a>
    <nav class="workspace-nav">{workspace_navigation(active)}</nav>
  </aside>
  <div class="workspace-page">
    <header class="workspace-page-header"><div><div class="workspace-page-eyebrow">Engineering workspace</div><h1>{html.escape(title)}</h1></div></header>
    <div class="workspace-page-content" id="workspace-page-content">{content}</div>
  </div>
</main>
<button class="drawer-backdrop" id="subpage-drawer-backdrop" aria-label="Close navigation" hidden></button>
</body></html>'''


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
    <nav class="workspace-nav">__NAVIGATION__</nav>
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
</body></html>'''.replace('__VERSION__', VERSION).replace('__NOTICE__', notice).replace('__NAVIGATION__', workspace_navigation())
