# How job-finder works, in plain English

## What it's for

Lots of local businesses (barbers, plumbers, nail salons, cafés) are doing fine but
have no website, or only a Facebook page, or a website that's broken or years out of
date. Those businesses are people you could offer to build or fix a website for.

Finding them by hand means clicking through Google Maps one listing at a time. This tool
does the clicking for you and hands you a list: who they are, their phone number, where
they are, and what's wrong with their online presence.

## The big picture

You use it in four steps, each a separate command:

```
1. scan         Go through Google Maps and write down every business in the area
2. check-sites  Visit the websites we found and spot the broken or outdated ones
3. export       Turn the list into a spreadsheet
4. map          Put the list on a map
```

Everything the tool learns goes into one file, `finder.db`. Think of it as the tool's
notebook. Each step reads from the notebook and adds to it, so you can stop at any point
and pick up later.

## Sorting businesses into four groups

Every business ends up in one of four groups:

| Group | Meaning | Good lead? |
|---|---|---|
| **none** | No website at all | Best |
| **social** | Only a Facebook/Instagram page, or only a booking page (like Booksy or Square) | Very good |
| **weak** | Has a website, but it's broken, insecure, doesn't work on phones, or is years old | Good |
| **has_site** | Has a working website | Not a lead |

Booking pages count as "social" because they're not the business's own website. The
business doesn't control how it looks and can't put much on it.

---

## Step 1: `scan` — collecting businesses

```
python main.py scan --near "Columbus, OH" --radius 5km --categories barber,plumber
```

### Finding the middle of the area (`resolve_center`)

The tool needs a precise point on the globe to start from. If you typed an address like
"Columbus, OH", it asks OpenStreetMap (a free, public map service) for that address's
coordinates. If you typed coordinates yourself, it uses them directly. It prints the place
it found so you can check it picked the right Columbus.

### Splitting the area into squares (`build_grid`)

Here's the catch with Google Maps: however far you scroll, one search stops at about 120
results. It also shows the most popular places first. So one big search over a whole city
would miss most small businesses, and small businesses are exactly the ones we want.

The fix is to cut the area into small squares and search each one separately, zoomed in:

```
    ┌───┬───┬───┬───┬───┐
    │   │ · │ · │ · │   │
    ├───┼───┼───┼───┼───┤       ● = the middle point you gave
    │ · │ · │ · │ · │ · │       · = one search happens here
    ├───┼───┼───┼───┼───┤
    │ · │ · │ ● │ · │ · │       Corners outside your circle are skipped.
    ├───┼───┼───┼───┼───┤
    │ · │ · │ · │ · │ · │
    ├───┼───┼───┼───┼───┤
    │   │ · │ · │ · │   │
    └───┴───┴───┴───┴───┘
```

With the default settings, that's 49 squares. Every square is searched for every business
type you asked for, so 2 types means 98 searches.

### Searching one square (`search_cell` and the scraper)

For each square, the tool opens a real Chrome browser and does what you would:

1. Opens Google Maps and searches "barber" centred on that square.
2. If Google asks about cookies (it does in Europe), clicks "Reject all".
3. Scrolls the results list to the bottom so all of them load.
4. Clicks each business one by one and reads its details panel: name, phone, website,
   address, category, star rating, and whether it's closed.
5. Waits a second or two between clicks, like a person would.

**Why a real browser?** Google Maps is built to be used by people in a browser. A real
browser behaves like a person, so Google is less likely to block it. That's also why the
window is visible by default.

**Skipping repeats.** Squares next to each other return many of the same businesses.
Every business on Google has a unique ID, so the tool remembers which IDs it already has
and doesn't click those again. This saves a lot of time.

**Saving as it goes.** Each business goes into the notebook the moment it's read. If
your computer crashes, Google blocks you, or you press Ctrl+C, nothing already read is
lost.

**Picking up where you left off.** When a square finishes, the tool writes down "square X,
barber: done". Run the same command again and it skips everything already done.

**If Google gets suspicious.** If Google shows a "prove you're not a robot" page, the tool
stops straight away rather than keep trying, which would make things worse. Wait a while,
then run it again. It will resume.

### Deciding the group (`classify`)

As each business is saved, the tool looks at its website link:
- No link → **none**
- Link goes to Facebook, Instagram, Linktree, Booksy, Square, etc. → **social**
- Anything else → **has_site** for now. Step 2 decides whether it's really **weak**.

---

## Step 2: `check-sites` — is the website any good?

```
python main.py check-sites
```

A business with a website looks fine on Google Maps. But if the website doesn't load, or
looks like it's from 2014, they need help just as much. This step visits every website
from step 1 and checks it. It visits 8 sites at a time, so it's quick, and it doesn't
touch Google at all, so there's no risk of being blocked.

A website is marked **weak** if:

| Problem | What it means for the owner |
|---|---|
| Domain doesn't exist | The site is gone. Customers who click it get an error |
| Error page (like "404 Not Found") | The site is broken |
| Doesn't load | The site is down or very slow |
| Domain parked or for sale | They let the domain lapse. Someone else is selling it |
| Broken or missing HTTPS | Browsers show customers a "Not secure" warning |
| Not mobile-friendly | The site is hard to use on a phone, where most customers are |
| Copyright 5+ years old | Nobody has touched the site in years |
| "Coming soon" / "Under construction" | The site was never finished |

