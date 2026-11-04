(() => {
  const sidebar = document.getElementById('workspace-subpage-sidebar');
  const toggle = document.getElementById('subpage-toggle-sidebar');
  const backdrop = document.getElementById('subpage-drawer-backdrop');
  const close = () => {
    sidebar?.classList.remove('open');
    if (backdrop) backdrop.hidden = true;
    toggle?.setAttribute('aria-expanded', 'false');
  };
  toggle?.addEventListener('click', () => {
    const open = !sidebar.classList.contains('open');
    close();
    sidebar.classList.toggle('open', open);
    backdrop.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
  });
  backdrop?.addEventListener('click', close);
  document.addEventListener('keydown', event => {if (event.key === 'Escape') close();});

  document.querySelectorAll('#workspace-page-content a[href]').forEach(link => {
    if (link.hasAttribute('data-classic-view') || link.target === '_blank') return;
    const url = new URL(link.getAttribute('href'), location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/')) return;
    if (url.pathname === '/' || url.pathname === '/new-version' || url.pathname.startsWith('/static/') || url.pathname.startsWith('/download-')) return;
    url.searchParams.set('view', 'workspace');
    link.href = url.pathname + url.search + url.hash;
  });
  document.querySelectorAll('#workspace-page-content form[action="/clear-reports"]').forEach(form => {
    form.action = '/clear-reports?view=workspace';
  });
  if (window.lucide) window.lucide.createIcons({attrs: {'aria-hidden': 'true'}});
})();
