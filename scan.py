"""The scan command: search Google Maps around a point for each category."""

import argparse
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request

from classify import classify
from db import Database
from scraper import BlockedError, MapsScraper, Place


class Scan:
    """One run of the scan command: search Google Maps for each category in
    every grid cell around the center point.

    Steps (see run()):
      1. resolve_center - turn --near/--coords into a (lat, lng) point
      2. build_grid     - cover the search circle with square cells
      3. search_cell    - search one category in one cell with MapsScraper
    """

    KM_PER_DEGREE_LAT = 111.32
    GEOCODE_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, categories: list[str], radius_km: float, cell_size_km: float,
                 near: str | None = None, coords: tuple[float, float] | None = None,
                 max_places: int = 500, headless: bool = False, fresh: bool = False,
                 db_path: str = "finder.db"):
        self.categories = categories
        self.radius_km = radius_km
        self.cell_size_km = cell_size_km
        self.near = near
        self.coords = coords
        self.max_places = max_places
        self.headless = headless
        self.fresh = fresh
        self.db_path = db_path
        self.places: dict[str, Place] = {}   # place_id -> Place, found this run

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Scan":
        """Build a Scan from the parsed command-line arguments."""
        return cls(
            categories=args.categories,
            radius_km=args.radius,
            cell_size_km=args.cell_size,
            near=args.near,
            coords=args.coords,
            max_places=args.max_places,
            headless=args.headless,
            fresh=args.fresh,
            db_path=args.db,
        )

    def run(self) -> int:
        """Run the whole scan. Returns an exit code."""
        try:
            # get the centre point, either from --coords or by looking up --near with OpenStreetMap
            center = self.resolve_center()
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        # split the search circle into small cells; one search per cell finds far more
        # businesses than a single wide search (see build_grid for why)
        cells = self.build_grid(center)
        jobs = len(cells) * len(self.categories)
        # print(f"searching {len(cells)} cells x {len(self.categories)} categories = {jobs} searches")
        # print(f"center {center[0]:.5f},{center[1]:.5f}, radius {self.radius_km:g} km")
        print(f"{len(cells)} cells x {len(self.categories)} categories = {jobs} searches")

        # search every cell for every category until done or --max-places is reached
        try:
            self.search_all(cells)
        except BlockedError as exc:
            print(f"error: {exc}. Stopping; wait a while before scanning again.", file=sys.stderr)
            self.finish()
            return 1
        except KeyboardInterrupt:
            print("\nstopped by user")
        return self.finish()

    def search_all(self, cells: list[tuple[float, float]]) -> None:
        """Open the browser and search every cell for every category.

        Searches finished in an earlier run are skipped unless --fresh is given.
        Stops early once --max-places new places have been found. BlockedError
        and KeyboardInterrupt are left for run() to handle.
        """
        jobs = len(cells) * len(self.categories)
        with Database(self.db_path) as db, MapsScraper(headless=self.headless) as maps:
            job = 0
            for cell in cells:
                for category in self.categories:
                    job += 1
                    if not self.fresh and db.job_done(cell, category):
                        print(f"[{job}/{jobs}] '{category}' at {cell[0]:.5f},{cell[1]:.5f} (done earlier, skipping)")
                        continue
                    if len(self.places) >= self.max_places:
                        print(f"reached --max-places ({self.max_places}), stopping")
                        return
                    print(f"[{job}/{jobs}] '{category}' at {cell[0]:.5f},{cell[1]:.5f}")
                    self.search_cell(maps, db, cell, category)

# This gets the coordinates of the center point, either from --coords or by looking up --near with OpenStreetMap.
    def resolve_center(self) -> tuple[float, float]:
        """Return the center point, looking up --near with OpenStreetMap if needed.

        Raises LookupError if the address can't be found or the lookup fails.
        """
        if self.coords:
            return self.coords
        if not self.near:
            raise LookupError("no location given; use --near or --coords")

        # Nominatim's usage policy requires an identifying User-Agent and at most
        # one request per second; we only make one request per scan.
        query = urllib.parse.urlencode({"q": self.near, "format": "json", "limit": 1})
        request = urllib.request.Request(
            f"{self.GEOCODE_URL}?{query}",
            headers={"User-Agent": "job-finder/0.1 (personal lead finder)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                results = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LookupError(f"couldn't look up '{self.near}': {exc}") from exc

        if not results:
            raise LookupError(f"no place found for '{self.near}'; try a fuller address or --coords")
        place = results[0]
        print(f"found: {place.get('display_name', self.near)}")
        return float(place["lat"]), float(place["lon"])

# Return the center point of every cell that overlaps the search circle. "
    def build_grid(self, center: tuple[float, float]) -> list[tuple[float, float]]:
        lat, lng = center
        km_per_degree_lng = self.KM_PER_DEGREE_LAT * math.cos(math.radians(lat))
        steps = math.ceil(self.radius_km / self.cell_size_km)
        # A cell overlaps the circle if its center is within radius + half its diagonal.
        reach = self.radius_km + self.cell_size_km * math.sqrt(2) / 2

        cells = []
        for row in range(-steps, steps + 1):
            for col in range(-steps, steps + 1):
                dy, dx = row * self.cell_size_km, col * self.cell_size_km
                if math.hypot(dx, dy) <= reach:
                    cells.append((lat + dy / self.KM_PER_DEGREE_LAT,
                                  lng + dx / km_per_degree_lng))
        return cells

    def search_cell(self, maps: MapsScraper, db: Database,
                    cell: tuple[float, float], category: str) -> None:
        """Search one category in one cell and save every place we haven't seen yet.

        Places already in the database (from this run or an earlier one) are skipped
        without being opened; with --fresh only this run's places are skipped, so
        older ones are re-read and updated. Each place is saved as soon as it's read.
        """
        def save(place: Place) -> None:
            level, reason = classify(place.website)
            db.save_place(place, category, level, reason)
            self.places[place.place_id] = place
            closed = "" if place.status == "open" else f" [{place.status}]"
            email = f" | {place.email}" if place.email else ""
            print(f"    [{level}] {place.name} | {place.phone or '-'}{email} | {reason}{closed}")

        def skip(place_id: str) -> bool:
            return place_id in self.places or (not self.fresh and db.has_place(place_id))

        limit = self.max_places - len(self.places)
        result = maps.search(cell[0], cell[1], category, skip=skip, limit=limit, on_place=save)

        # Only mark the search done if it wasn't cut short by --max-places,
        # otherwise a later run should search this cell again.
        if len(result.places) < limit:
            db.finish_job(cell, category, result.found, len(result.places), result.hit_cap)

        print(f"    {result.found} results, {len(result.places)} new, {len(self.places)} this run")
        if result.hit_cap:
            print("    note: hit Google's ~120 result limit here; a smaller --cell-size would find more")

    def finish(self) -> int:
        """Print a summary of what this run found. Returns exit code 0."""
        leads = [(classify(p.website), p) for p in self.places.values() if p.status == "open"]
        leads = [(level, reason, p) for (level, reason), p in leads if level in ("none", "social")]
        print(f"\ndone: {len(self.places)} places this run, {len(leads)} open leads"
              f" (no website or social/booking page only), saved to {self.db_path}")
        for level, reason, place in leads:
            email = f" | {place.email}" if place.email else ""
            print(f"  [{level}] {place.name} | {place.phone or '-'}{email} | {place.address or '-'} | {reason}")
        return 0
