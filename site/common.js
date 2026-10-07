// Shared rendering of the missions (upcoming and history pages).
const SLOT_MS = 30 * 60 * 1000; // a mission stays available for 30 min
const DEFAULT_MUTATOR = 'Double XP'; // the mutator selected by default in the filters
const NO_MUTATOR = 'none'; // filter value for the missions without a mutator

// "Double XP mission" when the filters only keep Double XP missions, "mission" otherwise.
function missionKind(filters) {
  return filters.mutator === DEFAULT_MUTATOR ? 'Double XP mission' : 'mission';
}

const CONFIG = window.DRG_CONFIG || {};

// Visit statistics (GoatCounter: no cookies, no personal data), only when a site code is configured.
// Page views are counted without the query string, so that every filter combination is not a separate page.
if (/^[a-z0-9-]+$/.test(CONFIG.goatcounter || '')) {
  window.goatcounter = { path: () => location.pathname };
  const script = document.createElement('script');
  script.async = true;
  script.dataset.goatcounter = `https://${CONFIG.goatcounter}.goatcounter.com/count`;
  script.src = 'https://gc.zgo.at/count.js';
  document.head.appendChild(script);
}

// Name of the filter changed by a form event (checkbox lists carry it on their hidden field).
function filterName(event) {
  const multi = event.target.closest && event.target.closest('.multi');
  return multi ? multi.querySelector('input[type=hidden]').name : event.target.name;
}

// Counts an action (event) in the statistics; does nothing without statistics.
function track(name) {
  if (window.goatcounter && window.goatcounter.count) {
    window.goatcounter.count({ path: name, title: name, event: true });
  }
}

// "About" link at the top of the pages, to the project's README.
if (/^https:\/\//.test(CONFIG.readmeUrl || '')) {
  document.querySelector('.header').insertAdjacentHTML('beforeend',
    `<a class="about-link" href="${escapeHtml(CONFIG.readmeUrl)}" rel="noopener" data-readme>About</a>`);
}

const BIOME_COLORS = {
  'Crystalline Caverns': '#6fc3e8',
  'Salt Pits': '#e6d3a3',
  'Fungus Bogs': '#9bc94a',
  'Radioactive Exclusion Zone': '#7de05a',
  'Dense Biozone': '#d46ab8',
  'Glacial Strata': '#a9d8f0',
  'Hollow Bough': '#c9894a',
  'Azure Weald': '#4fa3e0',
  'Magma Core': '#f06a3a',
  'Sandblasted Corridors': '#e0b25a',
  'Ossuary Depths': '#b8a9c9',
};

const timeFmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' });
const dayFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
const dayYearFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

function dayLabel(date) {
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === tomorrow.toDateString()) return 'Tomorrow';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  const fmt = date.getFullYear() === today.getFullYear() ? dayFmt : dayYearFmt;
  return fmt.format(date);
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function gauge(value, label) {
  const dots = [1, 2, 3].map((i) => `<i class="${i <= value ? 'filled' : ''}"></i>`).join('');
  return `<span class="gauge" title="${label} ${value}/3">${label} <span class="dots">${dots}</span></span>`;
}

function seasonName(s) {
  return s === 's0' ? 'No season' : `Season ${s.slice(1)}`;
}

// A mission missing from season 0 only exists for the players of some seasons.
function seasonTag(seasons) {
  if (!seasons.length || seasons.includes('s0')) return '';
  return `<span class="tag season">${seasons.map(seasonName).join(', ')} only</span>`;
}

// "Set PC clock" button: opens a dialog that explains the principle and the helper's installation
// (clock-helper.ps1), then asks for confirmation. Only "Set clock" opens the drgtime:// link, which
// sets the Windows clock to this mission's time through the helper.
const START_FORMAT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

function clockButton(m) {
  if (!START_FORMAT.test(m.start)) return '';
  return `<div class="actions">
    <button type="button" class="clock-button" data-start="${m.start}"
      data-mission="${escapeHtml(m.mission)}" data-biome="${escapeHtml(m.biome)}">Set PC clock</button>
  </div>`;
}

