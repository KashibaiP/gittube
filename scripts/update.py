#!/usr/bin/env python3
"""Refresh data.js with live results from the GitHub repository search API.

Usage:  GITHUB_TOKEN=... python3 scripts/update.py
The token is optional but avoids the low unauthenticated rate limit.
Only the standard library is used.

Besides the repo lists, the script keeps a small history of star counts
(`hist` in data.js) so it can show how many stars each repo gained.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com/search/repositories"
KEEP = 12          # repos kept per lane
HIST_DAYS = 14     # how long star snapshots are kept
BLOCKED = ("nsfw", "porn", "pre-activat", "keygen", "cracked", "full working installer")
# repos mentioning these words are left out
PREFIX = "window.GITTUBE = "
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.js")


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_lanes(now):
    """Lane definitions. "q" is a normal GitHub repository search query."""
    def ago(days):
        return (now - timedelta(days=days)).date().isoformat()

    return [
        {"id": "today", "name": "Today",
         "hint": "Repos created in the last 24 hours, most starred first.",
         "q": f"created:>{stamp(now - timedelta(hours=24))}"},
        {"id": "week", "name": "This week",
         "hint": "Repos created in the last 7 days, most starred first.",
         "q": f"created:>{ago(7)}"},
        {"id": "python", "name": "Python",
         "hint": "Python repos created in the last 30 days, most starred first.",
         "q": f"language:python created:>{ago(30)}"},
        {"id": "rust", "name": "Rust",
         "hint": "Rust repos created in the last 30 days, most starred first.",
         "q": f"language:rust created:>{ago(30)}"},
        {"id": "telecom", "name": "Telecom",
         "hint": "Repos with the telecom topic, pushed in the last 14 days, 10+ stars.",
         "q": f"topic:telecom pushed:>{ago(14)} stars:>10"},
        {"id": "5g", "name": "5G",
         "hint": "Repos with the 5g topic, pushed in the last 14 days, 50+ stars.",
         "q": f"topic:5g pushed:>{ago(14)} stars:>50"},
    ]


def fetch(query):
    params = urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": KEEP + 6})
    req = urllib.request.Request(f"{API}?{params}", headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "gittube-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def blocked(item):
    text = " ".join([
        item.get("full_name") or "",
        item.get("description") or "",
        " ".join(item.get("topics") or []),
    ]).lower()
    if any(word in text for word in BLOCKED):
        return True
    # Star-farmed spam: hundreds of stars, no forks, topics stuffed to the API cap.
    return (len(item.get("topics") or []) >= 20
            and item.get("forks_count", 0) == 0
            and item.get("stargazers_count", 0) >= 100)


def day(iso):
    return (iso or "")[:10]


def slim(item):
    return {
        "n": item["full_name"],
        "d": item.get("description") or "",
        "l": item.get("language") or "",
        "s": item["stargazers_count"],
        "f": item["forks_count"],
        "c": day(item.get("created_at")),
        "u": day(item.get("updated_at")),
        "t": (item.get("topics") or [])[:4],
    }


# ---- star history -----------------------------------------------------

def load_previous(path):
    """Read the previous data.js. Returns {} if it is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
        if not text.startswith(PREFIX):
            return {}
        return json.loads(text[len(PREFIX):].rstrip(";").strip())
    except (OSError, ValueError):
        return {}


def bootstrap_history(prev):
    """Older data.js files have no history. Use their star counts as one snapshot."""
    hist = {}
    date = prev.get("generated")
    if not date:
        return hist
    for lane in prev.get("lanes", []):
        for repo in lane.get("repos", []):
            hist.setdefault(repo["n"], [[date, repo["s"]]])
    return hist


def update_history(prev_hist, repos, today):
    """Add today's star counts and drop snapshots older than HIST_DAYS."""
    cutoff = (datetime.fromisoformat(today) - timedelta(days=HIST_DAYS)).date().isoformat()
    hist = {}
    for name, entries in prev_hist.items():
        kept = [e for e in entries if e[0] >= cutoff and e[0] != today]
        if kept:
            hist[name] = kept
    for repo in repos:
        entries = hist.setdefault(repo["n"], [])
        entries[:] = [e for e in entries if e[0] != today]
        entries.append([today, repo["s"]])
        entries.sort(key=lambda e: e[0])
    return hist


def gain(entries, stars, today, days):
    """Stars gained since the latest snapshot taken `days` or more days ago.

    days=1 means "since the previous day's snapshot". Returns None when there
    is no snapshot old enough to compare with.
    """
    limit = (datetime.fromisoformat(today) - timedelta(days=days)).date().isoformat()
    older = [e for e in entries if e[0] <= limit]
    if not older:
        return None
    return stars - older[-1][1]


# ---- main -------------------------------------------------------------

def run(fetch_fn=fetch, now=None, out=OUT, pause=2):
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    prev = load_previous(out)
    prev_hist = prev.get("hist") or bootstrap_history(prev)

    lanes = []
    for lane in build_lanes(now):
        data = fetch_fn(lane["q"])
        repos = [slim(i) for i in data["items"]
                 if not i.get("archived") and not blocked(i)][:KEEP]
        lanes.append({
            "id": lane["id"], "name": lane["name"], "hint": lane["hint"],
            "matches": data.get("total_count", len(repos)), "repos": repos,
        })
        print(f"{lane['id']}: {len(repos)} repos of {data.get('total_count')}")
        if pause:
            time.sleep(pause)  # stay well inside the search rate limit

    every = [r for lane in lanes for r in lane["repos"]]
    hist = update_history(prev_hist, every, today)
    for repo in every:
        entries = hist[repo["n"]]
        for key, days in (("g1", 1), ("g7", 7)):
            g = gain(entries, repo["s"], today, days)
            if g is not None:
                repo[key] = g

    payload = {"generated": today, "at": stamp(now), "lanes": lanes, "hist": hist}
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(PREFIX)
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    os.replace(tmp, out)  # the old file stays intact if anything above failed
    print("wrote data.js")
    return payload


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # leave the old data.js untouched on any failure
        print(f"update failed: {exc}", file=sys.stderr)
        sys.exit(1)
