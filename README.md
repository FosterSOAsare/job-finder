# job-finder

Finds local businesses on Google Maps that have no website or online presence.

> **Status:** the command line, address lookup and grid are built. Google Maps
> scraping, the database, website checks, export and the map are **not built yet**.

## What counts as "online presence"

| Level | Rule |
|---|---|
| `none` | The Maps listing has no website link |
| `social` | The website link goes to Facebook, Instagram, Linktree, WhatsApp, etc. |
| `weak` | The site is dead, parked, insecure, not mobile-friendly or outdated |
| `has_site` | A working website (not a lead) |

## Usage

```
python main.py scan --near "Columbus, OH" --radius 5km --categories barber,plumber
python main.py scan --coords 39.96,-83.0 --radius 3mi --categories "nail salon"
python main.py -h            # list commands
python main.py scan -h       # options for one command
```

Requires Python 3.10+. No packages to install yet (standard library only).

### Commands

| Command | Status | Purpose |
|---|---|---|
| `scan` | partly built | Search Google Maps around a point |
| `check-sites` | not built | Flag weak websites |
| `export` | not built | Write leads to CSV |
| `map` | not built | Write an HTML map of leads |

Until a command is built, it just prints the options it received.

### `scan` options

| Option | Default | Notes |
|---|---|---|
| `--near ADDRESS` | — | Center as an address. Give exactly one of `--near` / `--coords` |
| `--coords LAT,LNG` | — | Center as coordinates. For a negative latitude use `--coords=-33.8,151.2` |
| `--categories` | required | Comma-separated, e.g. `"barber,plumber,nail salon"` |
| `--radius` | `5km` | Accepts `km`, `m` or `mi`; a bare number means km |
| `--cell-size` | `1.5km` | Size of each grid cell |
| `--max-places` | `500` | Stop after this many new places per run |
| `--headless` | off | Run the browser without a window |
| `--fresh` | off | Ignore saved progress and rescan everything |
| `--db` | `finder.db` | Database file. Goes **before** the command: `main.py --db x.db scan ...` |

## How it works

### Files

| File | Contents |
|---|---|
| `main.py` | Command-line parsing and dispatch |
| `scan.py` | The `Scan` class: center lookup, grid, search loop |

### Flow of `python main.py scan ...`

```
main.py
  main()
   ├─ build_parser()        define commands and options
   ├─ parser.parse_args()   read the command line, convert values, apply defaults
   ├─ validate()            cross-option checks (--coords range, cell size, ...)
   └─ Scan.from_args(args).run()
        │
scan.py │
  Scan.run()
   ├─ resolve_center()      --coords → used as-is
   │                        --near   → looked up with OpenStreetMap (Nominatim)
   ├─ build_grid(center)    cover the search circle with square cells
   └─ for each cell × category:
        search_cell()       ← placeholder: prints what it would search
```

### 1. `main()` — `main.py`

1. **`build_parser()`** describes every command and option. It runs nothing; argparse
   uses it to read input and generate `-h` help.
2. **`parser.parse_args(argv)`** matches the command line against that description.
   The command comes first, then its options in any order. `type=` functions convert
   values (`parse_radius` turns `"3mi"` into `4.83` km; `parse_list` splits
   `"barber,plumber"`). Bad input prints an error and exits with code 2.
3. **`validate()`** runs checks that need several options or extra work: splits and
   range-checks `--coords` into a `(lat, lng)` tuple, and makes sure `--cell-size`
   fits in the radius and `--max-places` is positive.
4. For `scan`, **`Scan.from_args(args)`** creates a `Scan` object (it's a
   `@classmethod`, so it's called on the class and builds the object with
   `cls(...)`), then **`.run()`** starts it. Its return value becomes the exit code.

### 2. `Scan.run()` — `scan.py`

**Step 1: `resolve_center()`** turns the location into one `(lat, lng)` point.

- `--coords` given: returned as-is.
- `--near` given: sent to `https://nominatim.openstreetmap.org/search`, and the first
  match is used. The matched place name is printed so a wrong match is easy to spot.
- If the address isn't found or the lookup fails, it raises `LookupError`. `run()`
  catches it, prints `error: ...` and returns exit code 1.

**Step 2: `build_grid(center)`** splits the circle of `--radius` around the center into
squares of `--cell-size` and returns the middle point of each one. Squares that don't
touch the circle (the corners) are dropped.

Why a grid instead of one search: a single Google Maps search returns at most ~120
results and favours prominent places near the middle of the view. Small businesses
(the leads we want) get left out. Many small, zoomed-in searches cover the area evenly.

```
    ┌───┬───┬───┬───┬───┐
    │   │ · │ · │ · │   │
    ├───┼───┼───┼───┼───┤
    │ · │ · │ · │ · │ · │     ● center
    ├───┼───┼───┼───┼───┤     · cell center (one search each)
    │ · │ · │ ● │ · │ · │
    ├───┼───┼───┼───┼───┤     default 5 km radius, 1.5 km cells = 49 cells
    │ · │ · │ · │ · │ · │
    ├───┼───┼───┼───┼───┤
    │   │ · │ · │ · │   │
    └───┴───┴───┴───┴───┘
```

**Step 3: `search_cell(cell, category)`** is called once per cell per category.
**Not built yet.** It only prints the search it would run.

### Example output

```
$ python main.py scan --near "Columbus, OH" --radius 3km --categories barber
found: Columbus, Franklin County, Ohio, United States
center 39.96226,-83.00071, radius 3 km
21 cells x 1 categories = 21 searches
  [todo] search 'barber' at 39.93531,-83.01829
  ...
```

## Next steps

1. `search_cell`: open Google Maps with Playwright, scroll the results, read each
   place (name, phone, website, rating, reviews).
2. Save places to SQLite, skip duplicates, record finished jobs so runs can resume.
3. Classify each place as `none` / `social` / `weak` / `has_site`.
4. `check-sites`, `export` and `map` commands.
