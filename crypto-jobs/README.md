# 🔐 Cryptography Research Positions

A live, filterable index of postdoc · research-scientist · faculty · internship · visiting positions in cryptography (MPC, FHE, FSS, ZK, PQC, PPML, hardware, side-channel, SSE, blockchain) — India and abroad.

Inspired by [mpc-deadlines](https://mpc-deadlines.github.io/) and [sec-deadlines](https://sec-deadlines.github.io/), but for **positions** instead of conference deadlines.

## What's inside

```
crypto-jobs/
├── _config.yml                 ← Jekyll config + filter taxonomies
├── _data/
│   └── positions.yml           ← the list (curated + auto-appended IACR entries)
├── _layouts/
│   └── default.html
├── _includes/                  ← (reserved for future partials)
├── assets/
│   ├── css/style.css           ← dark/light theme, responsive
│   └── js/filter.js            ← client-side filtering + URL hash sync
├── index.html                  ← renders all cards with filter UI
├── scripts/
│   └── fetch_iacr_jobs.py      ← scrapes IACR jobs board, classifies new entries
├── Gemfile
└── README.md                   ← (this file)
```

## Deploying to GitHub Pages (one-time setup)

1. **Create a new public GitHub repo.** If you want a user-page URL (`<you>.github.io`), name it exactly `<you>.github.io`. Otherwise any name works (URL becomes `<you>.github.io/<repo>`).

2. **Push this folder.** From inside the unpacked `crypto-jobs/` directory:
   ```bash
   git init && git add -A && git commit -m "Initial commit"
   git branch -M main
   git remote add origin git@github.com:<you>/<repo>.git
   git push -u origin main
   ```

3. **Turn on Pages.** Repo → Settings → Pages → Source: **GitHub Actions** (not "Deploy from branch"). The `deploy.yml` workflow (at the repo root, in `.github/workflows/`) handles the rest.

   > **Note:** the GitHub Actions workflows must live in `.github/workflows/` at the **repository root** — GitHub ignores any `.github/workflows/` inside a subfolder. In this repo the Jekyll site is in `crypto-jobs/`, so the workflows point into that subdirectory.

4. **Adjust `_config.yml`:** if your repo is not a user-page, set:
   ```yaml
   baseurl: "/<repo-name>"
   ```

5. **First deploy:** push any commit. The site will appear at `https://<you>.github.io/<repo>/` within a couple of minutes.

## How the self-update works

- Every 6 hours, the **Refresh IACR job listings** workflow runs (`.github/workflows/refresh-iacr.yml` at the repo root).
- It scrapes the IACR jobs board at `https://iacr.org/jobs/` (there is no RSS feed — the board is server-rendered HTML), classifies each entry into `type`, `region`, and `area` using regex heuristics, and **appends only new entries** (those whose canonical `https://iacr.org/jobs/item/<id>` link isn't already in `_data/positions.yml`) to the end of `_data/positions.yml`.
- It commits the change to `main` and then dispatches the **Deploy** workflow, which rebuilds and publishes the site automatically — no human step required.

This is an **auto-publish** flow: new IACR listings go live without review. The regex classification gets a small fraction of `type`/`region`/`area` tags wrong; fix those by editing `_data/positions.yml` directly. If you'd prefer a review gate instead, change the workflow's final step to open a pull request rather than push to `main`.

## Adding a position by hand

Just append an entry to `_data/positions.yml`:

```yaml
- name: "Crypto Group at Example University"
  role: "Postdoctoral Researcher"
  type: postdoc                         # postdoc | research_scientist | faculty | intern | visiting | phd
  region: europe                        # india | europe | north_america | asia_pacific | middle_east | africa | remote
  country: "Germany"
  institution: "Example University"
  pi: "Prof. Foo Bar"
  link: "https://example.edu/jobs/123"
  deadline: "2026-08-15"                # or "rolling"
  posted: "2026-05-27"
  area: [mpc, fhe]                      # see filters in _config.yml for full list
  status: open                          # open | standing | contact | expired
  note: "Short comment shown on the card."
  source: direct
```

## Extending the filters

Filter taxonomies live in two places that must stay in sync:

1. `_config.yml` → `filter_groups` (documentation only)
2. `index.html` → the `<option>` lists inside each `<select>` and the area chips loop
3. `assets/css/style.css` → optional per-tag colour styling

If you add a new region (say `latin_america`), edit all three.

## Filter UI

- **Selects** for `type`, `region`, `status` (single-pick).
- **Chips** for `area` (multi-pick — checking multiple acts as AND).
- **Search** is a free-text substring match against name, institution, PI, role and note.
- Filters are reflected in the URL hash, so you can share filtered views (e.g. `#type=postdoc&region=india&areas=mpc,fss`).

## Local development

```bash
bundle install
bundle exec jekyll serve --livereload
# open http://127.0.0.1:4000/
```

To test the IACR fetcher locally (it appends any new listings to `_data/positions.yml`):

```bash
pip install pyyaml
python scripts/fetch_iacr_jobs.py
git diff _data/positions.yml      # review what it appended
```

## Optional: add more feeds

The fetcher pattern in `scripts/fetch_iacr_jobs.py` is small and easy to fork. Drop in additional polling scripts for:
- EURAXESS (RSS available)
- IIT system openings (HTML scrape required)
- CRA jobs (RSS available)
- Cryptography Researchers of India (collaborate with maintainers; consider a single shared YAML)

Then add corresponding workflows under `.github/workflows/`.

## License

MIT for the code. The position data is curated and may contain errors — always verify with the host institution before applying.

## Acknowledgements

- [mpc-deadlines](https://github.com/mpc-deadlines/mpc-deadlines.github.io) for the structural inspiration.
- [sec-deadlines](https://github.com/sec-deadlines/sec-deadlines.github.io) for the original deadline-tracker pattern.
- [Cryptography Researchers of India](https://cryptography-research-india.github.io/) for the India-focused community resource — their `positions` page is "under construction" and we'd encourage contributing back upstream.
- [IACR](https://iacr.org/jobs/) for maintaining the canonical positions feed.
