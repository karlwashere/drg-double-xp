#!/usr/bin/env python3
"""Archives the missions from doublexp.net (all of them, whatever their mutator) into a SQLite database.

- First run: loads the whole available history (since ARCHIVE_START).
- Later runs: reloads yesterday and the upcoming days (forecasts can change after a game
  update); past days that are already archived are never downloaded again.
- A database made by an older version, which only kept the Double XP missions, is upgraded in
  place: new columns are added and every day is downloaded again to get the other missions.

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
    seed        INTEGER NOT NULL,  -- generation seed, not unique either
    mutator     TEXT,              -- "Double XP", "Gold Rush"... NULL when the mission has none
    source_id   INTEGER            -- the mission's id at doublexp.net
);
-- Uniqueness comes from every day always being replaced as a whole. Within a day, rows keep the
-- order of the source file (id), which breaks ties when sorting.
CREATE INDEX IF NOT EXISTS missions_start ON missions (start);
CREATE INDEX IF NOT EXISTS missions_day ON missions (day);
CREATE INDEX IF NOT EXISTS missions_mutator_start ON missions (mutator, start);

CREATE TABLE IF NOT EXISTS archived_days (
    day           TEXT PRIMARY KEY,
    loaded_at     TEXT NOT NULL,
    mission_count INTEGER NOT NULL
);
"""

def upgrade_schema(db):
    """Upgrades a database that only kept the Double XP missions (no mutator column).

    Its rows are all Double XP missions, so they are marked as such right away (the site keeps
    working), and every day is forgotten as "archived" so that the next run downloads them all again.
    """
    columns = {row[1] for row in db.execute("PRAGMA table_info(missions)")}
    if not columns or "mutator" in columns:
        return False
    with db:
        db.execute("ALTER TABLE missions ADD COLUMN mutator TEXT")
        db.execute("ALTER TABLE missions ADD COLUMN source_id INTEGER")
        db.execute("UPDATE missions SET mutator = 'Double XP'")
        db.execute("DELETE FROM archived_days")
    return True


def download(day):
    request = urllib.request.Request(SOURCE.format(day=day), headers={"User-Agent": "drg-double-xp"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def all_missions(data):
    """(slot start, biome, mission) for every mission of a source file, in the file's order."""
    for start, slot in data.items():
        if not isinstance(slot, dict) or "Biomes" not in slot:
            continue  # auxiliary keys: dailyDeal, ver
        for biome, missions in slot["Biomes"].items():
            for m in missions:
                yield start, biome, m


def archive_day(db, day, data):
    rows = [
        (
            start, day, biome, m["PrimaryObjective"], m["SecondaryObjective"],
            int(m["Length"]), int(m["Complexity"]),
            json.dumps(m.get("MissionWarnings") or [], ensure_ascii=False),
            m["CodeName"], json.dumps(m.get("included_in") or []), int(m["Seed"]),
            m.get("MissionMutator") or None, m.get("id"),
        )
        for start, biome, m in all_missions(data)
    ]
    with db:  # one transaction per day: a day is never half archived
        db.execute("DELETE FROM missions WHERE day = ?", (day,))
        db.executemany(
            "INSERT INTO missions (start, day, biome, mission, secondary, length, complexity,"
            " warnings, name, seasons, seed, mutator, source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
    if upgrade_schema(db):
        print("Database upgraded to keep every mission: all days are downloaded again")
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
    print(f"{loaded} days loaded ({total} missions); {count} missions in the database")
    db.close()


if __name__ == "__main__":
    main()