const CLOCK_DIALOG = `
  <dialog id="clock-dialog" class="dialog" aria-labelledby="clock-title">
    <h2 id="clock-title">Set your PC clock to this mission</h2>
    <p id="clock-target" class="target"></p>
    <p>Deep Rock Galactic builds its mission list from your computer's clock. To play a mission
      that isn't live right now, your clock has to show that mission's time.</p>
    <h3>How it works</h3>
    <p>A web page can't change your clock by itself, so this uses a small helper installed once on your PC
      (Windows only). <strong>Set clock</strong> asks the helper to change your Windows clock to the time above.
      Afterwards, press <a href="drgtime://reset">Restore PC clock</a>: a shifted clock can disturb other apps and logins.</p>
    <div class="reassure">
      <p><strong>The helper is not a program.</strong> It is a plain text PowerShell script, about 130 lines with
        comments, that you can read from top to bottom before running anything. No compiled code, no installer,
        nothing hidden.</p>
      <ul>
        <li>Nothing is sent over the network.</li>
        <li>Nothing keeps running in the background: Windows starts it only when you press a button here.</li>
        <li>It can only set the clock (to a date between 2020 and 2035) or restore it.</li>
        <li>You can uninstall it at any time.</li>
      </ul>
      <details id="script-view">
        <summary>Read the script here</summary>
        <div class="script-actions">
          <button type="button" class="button" id="script-copy">Copy the script</button>
        </div>
        <pre id="script-source" tabindex="0">Loading…</pre>
      </details>
    </div>
    <h3>First time? Install the helper</h3>
    <ol>
      <li><a href="clock-helper.ps1" download id="script-download">Download the clock helper</a>
        (<code>clock-helper.ps1</code>). It goes to your Downloads folder.<br>
        <span class="muted">Prefer not to download a file? Press <strong>Copy the script</strong> above, paste it into
        Notepad, save it in your Downloads folder as <code>clock-helper.txt</code>, then rename it to
        <code>clock-helper.ps1</code>. It is exactly the same file.</span></li>
      <li>Open <strong>PowerShell</strong> (Start menu, type "PowerShell") and run this command
        (change the path if your browser saves files elsewhere):<br>
        <code>powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\\Downloads\\clock-helper.ps1"</code><br>
        Accept the administrator prompt if Windows shows one, and wait for "Installed. Self-test OK."</li>
      <li>Come back here and press <strong>Set clock</strong>. Your browser asks once whether to open the helper: allow it.</li>
    </ol>
    <p class="note">The helper only sets the clock (to dates between 2020 and 2035) and pauses Windows' automatic
      time sync until you restore it. To uninstall, run the same command with <code>-Uninstall</code> at the end.
      Use at your own risk.</p>
    <div class="dialog-actions">
      <button type="button" class="button" id="clock-cancel">Cancel</button>
      <a class="button button-primary" id="clock-confirm" href="#">Set clock</a>
    </div>
  </dialog>
  <div id="clock-toast" class="toast" role="status" hidden></div>`;

