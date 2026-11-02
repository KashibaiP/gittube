# GitTube

A HackerTube-style browser for GitHub repositories. Repos are grouped into lanes by language and topic: this week's new repos, Python, Rust, telecom and 5G. Each card shows stars, forks, dates, topics and a link to the real repository. You can search, sort, and click a topic to filter.

## Run it

Open `index.html` in a browser. There is no build step and no dependencies. The data is in `data.js`, which the page loads with a normal script tag, so it also works from a local file.

## How the data is kept fresh

`scripts/update.py` queries the GitHub repository search API and rewrites `data.js`. It uses only the Python standard library.

```
GITHUB_TOKEN=<token> python3 scripts/update.py
```

The token is optional and only raises the rate limit.

### Daily refresh with GitHub Actions

Create `.github/workflows/update.yml` with the contents below (on github.com: **Add file** > **Create new file**). It runs the script every day and commits `data.js` if it changed. You can also run it by hand from the Actions tab.

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
          if git diff --quiet -- data.js; then
            echo "No changes."
          else
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add data.js
            git commit -m "Update data"
            git push
          fi
```

## Add your own lanes

Edit the `LANES` list at the top of `scripts/update.py`. Each lane has an id, a name, a short hint and a normal GitHub search query, for example:

```python
{"id": "go", "name": "Go",
 "hint": "Go repos created in the last 30 days, most starred first.",
 "q": f"language:go created:>{ago(30)}"},
```

Then add a hue for the new id to the `HUES` object in `index.html` so its cards get their own color.

## Notes

- Lane definitions: "This week" is repos created in the last 7 days. Python and Rust are repos created in the last 30 days. Telecom and 5G are repos with that topic that were pushed in the last 14 days and pass a minimum star count.
- Stars and forks are the counts at the last refresh.
- Repos that mention certain adult-content words are filtered out in `update.py`.
- To publish it as a website, make the repo public and turn on GitHub Pages for the `main` branch.
