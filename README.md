# job-finder

Finds local businesses on Google Maps that have **no website**, **only a social or
booking page**, or a **broken or outdated website**, and turns them into a call list and a
map. Built for finding clients who need a website.

```
scan  ──►  check-sites  ──►  export (leads.csv)
                        └──►  map    (leads.html)
```

## Setup

Requires Python 3.10+.

```
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Quick start

```
python main.py scan --near "Columbus, OH" --radius 1km --categories barber --max-places 20
python main.py check-sites
python main.py export
python main.py map
```

Open `leads.csv` in Excel or Google Sheets, and `leads.html` in a browser.

## Lead levels

Every business is sorted into one of four levels:

| Level | Meaning | Lead? |
|---|---|---|
| `none` | No website on Google Maps | Best |
| `social` | Only a Facebook/Instagram/Linktree page, or a booking page (Booksy, Square, …) | Yes |
| `weak` | Website is down, parked, has broken or no HTTPS, isn't mobile-friendly, is a placeholder, or has a copyright 5+ years old | Yes |
| `has_site` | Working website | No |

## Commands

### `scan` — collect businesses from Google Maps

```
python main.py scan --near "Columbus, OH" --radius 5km --categories "barber,nail salon"
```

Splits the area into a grid of small squares and searches each one for each category in a
real Chrome browser, reading every business's name, phone, website, address, category,
rating and open/closed status. Each business is saved the moment it's read. Rerunning the
same command resumes where it left off.

| Option | Default | |
|---|---|---|
| `--near ADDRESS` or `--coords LAT,LNG` | required | Center of the search (one of the two) |
| `--categories` | required | Comma-separated search terms |
| `--radius` | `5km` | Accepts `km`, `m` or `mi` |
| `--cell-size` | `1.5km` | Smaller finds more in dense areas, but takes longer |
| `--max-places` | `500` | Stop after this many new businesses |
| `--headless` | off | Hide the browser window |
| `--fresh` | off | Redo finished searches and refresh known businesses |

```
found: Columbus, Franklin County, Ohio, United States
5 cells x 1 categories = 5 searches
[1/5] 'barber' at 39.94653,-83.00000
    [has_site] Moses Barber & Groom | +16149148282 | website: mosesbarber.com
    [none] Shoulders Up Barber Boutique | +16142099484 | no website on Google Maps
    [social] Basement Cutz | +16145580458 | Booksy booking page only
    ...
```

### `check-sites` — find weak websites and emails

```
python main.py check-sites
```

Visits every website found by `scan`, marks broken or outdated ones as `weak`, and collects
email addresses from the homepage or contact page. Doesn't touch Google. Only unchecked
sites are visited; add `--recheck` to check them all again. `--timeout` sets seconds per
site (default 10).

### `export` — spreadsheet of leads

```
python main.py export --levels none,social --min-rating 4 -o columbus.csv
```

Writes open businesses to CSV, best leads first: name, phone, email, address, level,
reason, category, rating, website and Google Maps link.

| Option | Default | |
|---|---|---|
| `--levels` | `none,social,weak` | Which levels to include |
| `--min-rating` | `0` | Minimum star rating; unrated businesses are left out when set |
| `--category` | all | Only these search terms or Google categories |
| `-o` | `leads.csv` | Output file |

### `map` — leads on a map

```
python main.py map
```

Writes `leads.html`: a map with a pin per lead (red = no website, orange = social/booking,
purple = weak). Click a pin for contact details; use the legend to show or hide levels.
Options: `--levels`, `-o` (default `leads.html`). Needs internet to load the map.

### Global option

`--db FILE` uses a different database (default `finder.db`). It goes **before** the
command, e.g. `python main.py --db columbus.db scan ...`. Handy for keeping areas separate.

## Project layout

```
main.py        command line: parses options and runs the command
scan.py        scan: center lookup, grid, search loop
scraper.py     drives Chrome through Google Maps (all page selectors live here)
classify.py    decides a business's level from its website link
sitecheck.py   check-sites: website checks and email extraction
export.py      export to CSV
leadmap.py     HTML map
db.py          SQLite database (finder.db)
docs/          documentation
```

## Documentation

- [How it works, in plain English](docs/HOW-IT-WORKS.md): what each step does and why it's built that way
- [Technical reference](docs/TECHNICAL.md): modules, data flow, database schema and rules

## Troubleshooting

| Problem | Fix |
|---|---|
| `Google is showing a CAPTCHA` | Wait a few hours, then rerun the same command. It resumes. Scanning without `--headless` gets blocked less |
| `hit Google's ~120 result limit here` | The area is dense. Rerun with a smaller `--cell-size`, e.g. `750m` |
| `scan` suddenly finds nothing | Google changed its page. Update `SELECTORS` in `scraper.py` |
| `can't write leads.csv` | Close the file in Excel and rerun |
| `no place found for '...'` | Use a fuller address, or `--coords` |
| Negative latitude rejected | Write it with `=`: `--coords=-33.8,151.2` |

## Notes

- Scraping Google Maps is against Google's Terms of Service. Keep it to modest, personal use.
- It's deliberately slow (about 2–4 seconds per business) to avoid being blocked.
- Google Maps rarely lists emails; most come from `check-sites`. Businesses with no website
  usually only have a phone number.
- `finder.db`, `.browser-profile/`, `leads.csv` and `leads.html` are created at runtime and
  git-ignored.
