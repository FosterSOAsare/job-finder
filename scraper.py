"""Drive a real browser through Google Maps searches and read each place's details.

Google changes its page markup often. Every selector lives in SELECTORS below so
a breakage only needs fixing in one place.
"""

import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

SELECTORS = {
    "consent_reject": 'button:has-text("Reject all")',
    "feed": 'div[role="feed"]',
    "result_link": 'div[role="feed"] a[href*="/maps/place/"]',
    "end_of_list": "text=/reached the end of the list/i",
    "panel": 'div[role="main"]',
    "website": 'a[data-item-id="authority"]',
    "phone": 'button[data-item-id^="phone:tel:"]',
    "address": 'button[data-item-id="address"]',
    "category": 'button[jsaction*="category"]',
    "email": 'a[href^="mailto:"]',
    "rating": 'span[role="img"][aria-label$="stars"], span[role="img"][aria-label*="stars "]',
}

# Google's feature id, e.g. 0x88388faa6df24bb3:0xb6a37775b8f61eaf, and coordinates.
PLACE_ID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)")
COORDS_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zA-Z]{2,}")


class BlockedError(RuntimeError):
    """Google showed a CAPTCHA or 'unusual traffic' page."""


@dataclass
class Place:
    place_id: str
    name: str
    url: str
    lat: float | None = None
    lng: float | None = None
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    email: str | None = None
    rating: float | None = None
    status: str = "open"  # open | temporarily_closed | permanently_closed


@dataclass
class SearchResult:
    places: list[Place]   # places whose details were read
    found: int            # results in the list, including ones skipped
    hit_cap: bool         # the list stopped at Google's ~120 limit


