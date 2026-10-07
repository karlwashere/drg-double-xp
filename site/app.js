// Home page: the next mission matching the filters (Double XP by default) + the live and upcoming
// ones, loaded 24 hours at a time ("Load one more day") and shown 100 at a time ("Show more missions").
const form = document.getElementById('filters');
// The default season is the current one, known once api/filters has been loaded.
let defaultFilters = { mission: '', biome: '', mutator: DEFAULT_MUTATOR, warning: '', length: '', season: '' };
const nextDayButton = document.getElementById('next-day');
const moreButton = document.getElementById('more-missions');
const MAX_DAYS = 14; // limit of the API (api/upcoming)
const SHOWN_STEP = 100; // missions added to the list by "Show more missions"
let days = 1; // number of 24-hour periods loaded
let shown = SHOWN_STEP; // number of missions shown in the list
let knownUntil = null; // start of the last known mission (api/filters)

function countdown(ms) {
  const minutes = Math.max(0, Math.round(ms / 60000));
  if (minutes < 60) return `in ${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `in ${h} h ${String(m).padStart(2, '0')}` : `in ${h} h`;
}

function currentFilters() {
  return Object.fromEntries(new FormData(form));
}

function hasActiveFilter(filters) {
  return Object.values(filters).some(Boolean);
}

function showFeatured(m, now, filtered) {
  const zone = document.getElementById('featured');
  const kind = missionKind(currentFilters());
  if (!m) {
    zone.innerHTML = filtered
      ? `<p class="empty">No matching ${kind} in the ${periodLabel()}.</p>`
      : `<p class="empty">No known ${kind} for now.</p>`;
    return;
  }
  const start = new Date(m.start);
  const live = start <= now;
  const end = new Date(start.getTime() + SLOT_MS);
  zone.style.setProperty('--biome', BIOME_COLORS[m.biome] || '');
  zone.innerHTML = `
    <p class="countdown">${live ? 'Live now' : countdown(start - now)}</p>
    <p class="when">${live
      ? `Available until ${timeFmt.format(end)}`
      : `${dayLabel(start)} at ${timeFmt.format(start)}`}</p>
    ${missionContent(m)}`;
}

let missions = [];
let loaded = false;
let pendingRequest = 0;

function periodLabel() {
  return days === 1 ? 'next 24 hours' : `next ${days} days`;
}

// No more day to load once the API limit or the end of the known forecast is reached.
function canLoadMore() {
  if (days >= MAX_DAYS) return false;
  return !knownUntil || Date.now() + days * 86400000 < new Date(knownUntil).getTime();
}

function refresh() {
  if (!loaded) return;
  const now = new Date();
  const filters = currentFilters();
  const filtered = hasActiveFilter(filters);
  // The API already applied the filters; keep the missions that have not ended yet.
  const active = missions.filter((m) => new Date(m.start).getTime() + SLOT_MS > now);
  document.getElementById('next-title').textContent = `Next ${missionKind(filters)}`;
  showFeatured(active[0], now, filtered);
  const period = periodLabel();
  document.getElementById('upcoming-title').textContent = period[0].toUpperCase() + period.slice(1);
  // The list also contains the featured mission: it is the complete timeline.
  document.getElementById('upcoming').innerHTML = active.length
    ? groupByDay(active.slice(0, shown), now)
    : `<p class="empty">${filtered
      ? `No missions match these filters in the ${period}.`
      : `Nothing scheduled in the ${period}.`}</p>`;
  const hidden = active.length - shown;
  moreButton.hidden = hidden <= 0;
  moreButton.textContent = `Show more missions (${hidden.toLocaleString('en-GB')} left)`;
  // A further day only makes sense once everything already loaded is on screen.
  nextDayButton.hidden = hidden > 0 || !canLoadMore();
}

async function load() {
  const request = ++pendingRequest;
  nextDayButton.disabled = true;
  const params = new URLSearchParams({ hours: days * 24, ...currentFilters() });
  try {
    const response = await readApi(`api/upcoming?${params}`);
    if (request !== pendingRequest) return true; // a more recent load was started
    missions = response.missions;
  } catch (e) {
    if (!loaded && request === pendingRequest) {
      document.getElementById('featured').innerHTML =
        '<p class="empty">Couldn\'t load missions. Please try again in a moment.</p>';
    }
    return false;
  } finally {
    nextDayButton.disabled = false;
  }
  loaded = true;
  refresh();
  return true;
}

// New filters: back to the first missions of the period already loaded.
function reload() {
  shown = SHOWN_STEP;
  load();
}

async function start() {
  try {
    const f = await readApi('api/filters');
    fillFilters(form, f);
    defaultFilters = { ...defaultFilters, season: f.current_season };
    knownUntil = f.known_until;
    applyFilters(form, { ...defaultFilters, ...startFilters() });
    updateAddress(currentFilters(), defaultFilters);
  } catch (e) {
    form.hidden = true; // without the lists, the filters are useless
  }
  load();
}

form.addEventListener('change', (e) => {
  track(`filter-${filterName(e)}`);
  updateAddress(currentFilters(), defaultFilters);
  reload();
});
document.getElementById('reset').addEventListener('click', () => {
  track('filter-reset');
  applyFilters(form, defaultFilters);
  updateAddress(currentFilters(), defaultFilters);
  reload();
});
moreButton.addEventListener('click', () => {
  track('show-more-missions');
  shown += SHOWN_STEP;
  refresh();
});
nextDayButton.addEventListener('click', async () => {
  track('load-one-more-day');
  days += 1;
  if (!(await load())) days -= 1; // failed: keep the period already shown
});

start();
setInterval(refresh, 30 * 1000);
setInterval(load, 10 * 60 * 1000);
