#!/usr/bin/env python3
"""Refresh data.js with live results from the GitHub repository search API.

Usage:  GITHUB_TOKEN=... python3 scripts/update.py
The token is optional but avoids the low unauthenticated rate limit.
Only the standard library is used.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com/search/repositories"
KEEP = 12  # repos kept per lane
BLOCKED = ("nsfw",)  # repos mentioning these words are left out
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.js")

TODAY = datetime.now(timezone.utc).date()


def ago(days):
    return (TODAY - timedelta(days=days)).isoformat()


# Add or edit lanes here. "q" is a normal GitHub repository search query.
LANES = [
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
    return any(word in text for word in BLOCKED)


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


def main():
    lanes = []
    for lane in LANES:
        data = fetch(lane["q"])
        repos = [slim(i) for i in data["items"]
                 if not i.get("archived") and not blocked(i)][:KEEP]
        lanes.append({
            "id": lane["id"], "name": lane["name"], "hint": lane["hint"],
            "matches": data.get("total_count", len(repos)), "repos": repos,
        })
        print(f"{lane['id']}: {len(repos)} repos of {data.get('total_count')}")
        time.sleep(2)  # stay well inside the search rate limit

    payload = {"generated": TODAY.isoformat(), "lanes": lanes}
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("window.GITTUBE = ")
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    print("wrote data.js")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # leave the old data.js untouched on any failure
        print(f"update failed: {exc}", file=sys.stderr)
        sys.exit(1)
