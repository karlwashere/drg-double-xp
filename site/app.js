// Home page: the next Double XP mission + the live and upcoming ones,
// loaded 24 hours at a time ("Load one more day" button).
const form = document.getElementById('filters');
// The default season is the current one, known once api/filters has been loaded.
let defaultFilters = { mission: '', biome: '', length: '', season: '' };
const nextDayButton = document.getElementById('next-day');
const MAX_DAYS = 14; // limit of the API (api/upcoming)
let days = 1; // number of 24-hour periods loaded
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

function matches(m, f) {
  const missionTypes = multiChoice(f.mission);
  const biomes = multiChoice(f.biome);
  return (!missionTypes || missionTypes.includes(m.mission))
    && (!biomes || biomes.includes(m.biome))
    && (!f.length || m.length === Number(f.length))
    && (!f.season || m.seasons.includes(f.season));
}

function showFeatured(m, now, filtered) {
  const zone = document.getElementById('featured');
  if (!m) {
    zone.innerHTML = filtered
      ? `<p class="empty">No matching Double XP mission in the ${periodLabel()}.</p>`
      : '<p class="empty">No known Double XP mission for now.</p>';
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
  // Keep the missions that have not ended yet and match the filters.
  const active = missions.filter(
    (m) => new Date(m.start).getTime() + SLOT_MS > now && matches(m, filters));
  showFeatured(active[0], now, filtered);
  const period = periodLabel();
  document.getElementById('upcoming-title').textContent = period[0].toUpperCase() + period.slice(1);
  // The list also contains the featured mission: it is the complete timeline.
  document.getElementById('upcoming').innerHTML = active.length
    ? groupByDay(active, now)
    : `<p class="empty">${filtered
      ? `No missions match these filters in the ${period}.`
      : `Nothing scheduled in the ${period}.`}</p>`;
  nextDayButton.hidden = !canLoadMore();
}

async function load() {
  nextDayButton.disabled = true;
  try {
    missions = (await readApi(`api/upcoming?hours=${days * 24}`)).missions;
  } catch (e) {
    if (!loaded) {
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
  refresh();
});
document.getElementById('reset').addEventListener('click', () => {
  track('filter-reset');
  applyFilters(form, defaultFilters);
  updateAddress(currentFilters(), defaultFilters);
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
