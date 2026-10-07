#!/usr/bin/env python3
"""Assembles the static site (GitHub Pages) into an output folder.

Produced content:
  - a copy of site/;
  - config.js in "static" mode (current season, README link, visit statistics);
  - the missions of data/days/*.json, in a compact format split by month:
      data/index.json            months available, filter values, archive bounds;
      data/missions-YYYY-MM.json one file per month (see month_file), loaded on demand by static-api.js.

Usage: build_static.py [--season s6] [--days data/days] [--site site] [--output dist]
The season forced as current comes from the DRG_CURRENT_SEASON environment variable. Without it, the
site deduces the current season from the data (the most recent season of the recent missions).
The "About" link points to the README of the repository being built (GITHUB_REPOSITORY, set by GitHub
Actions), or to --readme-url. Visit statistics are enabled by a GoatCounter site code (DRG_GOATCOUNTER).
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# Fields of a mission used by the site (the archive also keeps "seed" and "source_id").
TEXT_FIELDS = ("biome", "mission", "secondary", "mutator", "name")
LIST_FIELDS = {"warnings": "warning", "seasons": "season"}


def month_file(missions):
    """Compact form of one month's missions: each text value is stored once in a dictionary and the
    missions refer to it by index. A row is
        [minutes since the start of the month, biome, mission, secondary, length, complexity,
         [warnings], mutator (-1: none), name, [seasons]]
    and rows keep the order of the input (start, biome, then the source file's order)."""
    month_start = datetime.strptime(missions[0]["start"][:7], "%Y-%m").replace(tzinfo=timezone.utc)
    dictionaries = {key: {} for key in (*TEXT_FIELDS, *LIST_FIELDS.values())}

    def index(key, value):
        return dictionaries[key].setdefault(value, len(dictionaries[key]))

    rows = []
    for m in missions:
        start = datetime.strptime(m["start"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        rows.append([
            int((start - month_start).total_seconds() // 60),
            index("biome", m["biome"]), index("mission", m["mission"]), index("secondary", m["secondary"]),
            m["length"], m["complexity"],
            [index("warning", w) for w in m["warnings"]],
            -1 if m.get("mutator") is None else index("mutator", m["mutator"]),
            index("name", m["name"]),
            [index("season", s) for s in m["seasons"]],
        ])
    return {"month": missions[0]["start"][:7],
            "dictionaries": {key: list(values) for key, values in dictionaries.items()},
            "rows": rows}


def write_data(folder, missions):
    """Writes index.json and the month files. Returns the index."""
    folder.mkdir()
    by_month = {}
    for m in missions:
        by_month.setdefault(m["start"][:7], []).append(m)
    for month, month_missions in by_month.items():
        (folder / f"missions-{month}.json").write_text(
            json.dumps(month_file(month_missions), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    seasons = sorted({s for m in missions for s in m["seasons"]})
    index = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "months": [{"month": month, "count": len(ms)} for month, ms in by_month.items()],
        "missions": sorted({m["mission"] for m in missions}),
        "biomes": sorted({m["biome"] for m in missions}),
        "mutators": sorted({m["mutator"] for m in missions if m.get("mutator") is not None}),
        "seasons": seasons,
        "archive_since": missions[0]["start"],
        "known_until": missions[-1]["start"],
    }
    (folder / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return index


def read_missions(days_folder):
    missions = []
    for file in sorted(Path(days_folder).glob("*.json")):
        missions.extend(json.loads(file.read_text(encoding="utf-8")))
    missions.sort(key=lambda m: (m["start"], m["biome"]))  # stable sort: the file order breaks ties
    return missions


def default_readme_url():
    repository = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/name" inside GitHub Actions
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repository}#readme" if repository else ""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", default=os.environ.get("DRG_CURRENT_SEASON", ""))
    parser.add_argument("--days", default="data/days")
    parser.add_argument("--site", default="site")
    parser.add_argument("--output", default="dist")
    parser.add_argument("--readme-url", default=default_readme_url())
    parser.add_argument("--goatcounter", default=os.environ.get("DRG_GOATCOUNTER", ""))
    args = parser.parse_args(argv)

    if args.season and not re.fullmatch(r"s\d+", args.season):
        sys.exit(f"Invalid season: {args.season!r} (expected: s followed by a number, e.g. s6)")
    if args.goatcounter and not re.fullmatch(r"[a-z0-9-]+", args.goatcounter):
        sys.exit(f"Invalid GoatCounter code: {args.goatcounter!r} (expected the code of yourcode.goatcounter.com)")
    if args.readme_url and not args.readme_url.startswith("https://"):
        sys.exit(f"Invalid README address: {args.readme_url!r} (expected https://...)")

    output = Path(args.output)
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(args.site, output)

    config = {"mode": "static", "currentSeason": args.season, "readmeUrl": args.readme_url,
              "goatcounter": args.goatcounter}
    (output / "config.js").write_text(
        "// Generated by tools/build_static.py: GitHub Pages mode.\n"
        f"window.DRG_CONFIG = {json.dumps(config)};\n",
        encoding="utf-8",
    )

    missions = read_missions(args.days)
    if not missions:
        sys.exit(f"No mission found in {args.days}: run collect_static.py first")
    index = write_data(output / "data", missions)

    # A web server must be able to read everything, whatever the permissions of the source files.
    for path in [output, *output.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)

    season = args.season or "deduced from the data"
    print(f"{len(missions)} missions in {len(index['months'])} month files, from {missions[0]['start']} "
          f"to {missions[-1]['start']}, season {season} -> {output}/")


if __name__ == "__main__":
    main()
