#!/usr/bin/env python3
"""Refresh data.js with live results from the GitHub repository search API.

Usage:  GITHUB_TOKEN=... python3 scripts/update.py
The token is optional but avoids the low unauthenticated rate limit.
Only the standard library is used.

Besides the repo lists, the script keeps a small history of star counts
(`hist` in data.js) so it can show how many stars each repo gained.
"""
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape

API = "https://api.github.com/search/repositories"
KEEP = 12          # repos kept per lane
HIST_DAYS = 14     # how long star snapshots are kept
BLOCKED = ("nsfw", "porn", "pre-activat", "keygen", "cracked", "full working installer")
# repos mentioning these words are left out
GFI = " good-first-issues:>0"  # search qualifier: repos with open good-first-issue issues
PREFIX = "window.GITTUBE = "
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.js")
DIGEST_WEEKS = 12  # weekly digests kept in the feed
DEFAULT_SITE = "https://kashibaip.github.io/gittube/"


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
        for repo in lane.get("repos", []) + lane.get("gfi", []):
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


# ---- weekly digest (RSS feed) -------------------------------------------

def site_url():
    """Public address of the site, used for links inside the feed."""
    url = os.environ.get("SITE_URL")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not url and "/" in repo:
        owner, name = repo.split("/", 1)
        url = f"https://{owner.lower()}.github.io/{name}/"
    url = url or DEFAULT_SITE
    return url if url.endswith("/") else url + "/"


def week_id(d):
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(d):
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def build_digest(lanes, now):
    """This week's picks: the fastest risers, then the top repos of each lane."""
    today = now.date()
    monday, sunday = week_bounds(today)

    def brief(r, g=None):
        out = {"n": r["n"], "d": (r.get("d") or "")[:140], "l": r.get("l") or "", "s": r["s"]}
        if g is not None:
            out["g"] = g
        return out

    every = [r for lane in lanes for r in lane["repos"]]
    kind = "week" if any(r.get("g7") is not None for r in every) else "day"
    key = "g7" if kind == "week" else "g1"
    best = {}
    for r in every:
        g = r.get(key)
        if g and g > 0 and g > best.get(r["n"], (0, None))[0]:
            best[r["n"]] = (g, r)
    rising = [brief(r, g) for g, r in sorted(best.values(), key=lambda x: -x[0])[:5]]

    seen = {r["n"] for r in rising}
    sections = []
    for lane in lanes:
        picks = []
        for r in lane["repos"]:
            if r["n"] in seen:
                continue
            seen.add(r["n"])
            picks.append(brief(r))
            if len(picks) == 3:
                break
        if picks:
            sections.append({"id": lane["id"], "name": lane["name"], "repos": picks})
    return {"week": week_id(today), "start": monday.isoformat(), "end": sunday.isoformat(),
            "updated": stamp(now), "kind": kind, "rising": rising, "lanes": sections}


def update_digests(prev, digest):
    """Replace this week's digest (or add it); older weeks stay as they were."""
    kept = [d for d in prev if isinstance(d, dict) and d.get("week") != digest["week"]]
    return sorted(kept + [digest], key=lambda d: d["week"], reverse=True)[:DIGEST_WEEKS]


def _cdata(text):
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _repo_li(r, site, kind=None):
    name = html.escape(r["n"])
    bits = f"★ {r['s']:,}"
    if r.get("g") is not None:
        bits += f", +{r['g']:,} this " + ("week" if kind == "week" else "day")
    desc = f": {html.escape(r['d'])}" if r.get("d") else ""
    lang = f" ({html.escape(r['l'])})" if r.get("l") else ""
    return (f'<li><a href="https://github.com/{html.escape(r["n"], quote=True)}">{name}</a>'
            f"{lang} {bits}{desc}</li>")


def _span(d):
    a = datetime.fromisoformat(d["start"])
    b = datetime.fromisoformat(d["end"])
    if a.month == b.month:
        return f"{a.day}–{b.day} {b:%b %Y}"
    return f"{a.day} {a:%b} – {b.day} {b:%b %Y}"


