/* Shared page-language preference for the workspace shell and utility pages. */
(() => {
  'use strict';
  const STORE = 'ffdcPageLanguage';
  const text = {
    en: {
      nav: {snapdump: 'SnapDump Analysis', milestones: 'Milestones', reports: 'History', usage: 'Usage', maintenance: 'Maintenance log', about: 'About & releases'},
      newAnalysis: 'New analysis', recent: 'Recent', recentDays: '30 days', clear: 'Clear',
      assistant: 'FFDC Analyzer Assistant', conversation: 'New conversation', current: 'Current analysis',
      noReport: 'No active report', reportList: 'FFDC Analysis Report List', evidence: 'Evidence read',
      noSelected: 'No report selected', attach: 'Attach FFDC', messagePlaceholder: 'Ask a question, enter a Bug ID, or attach an FFDC...',
      pageLanguage: 'Page language', support: 'For any questions, please contact:',
      about: {
        heading: 'Product version and release notes',
        intro: 'The product version identifies the deployed application. Report and evidence data remain separate from this release marker.',
        current: 'Current release', releaseNotes: 'Release notes'
      },
      maintenance: {
        heading: 'Register a maintenance item',
        intro: 'Record a UI issue, parser gap, model problem, or deployment follow-up for review.',
        category: 'Category', priority: 'Priority', title: 'Short title', related: 'Related report or Bug ID',
        description: 'Details', owner: 'Owner', contact: 'Contact', clear: 'Clear', submit: 'Register item',
        recent: 'Recent maintenance items', empty: 'No maintenance items have been registered.', saved: 'Maintenance item registered.'
      }
    },
    zh: {
      nav: {snapdump: 'SnapDump 分析', milestones: '里程碑', reports: '历史记录', usage: '使用情况', maintenance: '维护登记', about: '关于与发布说明'},
      newAnalysis: '新建分析', recent: '最近记录', recentDays: '30 天', clear: '清除',
      assistant: 'FFDC 分析助手', conversation: '新对话', current: '当前分析',
      noReport: '没有活动报告', reportList: 'FFDC 分析报告列表', evidence: '已读取证据',
      noSelected: '未选择报告', attach: '附加 FFDC', messagePlaceholder: '输入问题、Bug ID，或附加 FFDC…',
      pageLanguage: '页面语言', support: '如有任何问题请联系：',
      about: {
        heading: '产品版本与发布说明',
        intro: '产品版本用于标识已部署的应用程序。报告和证据数据与版本标记分开保存。',
        current: '当前版本', releaseNotes: '发布说明'
      },
      maintenance: {
        heading: '登记维护事项',
        intro: '登记界面问题、解析缺口、模型问题或部署跟进事项，供团队处理。',
        category: '类别', priority: '优先级', title: '简短标题', related: '关联报告或 Bug ID',
        description: '详细说明', owner: '负责人', contact: '联系方式', clear: '清除', submit: '登记事项',
        recent: '最近维护事项', empty: '还没有登记维护事项。', saved: '维护事项已登记。'
      }
    }
  };
  const get = (root, key) => String(key || '').split('.').reduce((value, part) => value && value[part], root);
  const MAINTENANCE_SEEN = 'ffdcMaintenanceLastSeen';
  const preserveIconText = (element, value) => {
    const icon = element.querySelector('i,svg');
    const badge = element.querySelector('[data-maintenance-unread]');
    if (icon && badge) { element.replaceChildren(icon, document.createTextNode(value), badge); }
    else if (icon) { element.replaceChildren(icon, document.createTextNode(value)); }
    else { element.textContent = value; }
  };
  const setText = (element, value) => {
    if (element && value !== undefined) element.textContent = value;
  };
  function language() {
    try { return localStorage.getItem(STORE) === 'zh' ? 'zh' : 'en'; } catch { return 'en'; }
  }
  function maintenanceTimestamp(value) {
    const timestamp = Date.parse(String(value || ''));
    return Number.isFinite(timestamp) ? timestamp : 0;
  }
  async function refreshMaintenanceUnread() {
    const badges = [...document.querySelectorAll('[data-maintenance-unread]')];
    if (!badges.length) return;
    try {
      const response = await fetch('/api/maintenance', {cache: 'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      const records = Array.isArray(data.records) ? data.records : [];
      let lastSeen = 0;
      try { lastSeen = Number(localStorage.getItem(MAINTENANCE_SEEN) || 0) || 0; } catch {}
      const newest = records.reduce((latest, row) => Math.max(latest, maintenanceTimestamp(row?.created_at)), 0);
      const onMaintenancePage = location.pathname === '/maintenance';
      const unread = onMaintenancePage ? 0 : records.filter(row => maintenanceTimestamp(row?.created_at) > lastSeen).length;
      if (onMaintenancePage) {
        try { localStorage.setItem(MAINTENANCE_SEEN, String(Math.max(Date.now(), newest))); } catch {}
      }
      const lang = language();
      badges.forEach(badge => {
        badge.textContent = String(unread);
        badge.hidden = unread <= 0;
        badge.title = lang === 'zh' ? `${unread} 条新的维护登记` : `${unread} new maintenance item${unread === 1 ? '' : 's'}`;
        badge.setAttribute('aria-label', badge.title);
      });
    } catch {}
  }
  function apply(next) {
    const lang = next === 'zh' ? 'zh' : 'en';
    const dictionary = text[lang];
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-language]').forEach(button => {
      const active = button.dataset.language === lang;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    document.querySelectorAll('[data-i18n]').forEach(element => setText(element, get(dictionary, element.dataset.i18n)));
    document.querySelectorAll('[data-workspace-nav]').forEach(element => preserveIconText(element, dictionary.nav[element.dataset.workspaceNav] || element.textContent));
    document.querySelectorAll('.new-analysis').forEach(element => preserveIconText(element, dictionary.newAnalysis));
    setText(document.querySelector('.recent-head > span'), dictionary.recent + ' ' + dictionary.recentDays);
    setText(document.querySelector('#chat-title'), dictionary.assistant);
    const chatContext = document.querySelector('#chat-context');
    if (chatContext && ['New conversation', '新对话'].includes(chatContext.textContent)) setText(chatContext, dictionary.conversation);
    setText(document.querySelector('#context-empty p'), dictionary.noReport);
    setText(document.querySelector('.context-header h2'), dictionary.current);
    setText(document.querySelector('.analysis-report-heading h3'), dictionary.reportList);
    setText(document.querySelector('.evidence-panel summary span'), dictionary.evidence);
    const input = document.querySelector('#workspace-input');
    if (input) input.placeholder = dictionary.messagePlaceholder;
    const scope = document.querySelector('#composer-scope');
    if (scope && ['No report selected', '未选择报告'].includes(scope.textContent)) scope.textContent = dictionary.noSelected;
    const attach = document.querySelector('#attach-button');
    if (attach) { attach.title = dictionary.attach; attach.setAttribute('aria-label', dictionary.attach); }
    const clear = document.querySelector('#clear-recent');
    if (clear) clear.textContent = dictionary.clear;
    const contact = document.querySelector('.workspace-support-contact span');
    if (contact) contact.textContent = dictionary.support;
    document.querySelectorAll('[data-i18n-placeholder]').forEach(element => { element.placeholder = get(dictionary, element.dataset.i18nPlaceholder) || element.placeholder; });
    document.querySelectorAll('[data-i18n-title]').forEach(element => { element.title = get(dictionary, element.dataset.i18nTitle) || element.title; });
    try { localStorage.setItem(STORE, lang); } catch {}
    window.dispatchEvent(new CustomEvent('ffdc-language-change', {detail: {language: lang}}));
    refreshMaintenanceUnread();
    window.lucide?.createIcons();
  }
  window.FFDCI18n = {apply, language};
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-language]').forEach(button => button.addEventListener('click', () => apply(button.dataset.language)));
    apply(language());
    refreshMaintenanceUnread();
    window.setInterval(refreshMaintenanceUnread, 30000);
  });
})();
