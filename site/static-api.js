// "static" mode (GitHub Pages): replays in JavaScript the three routes of api/api.py from
// data/missions.json, which tools/build_static.py generates at every data update.
// The pages see no difference: common.js calls readStatic() instead of fetch('api/...').
(function () {
  const PER_PAGE = 50;
  const SLOT_MS = 30 * 60 * 1000; // a mission stays available for 30 min
  const VALIDITY_MS = 5 * 60 * 1000; // the file is not downloaded again more than once every 5 min

  let cache = null;
  let loadedAt = 0;

  async function load() {
    if (cache && Date.now() - loadedAt < VALIDITY_MS) return cache;
    const response = await fetch('data/missions.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error(response.status);
    cache = (await response.json()).missions;
    loadedAt = Date.now();
    return cache;
  }

  function iso(date) {
    return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
  }

  // Like int() on the Python side: refuses anything that is not an integer.
  function integer(value, fallback) {
    if (value === undefined) return fallback;
    if (!/^[+-]?\d+$/.test(value)) throw new Error('invalid parameter');
    return parseInt(value, 10);
  }

  const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const sorted = (values) => [...new Set(values)].sort();

  // Like current_season() in api.py: the forced season, otherwise the most recent season found
  // in the missions of the last two days and the upcoming ones.
  function currentSeason(missions) {
    const forced = (window.DRG_CONFIG || {}).currentSeason;
    if (forced) return forced;
    const since = iso(new Date(Date.now() - 2 * 86400 * 1000));
    const numbers = missions.filter((m) => m.start >= since)
      .flatMap((m) => m.seasons).filter((s) => /^s\d+$/.test(s)).map((s) => Number(s.slice(1)));
    return numbers.length ? `s${Math.max(...numbers)}` : 's0';
  }

  // Comma-separated list of accepted values (mission, biome), or null for everything.
  function choice(value) {
    const values = (value || '').split(',').filter(Boolean);
    return values.length ? values : null;
  }

  async function upcoming(params) {
    const hours = Math.min(integer(params.hours, 24), 24 * 14);
    const now = Date.now();
    const after = iso(new Date(now - SLOT_MS));
    const until = iso(new Date(now + hours * 3600 * 1000));
    const missions = await load();
    return { missions: missions.filter((m) => m.start > after && m.start <= until) };
  }

  async function filters() {
    const missions = await load();
    return {
      missions: sorted(missions.map((m) => m.mission)),
      biomes: sorted(missions.map((m) => m.biome)),
      seasons: sorted(missions.flatMap((m) => m.seasons)),
      current_season: currentSeason(missions),
      archive_since: missions.length ? missions[0].start : null,
      known_until: missions.length ? missions[missions.length - 1].start : null,
    };
  }

  async function search(params) {
    const now = iso(new Date());
    const period = params.period || 'past';
    const length = params.length ? integer(params.length) : null;
    const page = Math.max(1, integer(params.page, 1));
    const missionTypes = choice(params.mission);
    const biomes = choice(params.biome);
    const missions = await load();

    // The original rank (i) breaks ties between two missions of the same slot and biome.
    let list = missions.map((m, i) => ({ m, i })).filter(({ m }) =>
      (!missionTypes || missionTypes.includes(m.mission))
      && (!biomes || biomes.includes(m.biome))
      && (length === null || m.length === length)
      && (!params.season || m.seasons.includes(params.season)));

    let descending = true;
    if (period === 'past') {
      list = list.filter(({ m }) => m.start <= now);
    } else if (period === 'upcoming') {
      list = list.filter(({ m }) => m.start > now);
      descending = false;
    }
    // ORDER BY start (DESC or ASC), biome; with equal slot and biome, the API (SQLite) walks the index
    // on start in the sort direction: insertion order when ascending, reverse order when descending.
    list.sort((a, b) => {
      if (a.m.start !== b.m.start) return descending ? compare(b.m.start, a.m.start) : compare(a.m.start, b.m.start);
      if (a.m.biome !== b.m.biome) return compare(a.m.biome, b.m.biome);
      return descending ? b.i - a.i : a.i - b.i;
    });

    return {
      total: list.length,
      page,
      per_page: PER_PAGE,
      missions: list.slice((page - 1) * PER_PAGE, page * PER_PAGE).map(({ m }) => m),
    };
  }

  const ROUTES = { '/api/upcoming': upcoming, '/api/filters': filters, '/api/missions': search };

  window.readStatic = async function (path) {
    const url = new URL(path, 'http://local/');
    const route = ROUTES[url.pathname];
    if (!route) throw new Error('404');
    return route(Object.fromEntries(url.searchParams));
  };
})();
