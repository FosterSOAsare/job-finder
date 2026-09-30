"""The export command: write leads from the database to a CSV file."""

import argparse
import csv
import os
import sys
from collections import Counter

from db import Database

# (CSV header, database column), in the order they appear in the file.
COLUMNS = [
    ("level", "level"),
    ("name", "name"),
    ("phone", "phone"),
    ("email", "email"),
    ("address", "address"),
    ("category", "category"),
    ("rating", "rating"),
    ("reason", "level_reason"),
    ("website", "website"),
    ("google_maps", "url"),
    ("found_by", "search_category"),
    ("lat", "lat"),
    ("lng", "lng"),
    ("first_seen", "first_seen"),
]


class Export:
    """One run of the export command: select leads and write them to CSV."""

    def __init__(self, levels: list[str], min_rating: float = 0.0,
                 categories: list[str] | None = None, output: str = "leads.csv",
                 db_path: str = "finder.db"):
        self.levels = levels
        self.min_rating = min_rating
        self.categories = categories
        self.output = output
        self.db_path = db_path

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Export":
        return cls(levels=args.levels, min_rating=args.min_rating, categories=args.category,
                   output=args.output, db_path=args.db)

    def run(self) -> int:
        if not os.path.exists(self.db_path):
            print(f"error: {self.db_path} doesn't exist; run scan first", file=sys.stderr)
            return 1
        with Database(self.db_path) as db:
            rows = db.leads(self.levels, self.min_rating, self.categories)

        if not rows:
            print("no leads match (run scan first, or loosen --levels / --min-rating / --category)")
            return 0

        try:
            # utf-8-sig so Excel shows names like "Turner’s" correctly.
            with open(self.output, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(header for header, _ in COLUMNS)
                for row in rows:
                    writer.writerow(row[column] for _, column in COLUMNS)
        except PermissionError:
            print(f"error: can't write {self.output}; is it open in Excel?", file=sys.stderr)
            return 1

        counts = Counter(row["level"] for row in rows)
        breakdown = ", ".join(f"{counts[level]} {level}" for level in self.levels if counts[level])
        emails = sum(1 for row in rows if row["email"])
        print(f"wrote {len(rows)} leads to {self.output} ({breakdown}; {emails} with email)")
        return 0
