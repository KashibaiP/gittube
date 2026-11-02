# GitTube

A HackerTube-style browser for the repositories trending on GitHub. Each repo is a card with its weekly and daily rank, a topic label and a link to the real repository. You can filter by topic, search, and sort.

## Run it

It is a single static file. Open `index.html` in a browser. No build step and no dependencies.

## Data

The list is a fixed snapshot from 2 Nov 2026:

- Weekly ranks: [Trendshift weekly](https://trendshift.io/weekly)
- Daily ranks: [marc-ko/daily-trending-repo, issue 597](https://github.com/marc-ko/daily-trending-repo/issues/597)

Descriptions are short paraphrases of what those pages state. Topic groups are a manual reading of each description. The data lives in the `R` array near the bottom of `index.html`.

## Ideas

- Fetch live stars, forks and topics from the GitHub API.
- Refresh the list on a schedule with GitHub Actions.
