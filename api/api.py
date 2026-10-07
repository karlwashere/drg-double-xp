#!/usr/bin/env python3
"""Read-only API on the missions database.

GET /api/upcoming?hours=24&...  missions not finished yet, starting within the next N hours
GET /api/filters                possible filter values + current season
GET /api/missions?...&period=&page=

Both mission lists accept the same filters: mission=, biome=, mutator=, length=, season=.
mission, biome and mutator accept several values separated by commas; mutator=none selects
the missions without a mutator.
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.environ.get("DRG_DB", "/data/drg.db")
# Forced current season; when empty it is deduced from the data (see current_season).
FORCED_SEASON = os.environ.get("DRG_CURRENT_SEASON", "")
SLOT_DURATION = timedelta(minutes=30)
PER_PAGE = 50
NO_MUTATOR = "none"
FILTERS_CACHE_SECONDS = 300  # the filter values only change with a new collection


@contextmanager
def connection():
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def as_dict(row):
    m = dict(row)
    m["warnings"] = json.loads(m["warnings"])
    m["seasons"] = json.loads(m["seasons"])
    del m["id"], m["day"]
    return m


COLUMNS = "id, start, day, biome, mission, secondary, length, complexity, warnings, mutator, name, seasons"


def choice(params, key):
    return [v for v in params.get(key, "").split(",") if v]


def filter_conditions(params):
    """SQL conditions for the filters shared by both mission lists."""
    conditions, values = [], []
    for key in ("mission", "biome"):  # comma-separated lists
        selected = choice(params, key)
        if selected:
            conditions.append(f"{key} IN ({','.join('?' * len(selected))})")
            values.extend(selected)
    mutators = choice(params, "mutator")
    if mutators:
        named = [m for m in mutators if m != NO_MUTATOR]
        parts = [f"mutator IN ({','.join('?' * len(named))})"] if named else []
        if NO_MUTATOR in mutators:
            parts.append("mutator IS NULL")
        conditions.append(f"({' OR '.join(parts)})")
        values.extend(named)
    if params.get("length"):
        conditions.append("length = ?")
        values.append(int(params["length"]))
    if params.get("season"):
        # seasons is a JSON list of strings: looking for the quoted value is an exact match.
        conditions.append("instr(seasons, ?) > 0")
        values.append(json.dumps(params["season"]))
    return conditions, values


def upcoming(params):
    hours = min(int(params.get("hours", "24")), 24 * 14)
    now = datetime.now(timezone.utc)
    conditions, values = filter_conditions(params)
    conditions = ["start > ?", "start <= ?"] + conditions
    values = [iso(now - SLOT_DURATION), iso(now + timedelta(hours=hours))] + values
    with connection() as db:
        rows = db.execute(
            f"SELECT {COLUMNS} FROM missions WHERE {' AND '.join(conditions)} ORDER BY start, biome, id",
            values,
        ).fetchall()
    return {"missions": [as_dict(r) for r in rows]}


def current_season(db):
    """Most recent season found in the missions of the last two days and the upcoming ones."""
    if FORCED_SEASON:
        return FORCED_SEASON
    since = iso(datetime.now(timezone.utc) - timedelta(days=2))
    seasons = [r[0] for r in db.execute(
        "SELECT DISTINCT j.value FROM missions, json_each(missions.seasons) j WHERE start >= ?", (since,))]
    seasons = [s for s in seasons if s[1:].isdigit()]
    return max(seasons, key=lambda s: int(s[1:]), default="s0")


_filters_cache = {"at": 0.0, "value": None}


def filters(_params):
    if _filters_cache["value"] and time.monotonic() - _filters_cache["at"] < FILTERS_CACHE_SECONDS:
        return _filters_cache["value"]
    with connection() as db:
        missions = [r[0] for r in db.execute("SELECT DISTINCT mission FROM missions ORDER BY 1")]
        biomes = [r[0] for r in db.execute("SELECT DISTINCT biome FROM missions ORDER BY 1")]
        mutators = [r[0] for r in db.execute(
            "SELECT DISTINCT mutator FROM missions WHERE mutator IS NOT NULL ORDER BY 1")]
        seasons = [r[0] for r in db.execute(
            "SELECT DISTINCT j.value FROM (SELECT DISTINCT seasons FROM missions) s, json_each(s.seasons) j ORDER BY 1")]
        first, last = db.execute("SELECT MIN(start), MAX(start) FROM missions").fetchone()
        season = current_season(db)
    value = {"missions": missions, "biomes": biomes, "mutators": mutators, "seasons": seasons,
             "current_season": season, "archive_since": first, "known_until": last}
    _filters_cache.update(at=time.monotonic(), value=value)
    return value


def search(params):
    conditions, values = filter_conditions(params)
    now = iso(datetime.now(timezone.utc))
    period = params.get("period", "past")
    if period == "past":
        conditions.append("start <= ?")
        values.append(now)
        order = "start DESC, biome, id DESC"
    elif period == "upcoming":
        conditions.append("start > ?")
        values.append(now)
        order = "start ASC, biome, id"
    else:
        order = "start DESC, biome, id DESC"

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    page = max(1, int(params.get("page", "1")))
    with connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM missions {where}", values).fetchone()[0]
        rows = db.execute(
            f"SELECT {COLUMNS} FROM missions {where} ORDER BY {order} LIMIT ? OFFSET ?",
            values + [PER_PAGE, (page - 1) * PER_PAGE],
        ).fetchall()
    return {"total": total, "page": page, "per_page": PER_PAGE, "missions": [as_dict(r) for r in rows]}


ROUTES = {"/api/upcoming": upcoming, "/api/filters": filters, "/api/missions": search}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        action = ROUTES.get(url.path)
        if not action:
            return self.respond(404, {"error": "not found"})
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            self.respond(200, action(params))
        except ValueError:
            self.respond(400, {"error": "invalid parameter"})
        except Exception as e:
            self.log_error("error: %r", e)
            self.respond(500, {"error": "internal error"})

    def respond(self, code, content):
        body = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
