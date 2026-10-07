// "static" mode (GitHub Pages): replays in JavaScript the three routes of api/api.py from the files
// that tools/build_static.py generates at every data update:
//   data/index.json             months available, filter values, archive bounds;
//   data/missions-YYYY-MM.json  the missions of one month, in a compact form (see month_file there).
// Months are loaded on demand: the upcoming missions only need one or two, the history needs them all.
// The pages see no difference: common.js calls readStatic() instead of fetch('api/...').
(function () {
  const PER_PAGE = 50;
  const SLOT_MS = 30 * 60 * 1000; // a mission stays available for 30 min
  const VALIDITY_MS = 5 * 60 * 1000; // the index is not downloaded again more than once every 5 min
  const NO_MUTATOR = 'none';
  const NO_WARNING = 'none';
  // Row layout of a month file.
  const START = 0, BIOME = 1, MISSION = 2, SECONDARY = 3, LENGTH = 4, COMPLEXITY = 5,
    WARNINGS = 6, MUTATOR = 7, NAME = 8, SEASONS = 9;

  let index = null;
  let indexLoadedAt = 0;
  let months = new Map(); // "YYYY-MM" -> promise of a decoded month

  async function getJson(path) {
    const response = await fetch(path, { cache: 'no-cache' });
    if (!response.ok) throw new Error(response.status);
    return response.json();
  }

  async function loadIndex() {
    if (index && Date.now() - indexLoadedAt < VALIDITY_MS) return index;
    const fresh = await getJson('data/index.json');
    if (!index || fresh.generated_at !== index.generated_at) months = new Map(); // new data: reload months
    index = fresh;
    indexLoadedAt = Date.now();
    return index;
  }

  function loadMonth(month) {
    if (!months.has(month)) {
      const promise = getJson(`data/missions-${month}.json`).then((file) => {
        const [year, number] = month.split('-').map(Number);
        return { ...file, base: Date.UTC(year, number - 1, 1) };
      });
      promise.catch(() => months.delete(month)); // a failed load can be retried
      months.set(month, promise);
    }
    return months.get(month);
  }

  // Months of the index that overlap [fromMs, toMs].
  async function monthsBetween(fromMs, toMs) {
    const { months: list } = await loadIndex();
    const first = iso(new Date(fromMs)).slice(0, 7);
    const last = iso(new Date(toMs)).slice(0, 7);
    return Promise.all(list.map((m) => m.month).filter((m) => m >= first && m <= last).map(loadMonth));
  }

  async function allMonths() {
    const { months: list } = await loadIndex();
    return Promise.all(list.map((m) => loadMonth(m.month)));
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

  // Comma-separated list of accepted values, or null for everything.
  function choice(value) {
    const values = (value || '').split(',').filter(Boolean);
    return values.length ? values : null;
  }

  // Filters of a request, translated into a test on the compact rows of one month.
  function matcher(params, month) {
    const d = month.dictionaries;
    const indexes = (key, values) => (values ? new Set(values.map((v) => d[key].indexOf(v))) : null);
    const missionTypes = indexes('mission', choice(params.mission));
    const biomes = indexes('biome', choice(params.biome));
    // In the rows, -1 means "no mutator": an unknown mutator name must not be turned into it.
    const mutatorValues = choice(params.mutator);
    const mutators = mutatorValues && new Set();
    for (const v of mutatorValues || []) {
      const k = v === NO_MUTATOR ? -1 : d.mutator.indexOf(v);
      if (v === NO_MUTATOR || k !== -1) mutators.add(k);
    }
    // A mission matches the warning filter when it has at least one of the selected warnings, or all
    // of them with warning_mode=all. An unknown warning never matches (like instr() in api.py).
    const warningValues = choice(params.warning);
    const noWarning = !!warningValues && warningValues.includes(NO_WARNING);
    const named = (warningValues || []).filter((v) => v !== NO_WARNING).map((v) => d.warning.indexOf(v));
    const allWarnings = params.warning_mode === 'all';
    const warningTest = (r) => {
      const tests = named.map((k) => k !== -1 && r[WARNINGS].includes(k));
      if (noWarning) tests.push(r[WARNINGS].length === 0);
      return allWarnings ? tests.every(Boolean) : tests.some(Boolean);
    };
    const length = params.length ? integer(params.length) : null;
    const season = params.season ? d.season.indexOf(params.season) : null;
    return (r) => (!missionTypes || missionTypes.has(r[MISSION]))
      && (!biomes || biomes.has(r[BIOME]))
      && (!mutators || mutators.has(r[MUTATOR]))
      && (!warningValues || warningTest(r))
      && (length === null || r[LENGTH] === length)
      && (season === null || r[SEASONS].includes(season));
  }

  function startMs(month, r) {
    return month.base + r[START] * 60000;
  }

  // Full mission object, with the same fields as the API.
  function decode(month, r) {
    const d = month.dictionaries;
    return {
      start: iso(new Date(startMs(month, r))),
      biome: d.biome[r[BIOME]],
      mission: d.mission[r[MISSION]],
      secondary: d.secondary[r[SECONDARY]],
      length: r[LENGTH],
      complexity: r[COMPLEXITY],
      warnings: r[WARNINGS].map((w) => d.warning[w]),
      mutator: r[MUTATOR] === -1 ? null : d.mutator[r[MUTATOR]],
      name: d.name[r[NAME]],
      seasons: r[SEASONS].map((s) => d.season[s]),
    };
  }

  async function upcoming(params) {
    const hours = Math.min(integer(params.hours, 24), 24 * 14);
    const now = Date.now();
    const after = now - SLOT_MS;
    const until = now + hours * 3600 * 1000;
    const missions = [];
    for (const month of await monthsBetween(after, until)) {
      const ok = matcher(params, month);
      for (const r of month.rows) {
        const t = startMs(month, r);
        if (t > after && t <= until && ok(r)) missions.push(decode(month, r));
      }
    }
    return { missions }; // the rows are already in the API's order: start, biome, source order
  }

  // Like current_season() in api.py: the forced season, otherwise the most recent season found
  // in the missions of the last two days and the upcoming ones.
  async function currentSeason(known) {
    const forced = (window.DRG_CONFIG || {}).currentSeason;
    if (forced) return forced;
    const since = Date.now() - 2 * 86400 * 1000;
    let best = -1;
    for (const month of await monthsBetween(since, Date.parse(known) || since)) {
      for (const r of month.rows) {
        if (startMs(month, r) < since) continue;
        for (const s of r[SEASONS]) {
          const name = month.dictionaries.season[s];
          if (/^s\d+$/.test(name)) best = Math.max(best, Number(name.slice(1)));
        }
      }
    }
    return best >= 0 ? `s${best}` : 's0';
  }

  async function filters() {
    const i = await loadIndex();
    return {
      missions: i.missions,
      biomes: i.biomes,
      mutators: i.mutators,
      warnings: i.warnings,
      seasons: i.seasons,
      current_season: await currentSeason(i.known_until),
      archive_since: i.archive_since,
      known_until: i.known_until,
    };
  }

  async function search(params) {
    const now = Date.now();
    const period = params.period || 'past';
    const page = Math.max(1, integer(params.page, 1));
    const loaded = await allMonths();

    // The matching rows; their rank (n) in the overall order breaks ties like the database's id does.
    const found = [];
    let n = 0;
    for (const month of loaded) {
      const ok = matcher(params, month);
      for (const r of month.rows) {
        const t = startMs(month, r);
        const inPeriod = period === 'past' ? t <= now : period === 'upcoming' ? t > now : true;
        if (inPeriod && ok(r)) found.push({ month, r, t, biome: month.dictionaries.biome[r[BIOME]], n });
        n += 1;
      }
    }
    // ORDER BY start (DESC or ASC), biome, id (DESC or ASC), like api.py.
    const descending = period !== 'upcoming';
    found.sort((a, b) => {
      if (a.t !== b.t) return descending ? b.t - a.t : a.t - b.t;
      if (a.biome !== b.biome) return compare(a.biome, b.biome);
      return descending ? b.n - a.n : a.n - b.n;
    });

    return {
      total: found.length,
      page,
      per_page: PER_PAGE,
      missions: found.slice((page - 1) * PER_PAGE, page * PER_PAGE).map((f) => decode(f.month, f.r)),
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
