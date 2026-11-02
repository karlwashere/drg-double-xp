// Dark (default) or light theme, remembered in this browser. Loaded in <head> so the page never flashes.
(() => {
  const KEY = 'theme';
  const read = () => { try { return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'; } catch { return 'dark'; } };
  const apply = (t) => { if (t === 'light') document.documentElement.dataset.theme = 'light'; else delete document.documentElement.dataset.theme; };
  const label = () => document.querySelectorAll('[data-theme-toggle]').forEach((b) => {
    const dark = read() === 'dark';
    b.textContent = dark ? '☀' : '☾';
    b.title = dark ? 'Switch to light theme' : 'Switch to dark theme';
    b.setAttribute('aria-label', b.title);
  });
  apply(read());
  document.addEventListener('DOMContentLoaded', label);
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest?.('[data-theme-toggle]')) return;
    const next = read() === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(KEY, next); } catch { /* private mode: this page only */ }
    apply(next); label();
  });
})();
