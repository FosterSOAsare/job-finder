"""The scan command: search Google Maps around a point for each category."""

import argparse
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request


class Scan:
    """One run of the scan command: search Google Maps for each category in
    every grid cell around the center point.

    Steps (see run()):
      1. resolve_center - turn --near/--coords into a (lat, lng) point
      2. build_grid     - cover the search circle with square cells
      3. search_cell    - search one category in one cell (not built yet)
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
            center = self.resolve_center()
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        cells = self.build_grid(center)
        jobs = len(cells) * len(self.categories)
        print(f"center {center[0]:.5f},{center[1]:.5f}, radius {self.radius_km:g} km")
        print(f"{len(cells)} cells x {len(self.categories)} categories = {jobs} searches")

        for cell in cells:
            for category in self.categories:
                self.search_cell(cell, category)
        return 0

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

    def build_grid(self, center: tuple[float, float]) -> list[tuple[float, float]]:
        """Return the center point of every cell that overlaps the search circle."""
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

    def search_cell(self, cell: tuple[float, float], category: str) -> None:
        """Search one category in one cell. Scraping isn't built yet."""
        print(f"  [todo] search '{category}' at {cell[0]:.5f},{cell[1]:.5f}")
