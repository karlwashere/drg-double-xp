// Site configuration.
//
//   mode "api"    : the api/ address answers (Python API from api/api.py, self-hosted).
//   mode "static" : no server, everything is read from data/missions.json (GitHub Pages).
//                   This file is then replaced at build time by tools/build_static.py.
//
// currentSeason is only used in "static" mode, to force the current season (in "api" mode it comes
// from DRG_CURRENT_SEASON). Empty: deduced from the data, like the API does.
window.DRG_CONFIG = { mode: 'api', currentSeason: '' };