If a website just forwards to a Facebook or booking page, the business is moved to
**social**, because it doesn't really have a site.

**Collecting emails.** While it's on the website, the tool looks for an email address on
the home page, and if there isn't one, on the Contact page. It ignores fake template
addresses like `name@website.com`. Google Maps itself almost never shows emails, so this
is the main source of them. Businesses in the **none** group have no website to read an
email from, so for them the phone number is how you get in touch.

Each website is checked once. Run the command again and it only checks new ones. Add
`--recheck` to check them all again, for example to see whether someone fixed their site.

---

## Step 3: `export` — the spreadsheet

```
python main.py export
```

Creates `leads.csv`, which opens in Excel or Google Sheets. One row per business, best
leads first (none, then social, then weak), and higher-rated businesses first within
each group. Closed businesses are left out.

Each row has the name, phone, email, address, group, the reason (e.g. "no HTTPS" or
"Facebook page only"), rating, website, and a link to the business on Google Maps.

The reason column tells you what to say when you call: "I noticed your website shows a
'Not secure' warning…"

You can narrow it down:
- `--levels none` for only businesses with no website at all
- `--min-rating 4` for only well-reviewed (so, busy) businesses
- `--category barber` for only barbers

---

## Step 4: `map` — seeing it on a map

```
python main.py map
```

Creates `leads.html`. Open it in your browser and you'll see a map with a coloured dot
for each lead:

- 🔴 red: no website
- 🟠 orange: social or booking page only
- 🟣 purple: weak website

Click a dot to see the business's details, call them with one tap on a phone, or open
them in Google Maps. Use the tick boxes in the corner to show or hide each group.
Handy for planning which ones to visit in person.

---

## How the pieces fit together

```
                          ┌──────────────────────┐
  You type a command ───► │ main.py              │  Reads what you typed, checks it
                          │ (the front desk)     │  makes sense, passes it on
                          └──────────┬───────────┘
          ┌────────────────┬─────────┴──────┬──────────────────┐
          ▼                ▼                ▼                  ▼
     scan.py          sitecheck.py      export.py          leadmap.py
   (collect)          (inspect)       (spreadsheet)          (map)
      │   │                │                │                  │
      │   └─ scraper.py    │                │                  │
      │      (drives the   │                │                  │
      │       browser)     │                │                  │
      │                    │                │                  │
      └── classify.py ─────┘                │                  │
          (sorts into groups)               │                  │
                   │                        │                  │
                   ▼                        ▼                  ▼
            ┌──────────────────────────────────────────────────────┐
            │ db.py → finder.db   (the notebook everything shares)  │
            └──────────────────────────────────────────────────────┘
```

Each file does one job:

| File | Its job | Why it's separate |
|---|---|---|
| `main.py` | Front desk: understands your command | Keeps "what did you ask for" apart from "how do we do it" |
| `scan.py` | Plans and runs the search | The overall plan: where, which squares, in what order |
| `scraper.py` | Drives the browser on Google Maps | Google changes its pages often. When it breaks, this is the only file to fix |
| `classify.py` | Decides the group from a website link | Used by both scan and check-sites, so it lives in one place |
| `sitecheck.py` | Inspects websites | Completely different work from scraping Google |
| `db.py` | Reads and writes the notebook | Every step shares the same notebook, so all the storage rules live together |
| `export.py` | Makes the spreadsheet | |
| `leadmap.py` | Makes the map | |

Every command file is built the same way. There's a class that holds the settings, a
`from_args` method that fills the settings in from what you typed, and a `run` method that
does the work. That makes each one easy to find your way around once you've read one.

## Why it's built this way: key decisions

- **Many small searches instead of one big one.** Google's 120-result limit, and its
  habit of showing popular places first, would hide the small businesses we want.
- **A real, visible browser.** It looks like a person, so Google blocks it less.
- **Saving every business immediately.** Scraping is slow and can be interrupted. Nothing
  should be lost when it is.
- **Remembering finished searches.** A big area can take hours, so you can do it in
  several sittings.
- **Stopping on a CAPTCHA.** Pushing through makes a block last longer.
- **Website checks separate from scanning.** They're fast and don't involve Google, so
  they can run at full speed without risk, and can be repeated later on their own.
- **Booking pages count as "social".** The business still has no website of its own.
- **Leaving out closed businesses.** They aren't anyone to call.

## Good to know

- Scraping Google Maps goes against Google's terms of service. Keep it to your own local
  prospecting at a sensible pace.
- It's not fast: roughly 2–4 seconds per business. Try a small area first, e.g.
  `--radius 1km --max-places 20`.
- If a square shows "hit Google's ~120 result limit", that area is dense. Scan it again
  with a smaller `--cell-size` (like `750m`) to find more.
- Google changes its website from time to time. If `scan` suddenly finds nothing, the
  scraper probably needs its selectors updating (see `scraper.py`).
