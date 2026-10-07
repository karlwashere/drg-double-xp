#!/usr/bin/env python3
"""Exports a SQLite database made by collect.py to the JSON files of the static mode.

Used once to move from a server hosting (SQLite) to GitHub Pages without losing the archive,
before the first run of the workflow.

Usage: sqlite_to_days.py drg.db [days_folder]   (default: data/days)
"""
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from collect_static import write_day


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit(__doc__)
    db = sqlite3.connect(f"file:{argv[0]}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    folder = Path(argv[1]) if len(argv) > 1 else Path("data/days")
    folder.mkdir(parents=True, exist_ok=True)

    by_day = defaultdict(list)
    for row in db.execute("SELECT * FROM missions ORDER BY id"):
        by_day[row["day"]].append({
            "start": row["start"],
            "biome": row["biome"],
            "mission": row["mission"],
            "secondary": row["secondary"],
            "length": row["length"],
            "complexity": row["complexity"],
            "warnings": json.loads(row["warnings"]),
            "mutator": row["mutator"],
            "name": row["name"],
            "seasons": json.loads(row["seasons"]),
            "seed": row["seed"],
            "source_id": row["source_id"],
        })
    # Archived days without any mission give an empty file, like collect_static.py.
    for (day,) in db.execute("SELECT day FROM archived_days"):
        by_day.setdefault(day, [])

    written = 0
    for day, rows in sorted(by_day.items()):
        rows.sort(key=lambda m: (m["start"], m["biome"]))
        written += write_day(folder, day, rows)
    print(f"{len(by_day)} days, {written} files written in {folder}/")


if __name__ == "__main__":
    main()
