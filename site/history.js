// History: search in the archive of the past Double XP missions.
const form = document.getElementById('filters');
const resultsZone = document.getElementById('results');
const summaryZone = document.getElementById('summary');
const moreButton = document.getElementById('more');

let currentSeason = '';
let missions = [];
let page = 1;
let total = 0;
let pendingRequest = 0;

function defaultValues() {
  return { mission: '', biome: '', length: '', season: currentSeason };
}

function currentFilters() {
  return Object.fromEntries(new FormData(form));
}

function render() {
  const now = new Date();
  summaryZone.textContent = total
    ? `${total.toLocaleString('en-GB')} mission${total > 1 ? 's' : ''}`
    : '';
  resultsZone.innerHTML = missions.length
    ? groupByDay(missions, now)
    : '<p class="empty">No missions match these filters.</p>';
  moreButton.hidden = missions.length >= total;
}

async function search(more = false) {
  const filters = currentFilters();
  if (!more) {
    page = 1;
    updateAddress(filters, defaultValues());
  }
  const request = ++pendingRequest;
  const params = new URLSearchParams({ ...filters, period: 'past', page });
  moreButton.disabled = true;
  try {
    const response = await readApi(`api/missions?${params}`);
    if (request !== pendingRequest) return; // a more recent search was started
    total = response.total;
    missions = more ? missions.concat(response.missions) : response.missions;
    render();
  } catch (e) {
    if (request !== pendingRequest) return;
    resultsZone.innerHTML = '<p class="empty">Couldn\'t load missions. Please try again in a moment.</p>';
  } finally {
    moreButton.disabled = false;
  }
}

async function start() {
  try {
    const f = await readApi('api/filters');
    currentSeason = f.current_season;
    fillFilters(form, f);
  } catch (e) {
    resultsZone.innerHTML = '<p class="empty">Couldn\'t load filters. Please try again in a moment.</p>';
    return;
  }
  applyFilters(form, { ...defaultValues(), ...startFilters() });
  search();
}

form.addEventListener('change', () => search());
document.getElementById('reset').addEventListener('click', () => {
  applyFilters(form, defaultValues());
  search();
});
moreButton.addEventListener('click', () => {
  page += 1;
  search(true);
});

start();
