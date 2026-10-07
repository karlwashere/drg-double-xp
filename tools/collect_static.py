#!/usr/bin/env python3
"""Archives the missions from doublexp.net (all of them, whatever their mutator) into JSON files, one per day.

This is the "no database" version of collect.py, used by the GitHub Pages mode: the files
data/days/YYYY-MM-DD.json are versioned by git, which keeps the history from one (ephemeral)
GitHub Actions run to the next.

- Past days that are already archived are never downloaded again.
- Yesterday and the next DAYS_AHEAD days are reloaded (forecasts can change after a game update).
- A file is only rewritten when its content changes: no pointless commits.
- A file written by an older version (Double XP missions only, no "mutator" field) is downloaded again.

Usage: collect_static.py [days_folder]   (default: data/days)
"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collect import ARCHIVE_START, DAYS_AHEAD, DAYS_TO_REFRESH, all_missions, download


def day_missions(data):
    """Every mission of a source file. The site uses the fields up to "seasons"; "seed" and
    "source_id" (the id at doublexp.net) are kept so that the archive loses nothing."""
    rows = [
        {
            "start": start,
            "biome": biome,
            "mission": m["PrimaryObjective"],
            "secondary": m["SecondaryObjective"],
            "length": int(m["Length"]),
            "complexity": int(m["Complexity"]),
            "warnings": m.get("MissionWarnings") or [],
            "mutator": m.get("MissionMutator") or None,
            "name": m["CodeName"],
            "seasons": m.get("included_in") or [],
            "seed": int(m["Seed"]),
            "source_id": m.get("id"),
        }
        for start, biome, m in all_missions(data)
    ]
    rows.sort(key=lambda m: (m["start"], m["biome"]))  # stable sort: the original order breaks ties
    return rows


def write_day(folder, day, rows):
    """Writes the day's file (one mission per line, for readable git diffs). Returns True if it changed."""
    body = ",\n".join(json.dumps(m, ensure_ascii=False, separators=(",", ":")) for m in rows)
    text = f"[\n{body}\n]\n" if rows else "[]\n"
    path = Path(folder) / f"{day}.json"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def up_to_date(path):
    """True if the day's file exists and has the current format (with the mutator of each mission)."""
    return path.exists() and '"mutator":' in path.read_text(encoding="utf-8")


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/days")
    folder.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date()
    frozen_before = today - timedelta(days=DAYS_TO_REFRESH)

    day = ARCHIVE_START
    downloaded, changed = 0, 0
    while day <= today + timedelta(days=DAYS_AHEAD):
        key = day.isoformat()
        if not (up_to_date(folder / f"{key}.json") and day < frozen_before):
            data = download(key)
            if data is None:
                print(f"{key}: not published yet")
            else:
                downloaded += 1
                if write_day(folder, key, day_missions(data)):
                    changed += 1
                    print(f"{key}: updated")
                time.sleep(0.5)  # stay polite with doublexp.net
        day += timedelta(days=1)

    print(f"{downloaded} days downloaded, {changed} files changed")


if __name__ == "__main__":
    main()
