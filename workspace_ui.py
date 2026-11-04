"""Conversation workspace and its opt-in themed subpages."""
import html
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse
from zoneinfo import ZoneInfo

VERSION = "20261030-psu-collapse1"
SUPPORT_CONTACT = (
    '<div class="workspace-support-contact" lang="en">'
    '<span>For any questions, please contact:</span>'
    '<a href="mailto:zhuangxin2@lenovo.com">zhuangxin2@lenovo.com</a></div>'
)
MAINTENANCE_END = datetime(2026, 10, 3, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

WORKSPACE_NAV = (
    ('snapdump', '/snapdump', 'hard-drive', 'SnapDump Analysis'),
    ('milestones', '/Current_bug_status_summary?view=workspace', 'calendar-days', 'Milestones'),
    ('reports', '/reports?view=workspace', 'files', 'History'),
    ('usage', '/usage-stats?view=workspace', 'chart-no-axes-combined', 'Usage'),
    ('maintenance', '/maintenance?view=workspace', 'clipboard-list', 'Maintenance log'),
    ('about', '/about?view=workspace', 'info', 'About & releases'),
)

RELEASE_NOTES = (
    {
        'version': VERSION,
        'date': '2026-10-30',
        'title': 'Release metadata consistency',
        'changes': (
            'Keep the current release date consistent across the About page and version response.',
            'Keep the existing version and release-notes data available to the application.',
        ),
    },
    {
        'version': '20261030-about-cleanup1',
        'date': '2026-10-30',
        'title': 'About page cleanup',
        'changes': (
            'Removed the public version endpoint explanation from the About page.',
            'Kept the existing version and release-notes data available to the application.',
        ),
    },
    {
        'version': '20261028-workspace-tools1',
        'date': '2026-10-28',
        'title': 'Workspace tools',
        'changes': (
            'Added a persistent English / Chinese page-language switch.',
            'Added a public version and release-notes page.',
            'Added maintenance registration with a local, reviewable record list.',
        ),
    },
    {
        'version': '20261028-pci-id-broadcom1',
        'date': '2026-10-28',
        'title': 'PCI ID normalization and Broadcom coverage',
        'changes': (
            'Render PCI Vendor ID and Device ID using conventional hexadecimal notation.',
            'Keep the original decimal values in evidence for traceability.',
        ),
    },
)


def workspace_navigation(active=''):
    links = []
    for key, href, icon, label in WORKSPACE_NAV:
        current = ' class="active" aria-current="page"' if key == active else ''
        badge = ''
        if key == 'maintenance':
            badge = '<span class="workspace-nav-badge" data-maintenance-unread hidden>0</span>'
        links.append(f'<a href="{href}" data-workspace-nav="{key}"{current}><i data-lucide="{icon}"></i>{label}{badge}</a>')
    return ''.join(links)


def workspace_language_controls():
    """Small shared control; the language preference is applied client-side."""
    return (
        '<div class="workspace-language-control" id="workspace-language-control" '
        'aria-label="Page language">'
        '<button type="button" data-language="zh" aria-label="中文">中文</button>'
        '<span aria-hidden="true">/</span>'
        '<button type="button" data-language="en" aria-label="English">EN</button>'
        '</div>'
    )


def workspace_topbar_utilities():
    return '<div class="workspace-topbar-utilities">' + workspace_language_controls() + SUPPORT_CONTACT + '</div>'


def workspace_page_identity(path):
    route = urlparse(str(path)).path
    if route == '/snapdump':
        return 'snapdump', 'SnapDump Analysis'
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
    if route == '/maintenance':
        return 'maintenance', 'Maintenance log'
    if route == '/about':
        return 'about', 'About & releases'
    if route == '/report':
        return 'reports', 'FFDC Analyzer Report'
    if route == '/reports':
        return 'reports', 'History'
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
    # Event handlers emitted after the original main still need the retained DOM.
    # Only copy the tail: scripts inside content already occur exactly once.
    trailing_scripts = ''.join(re.findall(
        r'<script\b[^>]*>.*?</script\s*>', page[end + len('</main>'):], re.I | re.S
    ))
    head_end = page.find('</head>')
    if head_end < 0:
        return page
    # Some classic pages emit their page-specific CSS just inside body.
    # Preserve those rules before workspace styles so the shell keeps precedence.
    prefix_styles = ''.join(re.findall(
        r'<style\b[^>]*>.*?</style\s*>', page[head_end + len('</head>'):main.start()], re.I | re.S
    ))
    head = page[:head_end] + prefix_styles
    active, title = workspace_page_identity(request_path)
    head = re.sub(r'<title>.*?</title>', '<title>' + html.escape(title) + ' - FFDC Analyzer</title>', head, count=1, flags=re.I | re.S)
    head += (
        f'<link rel="stylesheet" href="/static/workspace.css?v={VERSION}">'
        f'<link rel="stylesheet" href="/static/workspace-subpage.css?v={VERSION}">'
        f'<script defer src="/static/workspace-lucide.js?v={VERSION}"></script>'
        f'<script defer src="/static/workspace-language.js?v={VERSION}"></script>'
        f'<script defer src="/static/workspace-subpage.js?v={VERSION}"></script>'
    )
    return head + '</head><body class="workspace-subpage-body">' + f'''
<header class="workspace-topbar">
  <div class="brand-group"><button class="icon-button mobile-nav" id="subpage-toggle-sidebar" title="Navigation" aria-label="Navigation" aria-expanded="false"><i data-lucide="panel-left"></i></button>
  <a class="workspace-brand" href="/new-version"><img src="/static/lenovo_logo.png" alt="Lenovo"><span>FFDC Analyzer<span class="brand-subtitle">Engineering workspace</span></span></a></div>
  {workspace_topbar_utilities()}
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
{trailing_scripts}
</body></html>'''


def render_workspace_page(message=""):
    notice = ('<div class="workspace-notice" role="alert">' + html.escape(str(message)) + '</div>') if message else ''
    maintenance = ''
    if datetime.now(ZoneInfo("Asia/Shanghai")) < MAINTENANCE_END:
        maintenance = (
            '<div class="maintenance-banner" id="maintenance-banner" role="alert" '
            f'data-hide-at="{int(MAINTENANCE_END.timestamp() * 1000)}">'
            '<strong>Scheduled maintenance:</strong> Beijing ISG R&amp;D network infrastructure will be unavailable '
            'from October 1, 00:00 to October 3, 20:00. The FFDC Analyzer will be unavailable during this period.'
            '</div>'
        )
    return r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ThinkSystem FFDC Analyzer Workspace</title>
  <link rel="stylesheet" href="/static/workspace.css?v=__VERSION__">
  <script defer src="/static/workspace-marked.js?v=__VERSION__"></script>
  <script defer src="/static/workspace-lucide.js?v=__VERSION__"></script>
  <script defer src="/static/workspace-language.js?v=__VERSION__"></script>
  <script defer src="/static/workspace.js?v=__VERSION__"></script>
</head>
<body>
__MAINTENANCE__
<header class="workspace-topbar">
  <div class="brand-group"><button class="icon-button mobile-nav" id="toggle-sidebar" title="Navigation" aria-label="Navigation" aria-expanded="false"><i data-lucide="panel-left"></i></button>
  <a class="workspace-brand" href="/new-version"><img src="/static/lenovo_logo.png" alt="Lenovo"><span>FFDC Analyzer<span class="brand-subtitle">Engineering workspace</span></span></a></div>
  __TOPBAR_UTILITIES__
</header>
<main class="workspace-shell">
  <aside class="workspace-sidebar" id="workspace-sidebar" aria-label="Navigation">
    <button class="new-analysis" id="new-analysis" type="button"><i data-lucide="square-pen"></i>New analysis</button>
    <nav class="workspace-nav">__NAVIGATION__</nav>
    <div class="recent-block"><div class="recent-head"><span>Recent <span>30 days</span></span><button id="clear-recent" class="text-button" type="button" title="Clear recent items">Clear</button></div><div class="recent-list" id="recent-list"></div></div>
  </aside>
  <section class="workspace-chat" aria-label="Analysis conversation">
    <header class="chat-header"><div><h1 id="chat-title">FFDC Analyzer Assistant</h1><div class="chat-context" id="chat-context">New conversation</div></div><button class="icon-button" id="toggle-context" title="Analysis details" aria-label="Analysis details" aria-expanded="false"><i data-lucide="panel-right"></i></button></header>
    __NOTICE__
    <div class="authoring-bar" id="authoring-bar" hidden><span id="authoring-status"></span><button type="button" class="icon-button" id="exit-authoring" title="Exit rule authoring" aria-label="Exit rule authoring"><i data-lucide="x"></i></button></div>
    <div class="workspace-messages" id="workspace-messages" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions"></div>
    <div class="workspace-composer-wrap">
      <div class="workspace-drop-hint" id="workspace-drop-hint" role="status" hidden></div>
      <div class="file-chip" id="file-chip" hidden><i data-lucide="file-archive"></i><span id="file-chip-name"></span><button id="file-remove" class="icon-button" type="button" title="Remove attachment" aria-label="Remove attachment"><i data-lucide="x"></i></button></div>
      <div class="operation-status" id="operation-status" role="status" hidden></div>
      <form class="workspace-composer" id="workspace-composer">
        <input id="workspace-file" type="file" accept=".tzz,.tar,.tar.zst,.tzst,.tgz,.gz,.log,.txt,.trace,.out,.journal,.dmesg,text/*" hidden>
        <textarea id="workspace-input" rows="2" maxlength="12000" aria-label="Message" placeholder="Ask a question, enter a Bug ID, or attach an FFDC..."></textarea>
        <div class="composer-toolbar"><button class="icon-button" id="attach-button" type="button" title="Attach FFDC" aria-label="Attach FFDC"><i data-lucide="paperclip"></i></button><span class="composer-scope" id="composer-scope">No report selected</span><button class="icon-button stop-button" id="workspace-stop" type="button" title="Stop waiting" aria-label="Stop waiting" hidden><i data-lucide="square"></i></button><button class="send-button" id="workspace-send" type="submit" title="Send message" aria-label="Send message"><i data-lucide="arrow-up"></i></button></div>
      </form>
    </div>
  </section>
  <aside class="workspace-context" id="workspace-context" aria-label="Current analysis">
    <header class="context-header"><h2>Current analysis</h2><button class="icon-button close-context" id="close-context" title="Close details" aria-label="Close details"><i data-lucide="x"></i></button></header>
    <div class="context-empty" id="context-empty"><i data-lucide="file-search"></i><p>No active report</p></div>
    <div class="context-data" id="context-data" hidden>
      <select id="report-selector" hidden aria-hidden="true"></select>
      <dl class="context-fields"><dt>Bug</dt><dd id="context-bug"></dd><dt>Status</dt><dd id="context-status"></dd><dt>Engineer</dt><dd id="context-engineer"></dd><dt>File</dt><dd id="context-file"></dd><dt>Collected</dt><dd id="context-created"></dd></dl>
      <section class="analysis-report-section" id="analysis-report-section" hidden><div class="analysis-report-heading"><h3>FFDC Analysis Report List</h3><span id="analysis-report-count">0</span></div><div class="analysis-report-list" id="analysis-report-list"></div></section>
      <details class="evidence-panel"><summary><span>Evidence read</span><span class="evidence-count" id="evidence-count">0</span></summary><div id="evidence-sources"></div><div class="model-meta" id="model-meta"></div></details>
    </div>
  </aside>
</main>
<button class="drawer-backdrop" id="drawer-backdrop" aria-label="Close panel" hidden></button>
<dialog id="jira-login-dialog" aria-labelledby="jira-login-title">
  <form autocomplete="off">
    <h2 id="jira-login-title">Sign in to JIRA</h2>
    <p>Use your own JIRA account. Credentials are held only in the temporary server session, not saved to disk.</p>
    <label>Username<input name="username" autocomplete="off" required></label>
    <label>Password<div class="password-field"><input name="password" type="password" autocomplete="off" required><button type="button" class="password-toggle icon-button" id="toggle-jira-password" aria-label="Show password" title="Show password"><i data-lucide="eye"></i></button></div></label>
    <p role="alert"></p>
    <footer><button type="button" data-cancel>Cancel</button><button type="submit">Sign in</button></footer>
  </form>
</dialog>
<dialog id="evidence-dialog"><header><h2>Source evidence</h2><button class="icon-button" id="close-evidence" title="Close evidence" aria-label="Close evidence"><i data-lucide="x"></i></button></header><div id="evidence-content"></div></dialog>
</body></html>'''.replace('__VERSION__', VERSION).replace('__NOTICE__', notice).replace('__MAINTENANCE__', maintenance).replace('__NAVIGATION__', workspace_navigation()).replace('__TOPBAR_UTILITIES__', workspace_topbar_utilities())


def render_workspace_utility_page(kind, records=(), saved=False):
    """Return a classic page body for the existing workspace subpage wrapper."""
    if kind == 'about':
        title = 'About & releases'
        current_release_date = RELEASE_NOTES[0].get('date', '') if RELEASE_NOTES else ''
        body = (
            '<section class="workspace-utility-section" data-i18n-section="about">'
            '<div class="workspace-utility-lead"><div class="workspace-page-eyebrow">FFDC Analyzer</div>'
            '<h2 data-i18n="about.heading">Product version and release notes</h2>'
            '<p data-i18n="about.intro">The product version identifies the deployed application. Report and evidence data remain separate from this release marker.</p></div>'
            f'<div class="workspace-version-card"><strong>{html.escape(VERSION)}</strong><span data-i18n="about.current">Current release</span><time>{html.escape(str(current_release_date))}</time></div>'
            '<h3 data-i18n="about.releaseNotes">Release notes</h3><div class="workspace-release-list">'
            + ''.join(
                '<article class="workspace-release-item">'
                f'<header><strong>{html.escape(str(item.get("version", "")))}</strong><time>{html.escape(str(item.get("date", "")))}</time></header>'
                f'<h4>{html.escape(str(item.get("title", "")))}</h4><ul>'
                + ''.join(f'<li>{html.escape(str(change))}</li>' for change in item.get('changes', ()))
                + '</ul></article>' for item in RELEASE_NOTES
            )
            + '</div></section>'
        )
    else:
        title = 'Maintenance log'
        rows = ''
        for row in tuple(records or ()):
            rows += (
                '<article class="workspace-maintenance-item">'
                '<header><strong>' + html.escape(str(row.get('title') or row.get('category') or 'Maintenance item')) + '</strong>'
                '<span class="workspace-maintenance-status">' + html.escape(str(row.get('status') or 'Open')) + '</span></header>'
                '<p>' + html.escape(str(row.get('description') or '')) + '</p>'
                '<small>' + html.escape(str(row.get('id') or '')) + ' · ' + html.escape(str(row.get('created_at') or '')) + '</small>'
                '</article>'
            )
        notice = '<div class="workspace-form-notice" role="status" data-i18n="maintenance.saved">Maintenance item registered.</div>' if saved else ''
        body = (
            '<section class="workspace-utility-section" data-i18n-section="maintenance">'
            '<div class="workspace-utility-lead"><div class="workspace-page-eyebrow">FFDC Analyzer</div>'
            '<h2 data-i18n="maintenance.heading">Register a maintenance item</h2>'
            '<p data-i18n="maintenance.intro">Record a UI issue, parser gap, model problem, or deployment follow-up for review.</p></div>'
            + notice +
            '<form class="workspace-maintenance-form" method="post" action="/maintenance?view=workspace">'
            '<input type="hidden" name="view" value="workspace">'
            '<div class="workspace-form-grid">'
            '<label><span data-i18n="maintenance.category">Category</span><select name="category"><option>UI / usability</option><option>Parser / evidence</option><option>AI / model</option><option>Deployment</option></select></label>'
            '<label><span data-i18n="maintenance.priority">Priority</span><select name="priority"><option>Normal</option><option>High</option><option>Blocker</option></select></label>'
            '<label><span data-i18n="maintenance.title">Short title</span><input name="title" maxlength="120" required placeholder="A short description"></label>'
            '<label><span data-i18n="maintenance.related">Related report or Bug ID</span><input name="related" maxlength="120" placeholder="Optional"></label>'
            '<label class="workspace-form-wide"><span data-i18n="maintenance.description">Details</span><textarea name="description" maxlength="4000" required placeholder="Describe the issue and expected behavior"></textarea></label>'
            '<label><span data-i18n="maintenance.owner">Owner</span><input name="owner" maxlength="80" placeholder="Optional"></label>'
            '<label><span data-i18n="maintenance.contact">Contact</span><input name="contact" maxlength="160" placeholder="Optional email or team"></label>'
            '</div><div class="workspace-form-actions"><button class="button" type="reset" data-i18n="maintenance.clear">Clear</button><button class="button primary" type="submit" data-i18n="maintenance.submit">Register item</button></div>'
            '</form></section>'
            '<section class="workspace-utility-section" data-i18n-section="maintenance-list">'
            '<h3 data-i18n="maintenance.recent">Recent maintenance items</h3>'
            + (rows or '<p class="hint" data-i18n="maintenance.empty">No maintenance items have been registered.</p>')
            + '</section>'
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} - FFDC Analyzer</title>'
        '</head><body><main>' + body + '</main></body></html>'
    )
