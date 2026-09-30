# job-finder: technical reference

Command-line tool that scrapes Google Maps for local businesses, classifies each by
online presence, checks their websites, and exports leads as CSV or an HTML map.

- Python 3.10+, standard library plus [Playwright](https://playwright.dev/python/) (browser automation)
- Storage: a single SQLite file (`finder.db` by default)
- Entry point: `python main.py <command>`

## Setup

```
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Commands

```
python main.py [--db FILE] scan (--near ADDRESS | --coords LAT,LNG) --categories LIST [options]
python main.py [--db FILE] check-sites [--timeout SECONDS] [--recheck]
python main.py [--db FILE] export [--levels LIST] [--min-rating N] [--category LIST] [-o FILE]
python main.py [--db FILE] map [--levels LIST] [-o FILE]
```

`--db` is a global option and must come **before** the command.

| Command | Option | Default | Notes |
|---|---|---|---|
| `scan` | `--near` / `--coords` | required, exactly one | For a negative latitude write `--coords=-33.8,151.2` |
| | `--categories` | required | Comma-separated search terms |
| | `--radius` | `5km` | `km`, `m`, `mi`; bare number = km |
| | `--cell-size` | `1.5km` | Grid cell size; must not exceed the diameter |
| | `--max-places` | `500` | New places opened per run |
| | `--headless` | off | Hide the browser window (blocked more often) |
| | `--fresh` | off | Rerun finished searches and re-read known places |
| `check-sites` | `--timeout` | `10` | Seconds per HTTP request |
| | `--recheck` | off | Include sites already checked |
| `export` | `--levels` | `none,social,weak` | |
| | `--min-rating` | `0` | When > 0, unrated places are excluded |
| | `--category` | all | Matches `search_category` or Google `category`, case-insensitive |
| | `-o` | `leads.csv` | |
| `map` | `--levels` | `none,social,weak` | |
| | `-o` | `leads.html` | |

Exit codes: `0` success, `1` runtime error (address not found, Google block, missing DB,
file locked), `2` invalid arguments (argparse).

## Online-presence levels

| Level | Assigned by | Rule |
|---|---|---|
| `none` | `classify()` during scan | No website link on the Maps listing |
| `social` | `classify()` during scan, or `check_site()` | Link host matches `SOCIAL_DOMAINS` or `BOOKING_DOMAINS`, or the site redirects to one |
| `weak` | `check_site()` | Site fails one or more health checks |
| `has_site` | `classify()` / `check_site()` | Anything else |

## Module map

```
main.py       CLI: argument parsing, validation, dispatch to a command class
scan.py       Scan: center lookup, grid, search loop, per-place save
scraper.py    MapsScraper: Playwright session, Maps search, result/panel parsing; Place dataclass
classify.py   classify(): website link -> (level, reason)
db.py         Database: schema, migrations, all SQL
sitecheck.py  SiteCheck + check_site(): website health checks and email extraction
export.py     Export: leads -> CSV
leadmap.py    LeadMap: leads -> self-contained Leaflet HTML page
```

Dependency direction (no cycles):

```
main ─┬─ scan ──────┬─ scraper
      │             ├─ classify
      │             └─ db ── scraper (Place)
      ├─ sitecheck ─┬─ classify
      │             └─ db
      ├─ export ────── db
      └─ leadmap ───── db
```

Every command follows the same shape: a class with `__init__` (plain settings),
`from_args(args)` (`@classmethod` mapping argparse output to `__init__`), and `run() -> int`
(returns the exit code). `main()` only parses, validates and dispatches.

## `main.py`

| Function | Purpose |
|---|---|
| `parse_radius(value)` | argparse `type=`: `"3mi"` → `4.828` km. Raises `ArgumentTypeError` on bad input |
| `parse_list(value)` | argparse `type=`: `"a, b,"` → `["a", "b"]` |
| `parse_levels(value)` | `parse_list` + rejects names not in `LEVELS` |
| `build_parser()` | Declares the global `--db` and one subparser per command |
| `validate(args, parser)` | Cross-option checks argparse can't express: parses `--coords` into a `(lat, lng)` tuple and range-checks it; `--cell-size <= 2 × --radius`; `--max-places > 0`. Fails via `parser.error()` (exit 2) |
| `main(argv)` | Reconfigures stdout/stderr to UTF-8 (Windows consoles), parses, validates, dispatches |

## `scan.py` — `Scan`

```
run()
 ├─ resolve_center()          -> (lat, lng) or LookupError → exit 1
 ├─ build_grid(center)        -> [(lat, lng), ...] cell centers
 ├─ search_all(cells)         BlockedError → exit 1; Ctrl+C → stop cleanly
 │   └─ for cell × category:
 │        skip if db.job_done() (unless --fresh)
 │        stop if --max-places reached
 │        search_cell(maps, db, cell, category)
 └─ finish()                  summary of this run's leads
```

**`resolve_center()`** returns `--coords` as-is, or geocodes `--near` with
[Nominatim](https://nominatim.org/release-docs/latest/api/Search/) (`limit=1`, identifying
`User-Agent`, one request per scan, within the usage policy). Network errors, timeouts and
empty results raise `LookupError`.

**`build_grid(center)`** lays a square grid of `cell_size_km` over the circle of
`radius_km`. km offsets are converted to degrees with 111.32 km per degree of latitude and
`111.32 × cos(lat)` per degree of longitude. A cell is kept when its center is within
`radius + cell_size × √2 / 2` of the center (radius plus half the cell diagonal), so every
cell that overlaps the circle is included. Defaults (5 km / 1.5 km) give 49 cells.

*Why a grid:* one Maps search returns at most ~120 results and favours prominent places near
the viewport center. Small zoomed-in searches cover the area evenly and surface the
low-profile businesses that are the actual leads. Each (cell, category) pair is also a
resumable unit of work.

**`search_cell(maps, db, cell, category)`** calls `MapsScraper.search` with:
- `skip(place_id)`: true if seen this run, or already in the DB (unless `--fresh`)
- `limit`: remaining `--max-places` budget
- `on_place(place)`: `classify()` → `db.save_place()` → print. Places are committed one at a
  time, so interruption loses at most the place being read.

The job is recorded with `db.finish_job()` only if the search wasn't truncated by `limit`.

## `scraper.py` — `MapsScraper`

Context manager around a Playwright **persistent** Chromium context in `.browser-profile/`
(keeps cookies, including consent, between runs). Images, media and fonts are blocked via
`context.route`. Locale is forced to `en-US` and URLs carry `hl=en` so text matching works.

**`search(lat, lng, category, skip, limit, on_place) -> SearchResult`**
1. `goto https://www.google.com/maps/search/{category}/@{lat},{lng},15z?hl=en`
2. `_handle_consent()`: on `consent.google.*`, click "Reject all" (EU/UK)
3. `_check_blocked()`: `/sorry/` or `recaptcha` in URL → `BlockedError`
4. Wait for the results feed, or a single-place panel (Maps jumps straight to a place when
   there's one match; handled by `_read_open_place`)
5. `_scroll_results()`: scroll `div[role=feed]` until "reached the end of the list", 120
   results, or 5 scrolls with no growth
6. For each result not skipped: `_open_result()` clicks it, waits for the details panel whose
   `h1` exactly matches the name, `_read_panel()` extracts fields, `on_place()` is called,
   then a random 1–2.5 s pause

`SearchResult` = `places` (read this search), `found` (listed, incl. skipped), `hit_cap`.

**Field extraction** (`SELECTORS` holds every selector; fix breakages there):

| Field | Source |
|---|---|
| `place_id` | `!1s0x…:0x…` in the result href (Google feature id); falls back to the URL without query |
| `lat`, `lng` | `!3d…!4d…` in the href |
| `website` | `a[data-item-id="authority"]` href, unwrapped from `google.com/url?q=` |
| `phone` | `button[data-item-id^="phone:tel:"]` |
| `address` | `button[data-item-id="address"]` aria-label |
| `category` | `button[jsaction*="category"]` |
| `rating` | star `span[role=img]` aria-label |
| `email` | `mailto:` link or email pattern in the panel text (rarely present) |
| `status` | "Permanently closed" / "Temporarily closed" in panel text |

Review counts are not shown to logged-out users and are not collected.

Selectors were verified against live Maps in Sept 2026. Google changes markup without notice;
expect to update `SELECTORS` occasionally.

## `classify.py`

`classify(website) -> (level, reason)`. Parses the host, strips `www.`, and matches it (or
any subdomain) against `SOCIAL_DOMAINS` (Facebook, Instagram, TikTok, X, YouTube, LinkedIn,
Linktree, WhatsApp, Yelp, Google Sites/Business) and `BOOKING_DOMAINS` (Square, Booksy,
Vagaro, Fresha, Setmore, StyleSeat, Calendly, Toast, DoorDash, Uber Eats, …). Booking and
ordering pages count as `social` because they aren't a site the business controls.

## `sitecheck.py` — `check_site()` and `SiteCheck`

`SiteCheck.run()` loads `db.places_to_check()` (level `has_site`/`weak`, unchecked unless
`--recheck`), runs `check_site()` in a `ThreadPoolExecutor` (8 workers), and saves each
result on the main thread with `db.save_site_check()`. An unexpected exception in one check
is printed and that place is left unchecked for the next run.

**`check_site(website, timeout) -> SiteReport(level, reason, email)`**

Fetching (`urllib`, browser `User-Agent`, 2 MB cap):
1. HTTPS. On a certificate error, record "broken HTTPS certificate" and refetch unverified.
2. If HTTPS can't connect, try HTTP (one retry on network failure); if the final URL is
   still `http:`, record "no HTTPS".
3. Failures: DNS → `weak` "domain doesn't exist"; HTTP 401/403/429/503 → `has_site`
   "couldn't check" (bot protection, not evidence of a broken site); other HTTP errors →
   `weak` "site returns error N"; otherwise `weak` "site doesn't load".

Content checks on the loaded page:

| Check | Result |
|---|---|
| Final URL is a social/booking domain | `social` "website redirects to …" |
| Final host is a parking service, or parked phrases on a short page (< 300 words) | `weak` "domain parked or for sale" |
| Placeholder phrase in `<title>`, or in text of a page < 150 words | issue "placeholder page" |
| No `<meta name="viewport">` | issue "not mobile-friendly" |
| Latest copyright year ≤ current year − 5 | issue "copyright YYYY" |

Any issues → `weak` with issues joined by `; `; none → `has_site` "website OK".

Email: `mailto:` links, Cloudflare-obfuscated `data-cfemail` (decoded), and plain addresses
on the homepage; if none, the first same-site link containing "contact" is fetched and
searched. Template placeholders and site-builder addresses (`JUNK_EMAIL_DOMAINS`) and image
filenames are discarded. An address on the site's own domain is preferred.

## `db.py` — `Database`

Opens (creating if needed) the SQLite file, applies `SCHEMA`, then `_add_missing_columns()`
adds any column in `ADDED_COLUMNS` missing from an older database. Every write commits
immediately.

**`places`** (primary key `place_id`)

| Column | Notes |
|---|---|
| `name`, `url`, `lat`, `lng`, `category`, `address`, `phone`, `website`, `email`, `rating`, `status` | From the scraper |
| `search_category` | The `--categories` term that found it |
| `level`, `level_reason` | From `classify()` / `check_site()` |
| `site_checked_at` | Set by check-sites; `NULL` = not yet checked |
| `first_seen`, `last_scraped` | UTC ISO timestamps |

**`jobs`** (primary key `lat, lng, category`, coords rounded to 6 decimals): `results`,
`new_places`, `hit_cap`, `finished_at`. One row per completed search.

**Upsert rules in `save_place()`** (re-scraping an existing place):
- `first_seen` is kept; `email` is kept if the new scrape found none.
- If check-sites already checked the site **and** the website link is unchanged, `level`,
  `level_reason` and `site_checked_at` are kept.
- If the website link changed, the level comes from `classify()` and `site_checked_at` is
  cleared so the next check-sites run checks the new link.

| Method | Used by |
|---|---|
| `has_place`, `save_place` | scan |
| `job_done`, `finish_job` | scan |
| `places_to_check`, `save_site_check` | check-sites |
| `leads(levels, min_rating, categories)` | export, map. Open places only, ordered `none`, `social`, `weak`, then rating desc, name |

## `export.py` — `Export`

Writes `db.leads()` to CSV using `COLUMNS` (header → DB column): level, name, phone, email,
address, category, rating, reason, website, google_maps, found_by, lat, lng, first_seen.
Encoded `utf-8-sig` so Excel detects UTF-8. A locked file (open in Excel) returns exit 1.

## `leadmap.py` — `LeadMap`

Writes one HTML file: Leaflet 1.9.4 from unpkg, OpenStreetMap tiles, one `circleMarker` per
lead colored by `LEVEL_COLORS`, one layer group per level toggled from the legend, popups
with tel/mailto/website/Maps links. Place data is embedded as JSON via `_script_json()`,
which escapes `</` so a business name can't close the `<script>` tag; popup strings are
HTML-escaped in JS. Places without coordinates are skipped and counted. Needs internet to
load Leaflet and tiles.

## Files created at runtime

| Path | Contents | In git |
|---|---|---|
| `finder.db` | SQLite database | ignored |
| `.browser-profile/` | Chromium profile (cookies, consent) | ignored |
| `leads.csv`, `leads.html` | Exports | ignored |

## Known limitations

- Scraping Google Maps is against Google's Terms of Service. Keep volume modest; the tool
  stops on a CAPTCHA rather than retrying.
- Throughput is roughly 2–4 s per opened place; a dense cell can take several minutes.
- Cells that hit the 120-result cap are reported but not automatically subdivided; use a
  smaller `--cell-size` in dense areas.
- Emails are rare for `none` and `social` leads (no site to read them from).
- Site checks read server HTML only; content rendered purely by JavaScript isn't seen, so a
  JS-only site may miss the viewport or copyright checks.
- The same business name appearing twice in one results list may briefly match the previous
  details panel.