class MapsScraper:
    """A browser session for Google Maps. Use as a context manager:

        with MapsScraper(headless=False) as maps:
            result = maps.search(39.96, -83.0, "barber")
    """

    ZOOM = 15
    RESULT_CAP = 120
    PROFILE_DIR = ".browser-profile"   # keeps cookies (incl. consent) between runs
    PAUSE = (1.0, 2.5)                 # random seconds between opening places
    SCROLL_PAUSE = 1.5
    STALL_LIMIT = 5                    # scrolls with no new results before giving up

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._context = None
        self.page: Page | None = None

    def __enter__(self) -> "MapsScraper":
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            self.PROFILE_DIR,
            headless=self.headless,
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        # Skip images, fonts and video: faster, and we only need the text.
        self._context.route("**/*", lambda route: route.abort()
                            if route.request.resource_type in ("image", "media", "font")
                            else route.continue_())
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._context:
                self._context.close()
        finally:
            if self._playwright:
                self._playwright.stop()

    def search(self, lat: float, lng: float, category: str,
               skip: Callable[[str], bool] = lambda place_id: False,
               limit: int | None = None,
               on_place: Callable[[Place], None] = lambda place: None) -> SearchResult:
        """Search one category around one point and read every result's details.

        skip(place_id) -> True means we already have that place, so don't open it.
        limit caps how many places are opened in this search.
        on_place(place) is called as soon as each place is read, so callers can
        save it before the search finishes (nothing is lost if it's interrupted).
        """
        page = self.page
        query = urllib.parse.quote(category)
        page.goto(f"https://www.google.com/maps/search/{query}/@{lat},{lng},{self.ZOOM}z?hl=en",
                  wait_until="domcontentloaded")
        self._handle_consent()
        self._check_blocked()

        # Either a results list, a single place (Maps jumps straight to it), or nothing.
        try:
            page.wait_for_selector(f'{SELECTORS["feed"]}, {SELECTORS["panel"]} h1', timeout=20000)
        except PlaywrightTimeout:
            self._check_blocked()
            return SearchResult(places=[], found=0, hit_cap=False)

        if page.locator(SELECTORS["feed"]).count() == 0:
            place = self._read_open_place(page.url)
            if not place:
                return SearchResult(places=[], found=0, hit_cap=False)
            if skip(place.place_id):
                return SearchResult(places=[], found=1, hit_cap=False)
            on_place(place)
            return SearchResult(places=[place], found=1, hit_cap=False)

        links = self._scroll_results()
        places = []
        for name, href in links:
            place_id = _place_id(href)
            if skip(place_id):
                continue
            if limit is not None and len(places) >= limit:
                break
            place = self._open_result(name, href)
            if place:
                places.append(place)
                on_place(place)
            time.sleep(random.uniform(*self.PAUSE))
        return SearchResult(places=places, found=len(links), hit_cap=len(links) >= self.RESULT_CAP)

    def _handle_consent(self) -> None:
        """Click through Google's cookie-consent page (shown in the EU/UK)."""
        if "consent.google." not in self.page.url:
            return
        self.page.locator(SELECTORS["consent_reject"]).first.click()
        self.page.wait_for_url("**/maps/**", timeout=20000)

    def _check_blocked(self) -> None:
        url = self.page.url
        if "/sorry/" in url or "recaptcha" in url:
            raise BlockedError("Google is showing a CAPTCHA / unusual-traffic page")

    def _scroll_results(self) -> list[tuple[str, str]]:
        """Scroll the results list to the end and return (name, href) for each result."""
        page = self.page
        feed = page.locator(SELECTORS["feed"])
        links = page.locator(SELECTORS["result_link"])
        last_count, stalls = 0, 0
        while True:
            if page.locator(SELECTORS["end_of_list"]).count():
                break
            count = links.count()
            if count >= self.RESULT_CAP:
                break
            stalls = stalls + 1 if count == last_count else 0
            if stalls >= self.STALL_LIMIT:
                break
            last_count = count
            feed.evaluate("el => el.scrollTo(0, el.scrollHeight)")
            time.sleep(self.SCROLL_PAUSE)

        return [(link.get_attribute("aria-label") or "", link.get_attribute("href") or "")
                for link in links.all()]

    def _open_result(self, name: str, href: str) -> Place | None:
        """Click a result in the list and read its details panel."""
        page = self.page
        try:
            page.locator(f'{SELECTORS["result_link"]}[href="{href}"]').first.click()
            self._panel_for(name).wait_for(timeout=15000)
        except (PlaywrightTimeout, PlaywrightError):
            self._check_blocked()
            print(f"    ! couldn't open '{name}', skipping")
            return None
        return self._read_panel(self._panel_for(name), name, href)

    def _read_open_place(self, url: str) -> Place | None:
        """Read the details panel when the search went straight to one place."""
        panel = self.page.locator(SELECTORS["panel"]).filter(has=self.page.locator("h1")).first
        name = panel.locator("h1").first.inner_text().strip()
        return self._read_panel(panel, name, url) if name else None

    def _panel_for(self, name: str):
        heading = self.page.locator("h1", has_text=re.compile(rf"^\s*{re.escape(name)}\s*$"))
        return self.page.locator(SELECTORS["panel"]).filter(has=heading).first

    def _read_panel(self, panel, name: str, href: str) -> Place:
        place = Place(place_id=_place_id(href), name=name, url=href)
        coords = COORDS_RE.search(href)
        if coords:
            place.lat, place.lng = float(coords.group(1)), float(coords.group(2))

        website = _attr(panel, SELECTORS["website"], "href")
        place.website = _unwrap_google_redirect(website) if website else None

        phone_id = _attr(panel, SELECTORS["phone"], "data-item-id")
        place.phone = phone_id.removeprefix("phone:tel:") if phone_id else None

        address = _attr(panel, SELECTORS["address"], "aria-label")
        place.address = address.removeprefix("Address:").strip() if address else None

        category = panel.locator(SELECTORS["category"])
        place.category = category.first.inner_text().strip() if category.count() else None

        rating = _attr(panel, SELECTORS["rating"], "aria-label")
        match = re.search(r"\d+(?:\.\d+)?", rating or "")
        place.rating = float(match.group()) if match else None

        text = panel.inner_text()

        # Maps rarely lists an email, but take one if the panel shows it.
        mailto = _attr(panel, SELECTORS["email"], "href")
        if mailto:
            place.email = urllib.parse.unquote(mailto.removeprefix("mailto:").split("?")[0]) or None
        else:
            match = EMAIL_RE.search(text)
            place.email = match.group() if match else None

        if "Permanently closed" in text:
            place.status = "permanently_closed"
        elif "Temporarily closed" in text:
            place.status = "temporarily_closed"
        return place


def _attr(panel, selector: str, name: str) -> str | None:
    element = panel.locator(selector)
    return element.first.get_attribute(name) if element.count() else None


def _place_id(href: str) -> str:
    """Google's stable id for a place, falling back to the URL without its query."""
    match = PLACE_ID_RE.search(href)
    return match.group(1) if match else href.split("?")[0]


def _unwrap_google_redirect(url: str) -> str:
    """Turn https://www.google.com/url?q=https://example.com into https://example.com."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        target = urllib.parse.parse_qs(parsed.query).get("q")
        if target:
            return target[0]
    return url
