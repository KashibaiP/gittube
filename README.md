

https://github.com/user-attachments/assets/33d452c5-74f6-40ee-a1fa-9d5b8940b782

# GitTube

A HackerTube-style browser for GitHub repositories. Repos are grouped into lanes: Today (created in the last 24 hours), This week, Python, Rust, telecom and 5G. Each card shows stars, how many stars the repo gained, forks, dates, topics and a link to the real repository.

## What visitors can do

- **Browse lanes**, search, sort, and click a topic to filter.
- **Add their own lanes.** Type a language or topic (`Go`, `6g`, `open-ran`) under the lane chips. The page searches GitHub live from the visitor's browser and keeps the lane in that browser (up to 8). Use `lang:` or `topic:` in front to force the kind.
- **Filter** by language, minimum stars, or **good first issues** (repos with open good-first-issue issues).
- **Save for later.** The Save button on each card keeps the repo in a Saved view, stored in the visitor's browser (up to 100).
- **Follow the weekly digest** through `feed.xml`, an RSS feed with one entry per week.

Nothing is sent to any server of ours. Own lanes, saved repos and filters live in the visitor's browser.

## Run it

Open `index.html` in a browser. There is no build step and no dependencies. The data is in `data.js`, which the page loads with a normal script tag, so it also works from a local file.

## How the data is kept fresh

`scripts/update.py` queries the GitHub repository search API and rewrites `data.js` and `feed.xml`. It uses only the Python standard library.

```
GITHUB_TOKEN=<token> python3 scripts/update.py
```

The token is optional and only raises the rate limit. Each lane is searched twice (once normally, once for repos with good first issues), so a run makes 12 searches.

### Daily refresh with GitHub Actions

Create `.github/workflows/update.yml` with the contents below (on github.com: **Add file** > **Create new file**). It runs the script every day and commits `data.js` and `feed.xml` if they changed. You can also run it by hand from the Actions tab.

```yaml
name: Update data

on:
  schedule:
    - cron: "17 3 * * *"   # every day, 03:17 UTC
  workflow_dispatch:        # lets you run it by hand from the Actions tab

permissions:
  contents: write

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Fetch fresh data
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 scripts/update.py
      - name: Commit if changed
        run: |
          if git diff --quiet -- data.js feed.xml; then
            echo "No changes."
          else
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add data.js feed.xml
            git commit -m "Update data"
            git push
          fi
```

## Momentum

GitHub does not report star growth, so the daily job saves a snapshot of every listed repo's star count (kept for 14 days, in `hist` inside `data.js`). Each refresh compares the new count with the snapshots:

- **+N today** is the gain since the previous day's snapshot. It appears from the second daily refresh.
- **+N this week** is the gain since a snapshot at least 7 days old. It appears from the eighth daily refresh.
- **NEW** marks a repo created within the last day that has no gain yet.

The **Most gained today** sort stays switched off until at least one repo has a gain.

## Weekly digest (RSS)

Every refresh also writes `feed.xml`. It has one entry per ISO week (Monday to Sunday), newest first, and keeps the last 12 weeks:

- **Rising fastest**: the five repos with the biggest star gain (this week's gain when there is one, otherwise today's).
- **One section per lane** with its top three repos not already listed.

The entry for the current week is rewritten on every refresh until the week ends; older weeks stay as they were. Links in the feed point to your site, which the script works out from `GITHUB_REPOSITORY` when it runs in Actions (`https://<owner>.github.io/<repo>/`). To use another address, set the `SITE_URL` environment variable.

To get it by email, add the feed's address to any service that turns RSS into email. GitTube itself does not send email.

## Tests

```
python3 -m unittest discover -s tests -v     # script logic, no network needed
npm install playwright && npx playwright install chromium
node tests/e2e.js                            # the page, in a real browser
```

## Add a lane for everyone

Visitors can add lanes for themselves in the page. To add a lane that everyone sees and that is refreshed daily, edit `build_lanes` in `scripts/update.py`. Each lane has an id, a name, a short hint and a normal GitHub search query, for example:

```python
{"id": "go", "name": "Go",
 "hint": "Go repos created in the last 30 days, most starred first.",
 "q": f"language:go created:>{ago(30)}"},
```

Then add a hue for the new id to the `HUES` object in `index.html` so its cards get their own color.

## Notes

- Lane definitions: Today is repos created in the last 24 hours. This week is the last 7 days. Python and Rust are repos created in the last 30 days. Telecom and 5G are repos with that topic that were pushed in the last 14 days and pass a minimum star count.
- Stars and forks are the counts at the last refresh. Times are UTC.
- Repos that mention certain adult-content words, fake "pre-activated" installers, or that look star-farmed (hundreds of stars, no forks, 20 stuffed topics) are filtered out, both in `update.py` and in the page's own-lane search.
- GitHub allows about 10 anonymous searches a minute from a browser, so own lanes and the good-first-issues filter on own lanes can briefly show a rate-limit message.
- To publish it as a website, make the repo public and turn on GitHub Pages for the `main` branch.