def digest_html(d, site):
    parts = [f"<p>The best of GitHub this week ({_span(d)}), picked from GitTube's lanes. "
             "This entry is refreshed daily until the week ends.</p>"]
    if d["rising"]:
        parts.append("<h3>Rising fastest</h3><ol>"
                     + "".join(_repo_li(r, site, d.get("kind")) for r in d["rising"]) + "</ol>")
    else:
        parts.append("<p>Star-growth numbers appear once GitTube has a few days of history.</p>")
    for lane in d["lanes"]:
        parts.append(f"<h3>{html.escape(lane['name'])}</h3><ul>"
                     + "".join(_repo_li(r, site) for r in lane["repos"]) + "</ul>")
    parts.append(f'<p><a href="{html.escape(site, quote=True)}">Open GitTube</a></p>')
    return "".join(parts)


def render_feed(digests, site, now):
    items = []
    for d in digests:
        title = f"GitTube weekly digest: week {int(d['week'][-2:])}, {d['week'][:4]} ({_span(d)})"
        pub = format_datetime(datetime.strptime(d["updated"], "%Y-%m-%dT%H:%M:%SZ")
                              .replace(tzinfo=timezone.utc))
        items.append(
            "<item>"
            f"<title>{xml_escape(title)}</title>"
            f"<link>{xml_escape(site)}</link>"
            f'<guid isPermaLink="false">gittube-{xml_escape(d["week"])}</guid>'
            f"<pubDate>{pub}</pubDate>"
            f"<description>{_cdata(digest_html(d, site))}</description>"
            "</item>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        "<title>GitTube weekly digest</title>"
        f"<link>{xml_escape(site)}</link>"
        "<description>Trending GitHub repos by week: the fastest risers and the top of each lane.</description>"
        "<language>en</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        f'<atom:link href="{xml_escape(site, {chr(34): "&quot;"})}feed.xml" rel="self" type="application/rss+xml"/>'
        + "".join(items) + "</channel></rss>\n")


# ---- main -------------------------------------------------------------

def run(fetch_fn=fetch, now=None, out=OUT, pause=2):
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    prev = load_previous(out)
    prev_hist = prev.get("hist") or bootstrap_history(prev)

    def pick(data):
        return [slim(i) for i in data["items"]
                if not i.get("archived") and not blocked(i)][:KEEP]

    lanes = []
    for lane in build_lanes(now):
        data = fetch_fn(lane["q"])
        repos = pick(data)
        if pause:
            time.sleep(pause)  # stay well inside the search rate limit
        # same search, limited to repos that have open "good first issue" issues
        gdata = fetch_fn(lane["q"] + GFI)
        gfi = pick(gdata)
        lanes.append({
            "id": lane["id"], "name": lane["name"], "hint": lane["hint"],
            "matches": data.get("total_count", len(repos)), "repos": repos,
            "gmatches": gdata.get("total_count", len(gfi)), "gfi": gfi,
        })
        print(f"{lane['id']}: {len(repos)} repos of {data.get('total_count')}, {len(gfi)} with good first issues")
        if pause:
            time.sleep(pause)

    every = [r for lane in lanes for r in lane["repos"] + lane["gfi"]]
    hist = update_history(prev_hist, every, today)
    for repo in every:
        entries = hist[repo["n"]]
        for key, days in (("g1", 1), ("g7", 7)):
            g = gain(entries, repo["s"], today, days)
            if g is not None:
                repo[key] = g

    digests = update_digests(prev.get("digests") or [], build_digest(lanes, now))
    feed = render_feed(digests, site_url(), now)

    payload = {"generated": today, "at": stamp(now), "lanes": lanes, "hist": hist, "digests": digests}
    feed_out = os.path.join(os.path.dirname(out), "feed.xml")
    tmp, ftmp = out + ".tmp", feed_out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(PREFIX)
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    with open(ftmp, "w", encoding="utf-8") as fh:
        fh.write(feed)
    os.replace(tmp, out)  # the old files stay intact if anything above failed
    os.replace(ftmp, feed_out)
    print("wrote data.js and feed.xml")
    return payload


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # leave the old data.js untouched on any failure
        print(f"update failed: {exc}", file=sys.stderr)
        sys.exit(1)
