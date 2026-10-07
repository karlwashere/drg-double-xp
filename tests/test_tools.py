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
                 "Length": 1, "Complexity": 1, "CodeName": "Other One", "Seed": 12},
            ],
            "Azure Weald": [
                {"MissionMutator": "Double XP", "PrimaryObjective": "Egg Hunt", "SecondaryObjective": "Fossils",
                 "Length": 3, "Complexity": 2, "MissionWarnings": [], "CodeName": "Duplicitous Bottom",
                 "included_in": ["s3"], "Seed": 13, "id": 7},
                {"PrimaryObjective": "Mining Expedition", "SecondaryObjective": "Fossils",  # no mutator
                 "Length": 1, "Complexity": 1, "CodeName": "Plain One", "included_in": ["s0"], "Seed": 15, "id": 8},
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
    def test_keeps_every_mission_and_ignores_auxiliary_keys(self):
        names = [m["CodeName"] for _, _, m in collect.all_missions(SOURCE)]
        self.assertEqual(sorted(names), ["Duplicitous Bottom", "Gutless Enclosure", "No warnings", "Other One", "Plain One"])

    def test_format_and_order_by_slot_then_biome(self):
        rows = collect_static.day_missions(SOURCE)
        self.assertEqual([(m["start"], m["biome"], m["name"]) for m in rows], [
            ("2026-10-06T16:30:00Z", "Magma Core", "No warnings"),
            ("2026-10-06T17:00:00Z", "Azure Weald", "Duplicitous Bottom"),  # same slot and biome:
            ("2026-10-06T17:00:00Z", "Azure Weald", "Plain One"),           # the file's order is kept
            ("2026-10-06T17:00:00Z", "Salt Pits", "Gutless Enclosure"),
            ("2026-10-06T17:00:00Z", "Salt Pits", "Other One"),
        ])
        self.assertEqual(list(rows[3]), [
            "start", "biome", "mission", "secondary", "length", "complexity", "warnings", "mutator", "name",
            "seasons", "seed", "source_id"])
        self.assertEqual(rows[3]["warnings"], ["Pit Jaw Colony"])
        self.assertEqual([m["mutator"] for m in rows], ["Double XP", "Double XP", None, "Double XP", "Other mutator"])
        self.assertEqual((rows[1]["seed"], rows[1]["source_id"]), (13, 7))
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
            self.assertEqual(len(text.splitlines()), 5 + 2)  # 5 missions + brackets

    def test_old_format_is_downloaded_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026-10-06.json"
            path.write_text('[\n{"start":"2026-10-06T16:30:00Z","biome":"Magma Core"}\n]\n', encoding="utf-8")
            self.assertFalse(collect_static.up_to_date(path))  # Double XP only, no mutator field
            collect_static.write_day(tmp, "2026-10-06", collect_static.day_missions(SOURCE))
            self.assertTrue(collect_static.up_to_date(path))
            self.assertFalse(collect_static.up_to_date(Path(tmp) / "missing.json"))


class SchemaUpgrade(unittest.TestCase):
    OLD_SCHEMA = collect.SCHEMA.split("    seed        INTEGER NOT NULL,")[0] + """    seed        INTEGER NOT NULL
);
CREATE TABLE archived_days (day TEXT PRIMARY KEY, loaded_at TEXT NOT NULL, mission_count INTEGER NOT NULL);
"""

    def test_double_xp_only_database_is_upgraded(self):
        db = sqlite3.connect(":memory:")
        db.executescript(self.OLD_SCHEMA)
        db.execute("INSERT INTO missions (start, day, biome, mission, secondary, length, complexity, warnings,"
                   " name, seasons, seed) VALUES ('2026-10-06T17:00:00Z', '2026-10-06', 'Salt Pits', 'Egg Hunt',"
                   " 'x', 1, 1, '[]', 'n', '[]', 1)")
        db.execute("INSERT INTO archived_days VALUES ('2026-10-06', 'now', 1)")
        self.assertTrue(collect.upgrade_schema(db))
        db.executescript(collect.SCHEMA)  # the new index can now be created
        self.assertEqual(db.execute("SELECT mutator FROM missions").fetchall(), [("Double XP",)])  # still shown
        self.assertEqual(db.execute("SELECT COUNT(*) FROM archived_days").fetchone()[0], 0)  # all reloaded
        self.assertFalse(collect.upgrade_schema(db))  # second call: nothing to do

    def test_new_database_untouched(self):
        db = sqlite3.connect(":memory:")
        self.assertFalse(collect.upgrade_schema(db))
        db.executescript(collect.SCHEMA)
        self.assertFalse(collect.upgrade_schema(db))


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
             "length": 1, "complexity": 1, "warnings": [], "mutator": None, "name": "n", "seasons": ["s6"],
             "seed": 1, "source_id": 1}])
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
            index = json.loads((dist / "data" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["months"], [{"month": "2026-10", "count": 6}])  # the 5 of SOURCE + the 7th's
            self.assertEqual(index["mutators"], ["Double XP", "Other mutator"])
            self.assertEqual(index["warnings"], ["Pit Jaw Colony"])
            self.assertEqual((index["archive_since"], index["known_until"]), ("2026-10-06T16:30:00Z", "2026-10-07T01:00:00Z"))

    def test_month_file_round_trip(self):
        """Decoding a month file (like static-api.js does) gives back the missions, in the same order."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            days, site = self.prepare(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                build_static.main(["--days", str(days), "--site", str(site), "--output", str(tmp / "dist")])
            month = json.loads((tmp / "dist" / "data" / "missions-2026-10.json").read_text(encoding="utf-8"))
            d = month["dictionaries"]
            decoded = [{
                "start": (datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=r[0])).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "biome": d["biome"][r[1]], "mission": d["mission"][r[2]], "secondary": d["secondary"][r[3]],
                "length": r[4], "complexity": r[5], "warnings": [d["warning"][w] for w in r[6]],
                "mutator": None if r[7] == -1 else d["mutator"][r[7]], "name": d["name"][r[8]],
                "seasons": [d["season"][s] for s in r[9]],
            } for r in month["rows"]]
            expected = build_static.read_missions(days)
            for m in expected:
                del m["seed"], m["source_id"]
            self.assertEqual(decoded, expected)

    def test_season_deduced_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            days, site = self.prepare(tmp)
            with contextlib.redirect_stdout(io.StringIO()), mock.patch.dict(os.environ, {"DRG_CURRENT_SEASON": ""}):
                build_static.main(["--days", str(days), "--site", str(site), "--output", str(tmp / "dist")])
            self.assertIn('"currentSeason": ""', (tmp / "dist" / "config.js").read_text(encoding="utf-8"))

    def build_config(self, env, *args):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            days, site = self.prepare(tmp)
            clean = {"GITHUB_REPOSITORY": "", "DRG_GOATCOUNTER": "", "DRG_CURRENT_SEASON": ""}
            with contextlib.redirect_stdout(io.StringIO()), mock.patch.dict(os.environ, {**clean, **env}):
                build_static.main(["--days", str(days), "--site", str(site), "--output", str(tmp / "dist"), *args])
            text = (tmp / "dist" / "config.js").read_text(encoding="utf-8")
            return json.loads(text[text.index("{"):text.rindex("}") + 1])

    def test_readme_link_and_statistics(self):
        config = self.build_config({"GITHUB_REPOSITORY": "owner/repo", "DRG_GOATCOUNTER": "my-site"})
        self.assertEqual(config["readmeUrl"], "https://github.com/owner/repo#readme")
        self.assertEqual(config["goatcounter"], "my-site")

    def test_no_readme_link_nor_statistics_by_default(self):
        config = self.build_config({})
        self.assertEqual((config["readmeUrl"], config["goatcounter"]), ("", ""))

    def test_invalid_statistics_code(self):
        with self.assertRaises(SystemExit):
            self.build_config({"DRG_GOATCOUNTER": "https://evil.example/x"})

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
        api._filters_cache["value"] = None
        patches = [mock.patch.object(api, "DB_PATH", str(path)), mock.patch.object(api, "FORCED_SEASON", "")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def biomes(self, **params):
        result = api.search({"period": "all", **params})
        return sorted(m["biome"] for m in result["missions"])

    def test_several_biomes(self):
        self.assertEqual(self.biomes(biome="Salt Pits,Magma Core"), ["Magma Core", "Salt Pits", "Salt Pits"])
        self.assertEqual(self.biomes(biome="Salt Pits"), ["Salt Pits", "Salt Pits"])
        self.assertEqual(len(self.biomes(biome="")), 6)  # empty: no filter

    def test_several_mission_types_combined_with_a_biome(self):
        self.assertEqual(self.biomes(mission="Egg Hunt,Elimination"), ["Azure Weald", "Magma Core"])
        self.assertEqual(self.biomes(mission="Egg Hunt,Elimination", biome="Magma Core"), ["Magma Core"])

    def test_mutators(self):
        self.assertEqual(self.biomes(mutator="Double XP"), ["Azure Weald", "Hollow Bough", "Magma Core", "Salt Pits"])
        self.assertEqual(self.biomes(mutator="none"), ["Azure Weald"])
        self.assertEqual(self.biomes(mutator="none,Other mutator"), ["Azure Weald", "Salt Pits"])
        self.assertEqual(self.biomes(mutator="Unknown"), [])
        self.assertEqual(api.filters({})["mutators"], ["Double XP", "Other mutator"])

    def test_warnings(self):
        # SOURCE: Salt Pits/Escort Duty has "Pit Jaw Colony"; every other mission has no warning.
        self.assertEqual(self.biomes(warning="Pit Jaw Colony"), ["Salt Pits"])
        self.assertEqual(self.biomes(warning="Pit Jaw Colony", mutator="Double XP"), ["Salt Pits"])
        self.assertEqual(self.biomes(warning="Pit Jaw Colony", mutator="Other mutator"), [])
        self.assertEqual(self.biomes(warning="none", mutator="Double XP"), ["Azure Weald", "Hollow Bough", "Magma Core"])
        self.assertEqual(len(self.biomes(warning="none,Pit Jaw Colony")), 6)
        self.assertEqual(self.biomes(warning="Unknown"), [])
        self.assertEqual(api.filters({})["warnings"], ["Pit Jaw Colony"])

    def test_all_selected_warnings(self):
        db = sqlite3.connect(api.DB_PATH)
        mission = {"PrimaryObjective": "Egg Hunt", "SecondaryObjective": "x", "Length": 1, "Complexity": 1,
                   "CodeName": "n", "included_in": ["s0"], "Seed": 1}
        collect.archive_day(db, "2026-10-05", {"2026-10-05T10:00:00Z": {"Biomes": {
            "Dense Biozone": [{**mission, "MissionWarnings": ["Elite Threat", "Low Oxygen"]}],
            "Fungus Bogs": [{**mission, "MissionWarnings": ["Elite Threat"]}]}}})
        db.close()
        both = "Elite Threat,Low Oxygen"
        self.assertEqual(self.biomes(warning=both), ["Dense Biozone", "Fungus Bogs"])  # any of them
        self.assertEqual(self.biomes(warning=both, warning_mode="all"), ["Dense Biozone"])  # both
        self.assertEqual(self.biomes(warning="Elite Threat", warning_mode="all"), ["Dense Biozone", "Fungus Bogs"])
        self.assertEqual(self.biomes(warning="Elite Threat,none", warning_mode="all"), [])  # contradictory
        self.assertEqual(self.biomes(warning=both, warning_mode="other"), ["Dense Biozone", "Fungus Bogs"])

    def test_upcoming_is_filtered(self):
        self.assertEqual([m["name"] for m in api.upcoming({"mutator": "Double XP"})["missions"]], ["Recent"])
        self.assertEqual(api.upcoming({"mutator": "none"})["missions"], [])
        self.assertEqual(api.upcoming({"biome": "Hollow Bough", "season": "s7"})["missions"][0]["mutator"], "Double XP")

    def test_ties_keep_the_source_order(self):
        past = [m["name"] for m in api.search({"period": "all", "biome": "Azure Weald"})["missions"]]
        self.assertEqual(past, ["Plain One", "Duplicitous Bottom"])  # newest first: reverse source order
        future = [m["name"] for m in api.search({"period": "upcoming"})["missions"]]
        self.assertEqual(future, ["Recent"])

    def test_current_season_deduced_from_recent_missions(self):
        self.assertEqual(api.filters({})["current_season"], "s7")

    def test_forced_current_season(self):
        with mock.patch.object(api, "FORCED_SEASON", "s6"):
            self.assertEqual(api.filters({})["current_season"], "s6")


if __name__ == "__main__":
    unittest.main()
