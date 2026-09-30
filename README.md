# job-finder

Finds local businesses on Google Maps that have no website, only a social or booking
page, or a broken or outdated website, and gives you a call list and a map of them.

## Setup

```
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Requires Python 3.10+.

## Usage

```
python main.py scan --near "Columbus, OH" --radius 5km --categories barber,plumber
python main.py check-sites
python main.py export        # -> leads.csv
python main.py map           # -> leads.html
```

Try a small area first: `--radius 1km --max-places 20`. Run any command with `-h` for
its options.

| Level | Meaning |
|---|---|
| `none` | No website on Google Maps |
| `social` | Only a social, link-in-bio or booking page |
| `weak` | Website is down, parked, insecure, not mobile-friendly or outdated |
| `has_site` | Working website (not a lead) |

## Documentation

- [How it works, in plain English](docs/HOW-IT-WORKS.md): what each step does and why
- [Technical reference](docs/TECHNICAL.md): modules, data flow, database schema, rules

Scraping Google Maps is against Google's Terms of Service. Keep volume modest.
