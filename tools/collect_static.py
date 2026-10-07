#!/usr/bin/env python3
"""Archives the Double XP missions from doublexp.net into JSON files, one per day.

This is the "no database" version of collect.py, used by the GitHub Pages mode: the files
data/days/YYYY-MM-DD.json are versioned by git, which keeps the history from one (ephemeral)
GitHub Actions run to the next.

- Past days that are already archived are never downloaded again.
- Yesterday and the next DAYS_AHEAD days are reloaded (forecasts can change after a game update).
- A file is only rewritten when its content changes: no pointless commits.

Usage: collect_static.py [days_folder]   (default: data/days)
"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collect import ARCHIVE_START, DAYS_AHEAD, DAYS_TO_REFRESH, double_xp, download


def day_missions(data):
    """The Double XP missions of a source file, in the API format (no id, no day)."""
    rows = [
        {
            "start": start,
            "biome": biome,
            "mission": m["PrimaryObjective"],
            "secondary": m["SecondaryObjective"],
            "length": int(m["Length"]),
            "complexity": int(m["Complexity"]),
            "warnings": m.get("MissionWarnings") or [],
            "name": m["CodeName"],
            "seasons": m.get("included_in") or [],
        }
        for start, biome, m in double_xp(data)
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


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/days")
    folder.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date()
    frozen_before = today - timedelta(days=DAYS_TO_REFRESH)

    day = ARCHIVE_START
    downloaded, changed = 0, 0
    while day <= today + timedelta(days=DAYS_AHEAD):
        key = day.isoformat()
        if not ((folder / f"{key}.json").exists() and day < frozen_before):
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
