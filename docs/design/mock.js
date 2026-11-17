/* Mockup-only behaviour: theme, state, tab and drawer switching via URL params.
   ?state=<name>  ?theme=light|dark  ?tab=chat|trace|queue  ?drawer=1|2
   Not part of the product; the React build replaces this with real state. */
(function () {
  var q = new URLSearchParams(location.search);
  var root = document.documentElement, body = document.body;

  var theme = q.get('theme');
  try { if (!theme) theme = localStorage.getItem('sl-theme'); } catch (e) {}
  if (theme === 'light' || theme === 'dark') root.setAttribute('data-theme', theme);

  function effectiveTheme() {
    return root.getAttribute('data-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }
  var toggle = document.querySelector('.theme-toggle');
  function syncToggle() {
    if (!toggle) return;
    var dark = effectiveTheme() === 'dark';
    toggle.setAttribute('aria-pressed', String(dark));
    toggle.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  }
  if (toggle) toggle.addEventListener('click', function () {
    var next = effectiveTheme() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('sl-theme', next); } catch (e) {}
    syncToggle();
  });
  syncToggle();

  var timer;
  function setState(s) {
    body.dataset.state = s;
    document.querySelectorAll('[data-s]').forEach(function (el) {
      el.hidden = el.dataset.s.split(' ').indexOf(s) === -1;
    });
    var d = document.getElementById('drawer'), sc = document.querySelector('.scrim');
    var open = !!(d && q.get('drawer') && s === 'answer');
    if (d) d.hidden = !open; if (sc) sc.hidden = !open;
    document.querySelectorAll('.cite').forEach(function (c) { c.setAttribute('aria-expanded', String(open && c.dataset.src === (q.get('drawer') || '1'))); });
  }
  var state = q.get('state') || body.dataset.default || 'idle';
  setState(state);

  function setTab(t) {
    body.dataset.tab = t;
    document.querySelectorAll('.tab').forEach(function (b) { b.setAttribute('aria-current', String(b.dataset.tab === t)); });
  }
  setTab(q.get('tab') || 'chat');
  document.querySelectorAll('.tab').forEach(function (b) { b.addEventListener('click', function () { setTab(b.dataset.tab); }); });
  document.querySelectorAll('[data-goto-tab]').forEach(function (b) { b.addEventListener('click', function () { setTab(b.dataset.gotoTab); }); });

  // Click-through: send -> streaming -> answer; Approve -> resolved.
  document.querySelectorAll('[data-goto-state]').forEach(function (b) {
    b.addEventListener('click', function () {
      clearTimeout(timer);
      q.delete('drawer');
      setState(b.dataset.gotoState);
      if (b.dataset.gotoState === 'streaming') timer = setTimeout(function () { setState('answer'); }, 3500);
    });
  });

  // Source drawer
  var drawer = document.getElementById('drawer'), scrim = document.querySelector('.scrim');
  function openDrawer(n) {
    if (!drawer) return;
    drawer.hidden = false; if (scrim) scrim.hidden = false;
    drawer.querySelectorAll('.src-panel').forEach(function (el) { el.hidden = el.dataset.src !== String(n); });
    drawer.querySelectorAll('.drawer-tab').forEach(function (t) { t.setAttribute('aria-selected', String(t.dataset.src === String(n))); });
    document.querySelectorAll('.cite, .source-link').forEach(function (c) { c.setAttribute('aria-expanded', String(c.dataset.src === String(n))); });
    var h = drawer.querySelector('h2'); if (h) h.focus && h.focus();
  }
  function closeDrawer() {
    if (!drawer) return; drawer.hidden = true; if (scrim) scrim.hidden = true;
    document.querySelectorAll('.cite, .source-link').forEach(function (c) { c.setAttribute('aria-expanded', 'false'); });
  }
  document.querySelectorAll('.cite, .source-link, .drawer-tab').forEach(function (c) { c.addEventListener('click', function () { openDrawer(c.dataset.src); }); });
  document.querySelectorAll('[data-close-drawer]').forEach(function (c) { c.addEventListener('click', closeDrawer); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });
  if (drawer && !drawer.hidden) openDrawerSilently();
  function openDrawerSilently() {
    var n = q.get('drawer') || '1';
    drawer.querySelectorAll('.src-panel').forEach(function (el) { el.hidden = el.dataset.src !== String(n); });
    drawer.querySelectorAll('.drawer-tab').forEach(function (t) { t.setAttribute('aria-selected', String(t.dataset.src === String(n))); });
  }
})();
