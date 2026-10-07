"""Tests of the collection and build tools (standard library only).

Run: python -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "api"))

import api  # noqa: E402
import build_static  # noqa: E402
import collect  # noqa: E402
import collect_static  # noqa: E402
import sqlite_to_days  # noqa: E402

# A minimal source file, in the doublexp.net format (bulkmissions/YYYY-MM-DD.json).
SOURCE = {
    "2026-10-06T17:00:00Z": {
        "Biomes": {
            "Salt Pits": [
                {"MissionMutator": "Double XP", "PrimaryObjective": "Escort Duty", "SecondaryObjective": "Fester Fleas",
                 "Length": 2, "Complexity": 3, "MissionWarnings": ["Pit Jaw Colony"], "CodeName": "Gutless Enclosure",
                 "included_in": ["s0", "s6"], "Seed": 11},
                {"MissionMutator": "Other mutator", "PrimaryObjective": "Deep Scan", "SecondaryObjective": "Ebonuts",
                 "Length": 1, "Complexity": 1, "CodeName": "Ignored", "Seed": 12},
            ],
            "Azure Weald": [
                {"MissionMutator": "Double XP", "PrimaryObjective": "Egg Hunt", "SecondaryObjective": "Fossils",
                 "Length": 3, "Complexity": 2, "MissionWarnings": [], "CodeName": "Duplicitous Bottom",
                 "included_in": ["s3"], "Seed": 13},
            ],
        }
    },
    "2026-10-06T16:30:00Z": {
        "Biomes": {
            "Magma Core": [
                {"MissionMutator": "Double XP", "PrimaryObjective": "Elimination", "SecondaryObjective": "Gunk Seeds",
                 "Length": 2, "Complexity": 2, "MissionWarnings": None, "CodeName": "No warnings",
                 "included_in": None, "Seed": 14},
            ]
        }
    },
    "dailyDeal": {"some": "thing"},  # auxiliary keys of the source file: ignored
    "ver": 5,
}


class DayMissions(unittest.TestCase):
    def test_keeps_only_double_xp_and_ignores_auxiliary_keys(self):
        names = [m["CodeName"] for _, _, m in collect.double_xp(SOURCE)]
        self.assertEqual(sorted(names), ["Duplicitous Bottom", "Gutless Enclosure", "No warnings"])

    def test_format_and_order_by_slot_then_biome(self):
        rows = collect_static.day_missions(SOURCE)
        self.assertEqual([(m["start"], m["biome"]) for m in rows], [
            ("2026-10-06T16:30:00Z", "Magma Core"),
            ("2026-10-06T17:00:00Z", "Azure Weald"),
            ("2026-10-06T17:00:00Z", "Salt Pits"),
        ])
        self.assertEqual(list(rows[2]), [
            "start", "biome", "mission", "secondary", "length", "complexity", "warnings", "name", "seasons"])
        self.assertEqual(rows[2]["warnings"], ["Pit Jaw Colony"])
        self.assertEqual(rows[0]["warnings"], [])  # MissionWarnings missing or null -> empty list
        self.assertEqual(rows[0]["seasons"], [])   # included_in missing or null -> empty list


class DayFiles(unittest.TestCase):
    def test_idempotent_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = collect_static.day_missions(SOURCE)
            self.assertTrue(collect_static.write_day(tmp, "2026-10-06", rows))
            self.assertFalse(collect_static.write_day(tmp, "2026-10-06", rows))
            self.assertEqual(json.loads((Path(tmp) / "2026-10-06.json").read_text(encoding="utf-8")), rows)
            rows[0]["length"] = 1
            self.assertTrue(collect_static.write_day(tmp, "2026-10-06", rows))

    def test_day_without_missions(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(collect_static.write_day(tmp, "2026-10-07", []))
            self.assertEqual((Path(tmp) / "2026-10-07.json").read_text(encoding="utf-8"), "[]\n")

    def test_one_mission_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            collect_static.write_day(tmp, "2026-10-06", collect_static.day_missions(SOURCE))
            text = (Path(tmp) / "2026-10-06.json").read_text(encoding="utf-8")
            self.assertEqual(len(text.splitlines()), 3 + 2)  # 3 missions + brackets


class FromSqlite(unittest.TestCase):
    def test_export_identical_to_the_static_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = sqlite3.connect(tmp / "drg.db")
            db.executescript(collect.SCHEMA)
            collect.archive_day(db, "2026-10-06", SOURCE)
            collect.archive_day(db, "2026-10-07", {"ver": 5})  # archived day without missions
            db.close()

            with contextlib.redirect_stdout(io.StringIO()):
                sqlite_to_days.main([str(tmp / "drg.db"), str(tmp / "from_sqlite")])
            collect_static.write_day(tmp, "expected", collect_static.day_missions(SOURCE))

            self.assertEqual(
                (tmp / "from_sqlite" / "2026-10-06.json").read_text(encoding="utf-8"),
                (tmp / "expected.json").read_text(encoding="utf-8"))
            self.assertEqual((tmp / "from_sqlite" / "2026-10-07.json").read_text(encoding="utf-8"), "[]\n")


class StaticSiteBuild(unittest.TestCase):
    def prepare(self, tmp):
        days = tmp / "days"
        days.mkdir()
        collect_static.write_day(days, "2026-10-07", [
            {"start": "2026-10-07T01:00:00Z", "biome": "Salt Pits", "mission": "Egg Hunt", "secondary": "x",
             "length": 1, "complexity": 1, "warnings": [], "name": "n", "seasons": ["s6"]}])
        collect_static.write_day(days, "2026-10-06", collect_static.day_missions(SOURCE))
        site = tmp / "site"
        site.mkdir()
        (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (site / "config.js").write_text("window.DRG_CONFIG = { mode: 'api' };", encoding="utf-8")
        return days, site

    def test_static_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            days, site = self.prepare(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                build_static.main(["--days", str(days), "--site", str(site), "--output", str(tmp / "dist"),
                                   "--season", "s7"])
            dist = tmp / "dist"
            self.assertTrue((dist / "index.html").exists())
            config = (dist / "config.js").read_text(encoding="utf-8")
            self.assertIn('"mode": "static"', config)
            self.assertIn('"currentSeason": "s7"', config)
            missions = json.loads((dist / "data" / "missions.json").read_text(encoding="utf-8"))["missions"]
            self.assertEqual([m["start"] for m in missions], sorted(m["start"] for m in missions))
            self.assertEqual(len(missions), 4)  # the 3 of SOURCE + the one of the 7th, in chronological order

    def test_season_deduced_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            days, site = self.prepare(tmp)
            with contextlib.redirect_stdout(io.StringIO()), mock.patch.dict(os.environ, {"DRG_CURRENT_SEASON": ""}):
                build_static.main(["--days", str(days), "--site", str(site), "--output", str(tmp / "dist")])
            self.assertIn('"currentSeason": ""', (tmp / "dist" / "config.js").read_text(encoding="utf-8"))

    def test_invalid_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            days, site = self.prepare(tmp)
            with self.assertRaises(SystemExit):
                build_static.main(["--days", str(days), "--site", str(site), "--output", str(tmp / "dist"),
                                   "--season", "six"])

    def test_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "empty").mkdir()
            (tmp / "site").mkdir()
            with self.assertRaises(SystemExit):
                build_static.main(["--days", str(tmp / "empty"), "--site", str(tmp / "site"),
                                   "--output", str(tmp / "dist")])


class Api(unittest.TestCase):
    """api.py on a small database: multiple values per filter and deduced current season."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "drg.db"
        db = sqlite3.connect(path)
        db.executescript(collect.SCHEMA)
        collect.archive_day(db, "2026-10-06", SOURCE)
        # A recent mission of season 7: it becomes the current season.
        soon = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00Z")
        collect.archive_day(db, soon[:10], {soon: {"Biomes": {"Hollow Bough": [
            {"MissionMutator": "Double XP", "PrimaryObjective": "Deep Scan", "SecondaryObjective": "x",
             "Length": 1, "Complexity": 1, "CodeName": "Recent", "included_in": ["s0", "s7"], "Seed": 1}]}}})
        db.close()
        patches = [mock.patch.object(api, "DB_PATH", str(path)), mock.patch.object(api, "FORCED_SEASON", "")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def biomes(self, **params):
        result = api.search({"period": "all", **params})
        return sorted(m["biome"] for m in result["missions"])

    def test_several_biomes(self):
        self.assertEqual(self.biomes(biome="Salt Pits,Magma Core"), ["Magma Core", "Salt Pits"])
        self.assertEqual(self.biomes(biome="Salt Pits"), ["Salt Pits"])
        self.assertEqual(len(self.biomes(biome="")), 4)  # empty: no filter

    def test_several_mission_types_combined_with_a_biome(self):
        self.assertEqual(self.biomes(mission="Egg Hunt,Elimination"), ["Azure Weald", "Magma Core"])
        self.assertEqual(self.biomes(mission="Egg Hunt,Elimination", biome="Magma Core"), ["Magma Core"])

    def test_current_season_deduced_from_recent_missions(self):
        self.assertEqual(api.filters({})["current_season"], "s7")

    def test_forced_current_season(self):
        with mock.patch.object(api, "FORCED_SEASON", "s6"):
            self.assertEqual(api.filters({})["current_season"], "s6")


if __name__ == "__main__":
    unittest.main()
