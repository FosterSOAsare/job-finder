"""Find local businesses on Google Maps that have no website or online presence."""

import argparse
import re
import sys

from scan import Scan

LEVELS = ("none", "social", "weak", "has_site")
DEFAULT_DB = "finder.db"


def parse_radius(value: str) -> float:
    """Parse a radius like '5km', '800m', '3mi' or '2' (km) into kilometres."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(km|m|mi)?\s*", value.lower())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid radius '{value}' (try 5km, 800m or 3mi)")
    amount, unit = float(match.group(1)), match.group(2) or "km"
    km = {"km": amount, "m": amount / 1000, "mi": amount * 1.609344}[unit]
    if km <= 0:
        raise argparse.ArgumentTypeError("radius must be greater than 0")
    return km


def parse_list(value: str) -> list[str]:
    """Parse a comma-separated list, dropping empty items."""
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("list cannot be empty")
    return items


def parse_levels(value: str) -> list[str]:
    levels = parse_list(value)
    unknown = [level for level in levels if level not in LEVELS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown level(s): {', '.join(unknown)} (choose from {', '.join(LEVELS)})"
        )
    return levels


def build_parser() -> argparse.ArgumentParser:
    """Define every command (scan, check-sites, export, map) and its options.

    This only describes what the program accepts; it doesn't run anything.
    argparse uses it to parse the command line, convert values, reject bad
    input and generate the -h help text. To add a command, add another
    sub.add_parser(...) block here and handle it in main().
    """
    parser = argparse.ArgumentParser(
        prog="finder",
        description="Find local businesses on Google Maps with no website or online presence.",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database path (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # scan
    scan = sub.add_parser("scan", help="scrape Google Maps around a location")
    where = scan.add_mutually_exclusive_group(required=True)
    where.add_argument("--near", metavar="ADDRESS", help='center of the search, e.g. "Columbus, OH"')
    where.add_argument("--coords", metavar="LAT,LNG", help="center as coordinates, e.g. 39.96,-83.00 (use --coords=-33.8,151.2 "
                            "when the latitude is negative)")
    scan.add_argument("--radius", type=parse_radius, default=parse_radius("5km"),
                      help="search radius: 5km, 800m, 3mi (default: 5km)")
    scan.add_argument("--categories", type=parse_list, required=True,
                      help='comma-separated, e.g. "barber,plumber,nail salon"')
    scan.add_argument("--cell-size", type=parse_radius, default=parse_radius("1.5km"),
                      help="grid cell size (default: 1.5km)")
    scan.add_argument("--max-places", type=int, default=500,
                      help="stop after this many new places per run (default: 500)")
    scan.add_argument("--headless", action="store_true", help="run the browser without a window")
    scan.add_argument("--fresh", action="store_true", help="ignore saved progress and rescan all cells")

    # check-sites: visit each saved business's website and mark it "weak" if it's
    # dead, parked, insecure, not mobile-friendly or outdated. Runs after a scan.
    check = sub.add_parser("check-sites", help="check websites to flag weak ones")
    check.add_argument("--timeout", type=float, default=10.0, help="seconds per request (default: 10)")
    check.add_argument("--recheck", action="store_true", help="recheck sites already checked")

    # export
    export = sub.add_parser("export", help="export leads to CSV")
    export.add_argument("--levels", type=parse_levels, default=["none", "social"],
                        help="comma-separated levels to include (default: none,social)")
    export.add_argument("--min-reviews", type=int, default=0, help="minimum review count (default: 0)")
    export.add_argument("--min-rating", type=float, default=0.0, help="minimum rating (default: 0)")
    export.add_argument("--category", type=parse_list, help="only these categories")
    export.add_argument("-o", "--output", default="leads.csv", help="output file (default: leads.csv)")

    # map
    map_ = sub.add_parser("map", help="write an HTML map of leads")
    map_.add_argument("--levels", type=parse_levels, default=["none", "social", "weak"],
                      help="comma-separated levels to show (default: none,social,weak)")
    map_.add_argument("-o", "--output", default="leads.html", help="output file (default: leads.html)")

    return parser


def validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Checks that argparse can't express on its own."""
    if args.command == "scan":
        if args.coords:
            try:
                lat, lng = (float(part) for part in args.coords.split(","))
            except ValueError:
                parser.error("--coords must look like LAT,LNG, e.g. 39.96,-83.00")
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                parser.error("--coords out of range")
            args.coords = (lat, lng)
        if args.cell_size > args.radius * 2:
            parser.error("--cell-size is larger than the search area")
        if args.max_places <= 0:
            parser.error("--max-places must be greater than 0")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate(args, parser)

    if args.command == "scan":
        return Scan.from_args(args).run()

    # Other commands are not implemented yet; show what was parsed.
    print(f"command: {args.command}")
    for key, value in vars(args).items():
        if key != "command":
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
