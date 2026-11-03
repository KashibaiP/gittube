"""Tests for scripts/update.py. Run:  python3 -m unittest discover -s tests -v"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import update  # noqa: E402


def item(name, stars, **kw):
    base = {
        "full_name": name, "description": "A repo", "language": "Python",
        "stargazers_count": stars, "forks_count": 1,
        "created_at": "2026-11-01T10:00:00Z", "updated_at": "2026-11-03T10:00:00Z",
        "topics": ["a", "b", "c", "d", "e"], "archived": False,
    }
    base.update(kw)
    return base


def at(day, hour=3):
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hour, 17, tzinfo=timezone.utc)


class FakeAPI:
    """Stands in for the GitHub search API. Records every query it receives."""

    def __init__(self, stars=None, extra=None):
        self.stars = stars or {}
        self.extra = extra or []
        self.queries = []

    def __call__(self, query):
        self.queries.append(query)
        items = [item("o/alpha", self.stars.get("o/alpha", 100)),
                 item("o/beta", self.stars.get("o/beta", 50))] + self.extra
        return {"items": items, "total_count": 999}


class QueryTests(unittest.TestCase):
    def test_lane_ids_and_order(self):
        ids = [l["id"] for l in update.build_lanes(at("2026-11-04"))]
        self.assertEqual(ids, ["today", "week", "python", "rust", "telecom", "5g"])

    def test_today_lane_looks_back_exactly_24_hours(self):
        lanes = {l["id"]: l for l in update.build_lanes(at("2026-11-04"))}
        self.assertEqual(lanes["today"]["q"], "created:>2026-11-03T03:17:00Z")

    def test_other_lane_windows(self):
        lanes = {l["id"]: l for l in update.build_lanes(at("2026-11-04"))}
        self.assertEqual(lanes["week"]["q"], "created:>2026-10-28")
        self.assertEqual(lanes["python"]["q"], "language:python created:>2026-10-05")
        self.assertIn("topic:5g pushed:>2026-10-21", lanes["5g"]["q"])


class FilterTests(unittest.TestCase):
    def test_slim_keeps_four_topics_and_day_only_dates(self):
        s = update.slim(item("o/x", 5))
        self.assertEqual(s["t"], ["a", "b", "c", "d"])
        self.assertEqual(s["c"], "2026-11-01")
        self.assertEqual(s["u"], "2026-11-03")

    def test_slim_handles_missing_fields(self):
        s = update.slim({"full_name": "o/x", "stargazers_count": 1, "forks_count": 0})
        self.assertEqual((s["d"], s["l"], s["t"], s["c"]), ("", "", [], ""))

    def test_blocked_words_in_name_description_or_topics(self):
        self.assertTrue(update.blocked(item("o/NSFW-thing", 1)))
        self.assertTrue(update.blocked(item("o/x", 1, description="an NSFW skill")))
        self.assertTrue(update.blocked(item("o/x", 1, topics=["nsfw"])))
        self.assertFalse(update.blocked(item("o/x", 1)))

    def test_fake_installer_spam_is_blocked(self):
        self.assertTrue(update.blocked(item(
            "o/office", 1, description="Complete standalone setup, full pre-activation")))
        self.assertTrue(update.blocked(item(
            "o/fl", 1, description="Fl Studio 2026 - Full working installer")))

    def test_star_farmed_repos_with_stuffed_topics_are_blocked(self):
        spam = item("o/s", 312, forks_count=0, topics=[f"t{i}" for i in range(20)])
        self.assertTrue(update.blocked(spam))

    def test_real_repos_with_many_topics_or_no_forks_are_kept(self):
        many = item("o/m", 312, forks_count=0, topics=[f"t{i}" for i in range(12)])
        popular = item("o/p", 312, forks_count=40, topics=[f"t{i}" for i in range(20)])
        young = item("o/y", 30, forks_count=0, topics=[f"t{i}" for i in range(20)])
        for r in (many, popular, young):
            self.assertFalse(update.blocked(r))


class HistoryTests(unittest.TestCase):
    def test_update_history_adds_today_and_keeps_order(self):
        hist = update.update_history({"o/a": [["2026-11-02", 10]]},
                                     [{"n": "o/a", "s": 15}], "2026-11-03")
        self.assertEqual(hist["o/a"], [["2026-11-02", 10], ["2026-11-03", 15]])

    def test_same_day_rerun_replaces_entry_instead_of_duplicating(self):
        prev = {"o/a": [["2026-11-02", 10], ["2026-11-03", 12]]}
        hist = update.update_history(prev, [{"n": "o/a", "s": 15}], "2026-11-03")
        self.assertEqual(hist["o/a"], [["2026-11-02", 10], ["2026-11-03", 15]])

    def test_old_snapshots_and_stale_repos_are_pruned(self):
        prev = {"o/old": [["2026-10-01", 5]],
                "o/a": [["2026-10-01", 5], ["2026-10-25", 8]]}
        hist = update.update_history(prev, [{"n": "o/a", "s": 20}], "2026-11-03")
        self.assertNotIn("o/old", hist)
        self.assertEqual(hist["o/a"], [["2026-10-25", 8], ["2026-11-03", 20]])

    def test_gain_since_previous_day(self):
        entries = [["2026-11-02", 100], ["2026-11-03", 160]]
        self.assertEqual(update.gain(entries, 160, "2026-11-03", 1), 60)

    def test_gain_is_none_without_an_old_enough_snapshot(self):
        self.assertIsNone(update.gain([["2026-11-03", 160]], 160, "2026-11-03", 1))
        self.assertIsNone(update.gain([["2026-11-01", 100], ["2026-11-03", 160]],
                                      160, "2026-11-03", 7))

    def test_gain_over_a_week_uses_latest_snapshot_at_least_7_days_old(self):
        entries = [["2026-10-25", 50], ["2026-10-27", 80], ["2026-11-02", 150],
                   ["2026-11-03", 200]]
        # limit is 2026-10-27, so the 27th snapshot is the baseline
        self.assertEqual(update.gain(entries, 200, "2026-11-03", 7), 120)

    def test_bootstrap_from_old_data_without_history(self):
        prev = {"generated": "2026-11-03",
                "lanes": [{"repos": [{"n": "o/a", "s": 40}, {"n": "o/b", "s": 7}]},
                          {"repos": [{"n": "o/a", "s": 40}]}]}
        hist = update.bootstrap_history(prev)
        self.assertEqual(hist, {"o/a": [["2026-11-03", 40]], "o/b": [["2026-11-03", 7]]})

    def test_bootstrap_without_date_is_empty(self):
        self.assertEqual(update.bootstrap_history({"lanes": []}), {})


class RunTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "data.js")

    def read(self):
        return update.load_previous(self.out)

    def test_first_run_writes_valid_file_with_no_gains(self):
        api = FakeAPI()
        update.run(api, at("2026-11-03"), self.out, pause=0)
        data = self.read()
        self.assertEqual(data["generated"], "2026-11-03")
        self.assertEqual(data["at"], "2026-11-03T03:17:00Z")
        self.assertEqual(len(data["lanes"]), 6)
        repo = data["lanes"][0]["repos"][0]
        self.assertNotIn("g1", repo)
        self.assertNotIn("g7", repo)
        self.assertEqual(data["hist"]["o/alpha"], [["2026-11-03", 100]])
        self.assertEqual(len(api.queries), 6)

    def test_second_day_shows_gain(self):
        update.run(FakeAPI(), at("2026-11-03"), self.out, pause=0)
        update.run(FakeAPI({"o/alpha": 160}), at("2026-11-04"), self.out, pause=0)
        data = self.read()
        alpha = [r for r in data["lanes"][0]["repos"] if r["n"] == "o/alpha"][0]
        beta = [r for r in data["lanes"][0]["repos"] if r["n"] == "o/beta"][0]
        self.assertEqual(alpha["g1"], 60)
        self.assertEqual(beta["g1"], 0)
        self.assertNotIn("g7", alpha)  # only one day of history so far

    def test_week_gain_appears_after_seven_days(self):
        for i, stars in enumerate([100, 110, 120, 130, 140, 150, 160, 170]):
            update.run(FakeAPI({"o/alpha": stars}), at(f"2026-11-{3 + i:02d}"), self.out, pause=0)
        alpha = [r for r in self.read()["lanes"][0]["repos"] if r["n"] == "o/alpha"][0]
        self.assertEqual(alpha["g1"], 10)
        self.assertEqual(alpha["g7"], 70)

    def test_upgrades_an_old_file_that_has_no_history(self):
        old = {"generated": "2026-11-03",
               "lanes": [{"id": "week", "repos": [{"n": "o/alpha", "s": 100}]}]}
        with open(self.out, "w", encoding="utf-8") as fh:
            fh.write(update.PREFIX + json.dumps(old) + ";\n")
        update.run(FakeAPI({"o/alpha": 130}), at("2026-11-04"), self.out, pause=0)
        alpha = [r for r in self.read()["lanes"][0]["repos"] if r["n"] == "o/alpha"][0]
        self.assertEqual(alpha["g1"], 30)

    def test_archived_and_blocked_repos_are_skipped(self):
        extra = [item("o/old", 999, archived=True), item("o/nsfw-pack", 998)]
        update.run(FakeAPI(extra=extra), at("2026-11-03"), self.out, pause=0)
        names = [r["n"] for r in self.read()["lanes"][0]["repos"]]
        self.assertEqual(names, ["o/alpha", "o/beta"])

    def test_keeps_only_12_repos_per_lane(self):
        extra = [item(f"o/r{i}", i) for i in range(30)]
        update.run(FakeAPI(extra=extra), at("2026-11-03"), self.out, pause=0)
        self.assertEqual(len(self.read()["lanes"][0]["repos"]), 12)

    def test_failed_fetch_leaves_the_old_file_untouched(self):
        update.run(FakeAPI(), at("2026-11-03"), self.out, pause=0)
        before = open(self.out, encoding="utf-8").read()

        def broken(query):
            raise OSError("network down")

        with self.assertRaises(OSError):
            update.run(broken, at("2026-11-04"), self.out, pause=0)
        self.assertEqual(open(self.out, encoding="utf-8").read(), before)
        self.assertFalse(os.path.exists(self.out + ".tmp"))

    def test_output_is_a_script_the_page_can_load(self):
        update.run(FakeAPI(), at("2026-11-03"), self.out, pause=0)
        text = open(self.out, encoding="utf-8").read()
        self.assertTrue(text.startswith("window.GITTUBE = "))
        self.assertTrue(text.rstrip().endswith(";"))
        json.loads(text[len("window.GITTUBE = "):].rstrip().rstrip(";"))

    def test_unreadable_previous_file_is_ignored(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            fh.write("not a data file")
        self.assertEqual(update.load_previous(self.out), {})
        update.run(FakeAPI(), at("2026-11-03"), self.out, pause=0)
        self.assertEqual(self.read()["generated"], "2026-11-03")


if __name__ == "__main__":
    unittest.main()
