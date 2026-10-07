#!/usr/bin/env python3
"""Archives the Double XP missions from doublexp.net into a SQLite database.

- First run: loads the whole available history (since ARCHIVE_START).
- Later runs: reloads yesterday and the upcoming days (forecasts can change after a game
  update); past days that are already archived are never downloaded again.

Usage: collect.py [database_path]
"""
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

SOURCE = "https://doublexp.net/static/json/bulkmissions/{day}.json"
ARCHIVE_START = date(2026, 5, 8)  # oldest day still published by doublexp.net
DAYS_AHEAD = 14
DAYS_TO_REFRESH = 1  # yesterday is still reloaded, just in case

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id          INTEGER PRIMARY KEY,
    start       TEXT NOT NULL,     -- start of the 30-minute slot, UTC ISO 8601
    day         TEXT NOT NULL,     -- UTC day of the source file
    biome       TEXT NOT NULL,
    mission     TEXT NOT NULL,
    secondary   TEXT NOT NULL,
    length      INTEGER NOT NULL,
    complexity  INTEGER NOT NULL,
    warnings    TEXT NOT NULL,     -- JSON list
    name        TEXT NOT NULL,     -- code name, not unique: two seasons can share it
    seasons     TEXT NOT NULL,     -- JSON list, e.g. ["s0","s1","s3","s6"]
    seed        INTEGER NOT NULL   -- generation seed, not unique either
);
-- No reliable natural key (name and seed can be shared between seasons): uniqueness comes
-- from every day always being replaced as a whole.
CREATE INDEX IF NOT EXISTS missions_start ON missions (start);
CREATE INDEX IF NOT EXISTS missions_day ON missions (day);

CREATE TABLE IF NOT EXISTS archived_days (
    day           TEXT PRIMARY KEY,
    loaded_at     TEXT NOT NULL,
    mission_count INTEGER NOT NULL
);
"""

def download(day):
    request = urllib.request.Request(SOURCE.format(day=day), headers={"User-Agent": "drg-double-xp"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def double_xp(data):
    for start, slot in data.items():
        if not isinstance(slot, dict) or "Biomes" not in slot:
            continue  # auxiliary keys: dailyDeal, ver
        for biome, missions in slot["Biomes"].items():
            for m in missions:
                if m.get("MissionMutator") == "Double XP":
                    yield start, biome, m


def archive_day(db, day, data):
    rows = [
        (
            start, day, biome, m["PrimaryObjective"], m["SecondaryObjective"],
            int(m["Length"]), int(m["Complexity"]),
            json.dumps(m.get("MissionWarnings") or [], ensure_ascii=False),
            m["CodeName"], json.dumps(m.get("included_in") or []), int(m["Seed"]),
        )
        for start, biome, m in double_xp(data)
    ]
    with db:  # one transaction per day: a day is never half archived
        db.execute("DELETE FROM missions WHERE day = ?", (day,))
        db.executemany(
            "INSERT INTO missions (start, day, biome, mission, secondary, length, complexity,"
            " warnings, name, seasons, seed) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        db.execute(
            "INSERT OR REPLACE INTO archived_days VALUES (?, ?, ?)",
            (day, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), len(rows)),
        )
    return len(rows)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "drg.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)

    today = datetime.now(timezone.utc).date()
    already = {r[0] for r in db.execute("SELECT day FROM archived_days")}
    frozen_before = today - timedelta(days=DAYS_TO_REFRESH)

    day = ARCHIVE_START
    total, loaded = 0, 0
    while day <= today + timedelta(days=DAYS_AHEAD):
        key = day.isoformat()
        if not (key in already and day < frozen_before):
            data = download(key)
            if data is None:
                print(f"{key}: not published yet")
            else:
                total += archive_day(db, key, data)
                loaded += 1
                time.sleep(0.5)  # stay polite with doublexp.net
        day += timedelta(days=1)

    count = db.execute("SELECT COUNT(*) FROM missions").fetchone()[0]
    print(f"{loaded} days loaded ({total} missions); {count} Double XP missions in the database")
    db.close()


if __name__ == "__main__":
    main()