function lowerFirst(text) {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

// "Read the script here": the source is loaded the first time the section is opened.
async function showScript() {
  const pre = document.getElementById('script-source');
  if (pre.dataset.loaded) return;
  try {
    const response = await fetch('clock-helper.ps1', { cache: 'no-cache' });
    if (!response.ok) throw new Error(response.status);
    pre.textContent = await response.text();
    pre.dataset.loaded = '1';
  } catch (e) {
    pre.textContent = 'Could not load the script. Use the download link below and open it in Notepad.';
  }
}

async function copyScript() {
  await showScript();
  const pre = document.getElementById('script-source');
  if (!pre.dataset.loaded) return;
  try {
    await navigator.clipboard.writeText(pre.textContent);
    showClockToast('Script copied. Paste it into Notepad, save it as clock-helper.txt, then rename it to clock-helper.ps1.');
  } catch (e) {
    // Clipboard refused (permissions, old browser): select the text so that Ctrl+C works.
    const range = document.createRange();
    range.selectNodeContents(pre);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    showClockToast('Press Ctrl+C to copy the selected script.');
  }
}

// With a mission button: confirmation before acting. Without (footer link): plain help.
function openClockDialog(button) {
  const dialog = document.getElementById('clock-dialog');
  const target = document.getElementById('clock-target');
  const confirm = document.getElementById('clock-confirm');
  const cancel = document.getElementById('clock-cancel');
  const title = document.getElementById('clock-title');
  const startIso = button && button.dataset.start;
  if (startIso && START_FORMAT.test(startIso)) {
    const start = new Date(startIso);
    title.textContent = 'Set your PC clock to this mission';
    target.innerHTML = `<strong>${escapeHtml(button.dataset.mission)}</strong> · ${escapeHtml(button.dataset.biome)}<br>`
      + `Your PC clock will be set to <strong>${lowerFirst(dayLabel(start))} at ${timeFmt.format(start)}</strong> (your time zone).`;
    confirm.href = `drgtime://set?t=${startIso}`;
    target.hidden = false;
    confirm.hidden = false;
    cancel.textContent = 'Cancel';
  } else {
    title.textContent = 'PC clock helper';
    target.hidden = true;
    confirm.hidden = true;
    cancel.textContent = 'Close';
  }
  dialog.showModal();
}

function showClockToast(text) {
  const toast = document.getElementById('clock-toast');
  toast.textContent = text;
  toast.hidden = false;
  clearTimeout(showClockToast.timer);
  showClockToast.timer = setTimeout(() => { toast.hidden = true; }, 7000);
}

document.body.insertAdjacentHTML('beforeend', CLOCK_DIALOG);
document.querySelector('.footer').insertAdjacentHTML('beforeend',
  '<p><button type="button" class="link-button footer-link" data-clock-help>PC clock helper</button>'
  + ' · <a href="drgtime://reset">Restore PC clock</a></p>');

document.getElementById('clock-dialog').addEventListener('click', (e) => {
  const dialog = e.currentTarget;
  const area = dialog.getBoundingClientRect();
  const outside = e.clientX < area.left || e.clientX > area.right || e.clientY < area.top || e.clientY > area.bottom;
  if (outside) dialog.close(); // click on the backdrop, not inside the window
});

document.getElementById('script-view').addEventListener('toggle', (e) => {
  if (e.target.open) {
    showScript();
    track('helper-read-script');
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest) return;
  const button = e.target.closest('.clock-button');
  if (button) {
    openClockDialog(button);
    track('set-pc-clock-dialog');
  } else if (e.target.closest('[data-clock-help]')) {
    openClockDialog(null);
    track('helper-help-dialog');
  } else if (e.target.closest('#script-copy')) {
    copyScript();
    track('helper-copy-script');
  } else if (e.target.closest('#script-download')) {
    track('helper-download');
  } else if (e.target.closest('[data-readme]')) {
    track('readme');
  } else if (e.target.closest('#clock-cancel')) {
    document.getElementById('clock-dialog').close();
  } else if (e.target.closest('#clock-confirm')) {
    track('set-clock');
    // The drgtime:// link opens normally; we close the window and say the request has been sent.
    document.getElementById('clock-dialog').close();
    showClockToast('Request sent. If nothing happens, install the helper first '
      + '("PC clock helper" at the bottom of the page).');
  } else if (e.target.closest('a[href="drgtime://reset"]')) {
    track('restore-clock');
    showClockToast('Restore request sent.');
  }
});

function missionContent(m) {
  const warnings = m.warnings.map((w) => `<span class="tag warning">${escapeHtml(w)}</span>`).join('');
  const season = seasonTag(m.seasons);
  const mutator = m.mutator
    ? `<span class="tag mutator${m.mutator === DEFAULT_MUTATOR ? ' double-xp' : ''}">${escapeHtml(m.mutator)}</span>` : '';
  return `
    <p class="mission-title">${escapeHtml(m.mission)}</p>
    <div class="biome">${escapeHtml(m.biome)}</div>
    <div class="details">
      ${gauge(m.length, 'Length')}
      ${gauge(m.complexity, 'Complexity')}
      <span>${escapeHtml(m.secondary)}</span>
      <span class="code-name">${escapeHtml(m.name)}</span>
    </div>
    ${mutator || warnings || season ? `<div class="tags">${mutator}${warnings}${season}</div>` : ''}
    ${clockButton(m)}`;
}

function missionCard(m, now) {
  const start = new Date(m.start);
  const live = start <= now && start.getTime() + SLOT_MS > now;
  const color = BIOME_COLORS[m.biome] || '';
  return `
    <article class="mission" style="--biome:${color}">
      <div>
        <div class="time">${timeFmt.format(start)}</div>
        ${live ? '<span class="live">Live</span>' : ''}
      </div>
      <div>${missionContent(m)}</div>
    </article>`;
}

// Groups the missions by local day, in the order received.
function groupByDay(missions, now) {
  const byDay = new Map();
  for (const m of missions) {
    const key = dayLabel(new Date(m.start));
    if (!byDay.has(key)) byDay.set(key, []);
    byDay.get(key).push(m);
  }
  return [...byDay].map(([day, list]) => `
    <h3 class="day">${day}</h3>
    <div class="list">${list.map((m) => missionCard(m, now)).join('')}</div>`).join('');
}

// Checkbox filters (mission type, biome). Their value is carried by a hidden field:
// '' = everything (all boxes checked, or none), otherwise the checked values separated by commas.

// Values kept by a checkbox filter, or null if it lets everything through.
function multiChoice(value) {
  return value ? value.split(',') : null;
}

function multiSummary(checked, total) {
  if (!checked.length || checked.length === total) return 'All';
  if (checked.length === 1) return checked[0].parentElement.textContent.trim(); // the label, e.g. "No mutator"
  return `${checked.length} selected`;
}

// Copies the state of the boxes into the hidden field and the summary.
function readMulti(block) {
  const boxes = [...block.querySelectorAll('.multi-options input')];
  const checked = boxes.filter((b) => b.checked);
  const all = block.querySelector('[data-all]');
  all.checked = checked.length === boxes.length;
  all.indeterminate = checked.length > 0 && checked.length < boxes.length;
  block.querySelector('input[type=hidden]').value =
    checked.length && checked.length < boxes.length ? checked.map((b) => b.value).join(',') : '';
  block.querySelector('summary').textContent = multiSummary(checked, boxes.length);
}

// Checks the boxes from a value (address, saved filters, reset).
function writeMulti(block, value) {
  const choice = multiChoice(value);
  for (const b of block.querySelectorAll('.multi-options input')) b.checked = !choice || choice.includes(b.value);
  readMulti(block);
}

function fillMulti(block, values, label = (v) => v) {
  const zone = block.querySelector('.multi-options');
  zone.innerHTML = values
    .map((v) => `<label><input type="checkbox" value="${escapeHtml(v)}" checked> ${escapeHtml(label(v))}</label>`).join('');
  // Listened to on the block: the hidden field is up to date before the event reaches the form.
  block.addEventListener('change', (e) => {
    if (e.target.matches('[data-all]')) {
      for (const b of zone.querySelectorAll('input')) b.checked = e.target.checked;
    }
    readMulti(block);
  });
  readMulti(block);
}

// One panel open at a time; a click elsewhere or Escape closes it.
document.addEventListener('click', (e) => {
  for (const d of document.querySelectorAll('.multi details[open]')) {
    if (!d.contains(e.target)) d.open = false;
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  for (const d of document.querySelectorAll('.multi details[open]')) {
    d.open = false;
    d.querySelector('summary').focus();
  }
});

// Filters shared by both pages (mission, biome, season), filled from api/filters.
function fillFilters(form, f) {
  fillMulti(form.elements.namedItem('mission').closest('.multi'), f.missions);
  fillMulti(form.elements.namedItem('biome').closest('.multi'), f.biomes);
  fillMulti(form.elements.namedItem('mutator').closest('.multi'), [...f.mutators, NO_MUTATOR],
    (v) => (v === NO_MUTATOR ? 'No mutator' : v));
  const season = form.elements.namedItem('season');
  for (const s of f.seasons.slice().reverse()) {
    season.add(new Option(s === f.current_season ? `Current (${s.slice(1)})` : seasonName(s), s));
  }
}

function applyFilters(form, values) {
  for (const [key, value] of Object.entries(values)) {
    // namedItem(), not elements[key]: "length" would return the number of fields of the form.
    const field = form.elements.namedItem(key);
    if (!field) continue;
    if (field.type === 'hidden') writeMulti(field.closest('.multi'), value);
    else if ([...field.options].some((o) => o.value === value)) field.value = value;
  }
}

// Filters are kept in the address, so that a search can be shared or reloaded,
// and saved in the browser for the next visit.
const SAVED_FILTERS_KEY = 'drg-filters';

function updateAddress(filters, defaults) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== defaults[key]) params.set(key, value);
  }
  const text = params.toString();
  history.replaceState(null, '', text ? `?${text}` : location.pathname);
  try { localStorage.setItem(SAVED_FILTERS_KEY, text); } catch (e) { /* storage unavailable */ }
  updateTabLinks();
}

// Filters to start with: those of the address if any, otherwise the saved ones.
function startFilters() {
  if (location.search) return Object.fromEntries(new URLSearchParams(location.search));
  try {
    return Object.fromEntries(new URLSearchParams(localStorage.getItem(SAVED_FILTERS_KEY) || ''));
  } catch (e) {
    return {};
  }
}

// The tabs (and the logo) carry the filters of the address to the other page.
function updateTabLinks() {
  for (const link of document.querySelectorAll('.tabs a, .brand')) {
    const target = link.getAttribute('href').split('?')[0];
    link.setAttribute('href', target + location.search);
  }
}
updateTabLinks();

async function readApi(path) {
  // GitHub Pages mode: no API, the routes are replayed in static-api.js.
  if (window.DRG_CONFIG && window.DRG_CONFIG.mode === 'static') return readStatic(path);
  const response = await fetch(path, { cache: 'no-cache' });
  if (!response.ok) throw new Error(response.status);
  return response.json();
}
