"""The check-sites command: load each saved website, flag weak ones and collect emails.

A site is "weak" if it's down, parked, a placeholder, has broken or missing HTTPS,
isn't set up for phones, or shows an old copyright year. Sites that redirect to a
social or booking page are moved to "social".
"""

import argparse
import html
import http.client
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date

from classify import classify
from db import Database

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MAX_BYTES = 2_000_000
OUTDATED_YEARS = 5          # copyright this many years old or more counts as outdated
BLOCKED_CODES = {401, 403, 429, 503}   # usually bot protection, not a broken site

PARKING_HOSTS = ("sedoparking.com", "sedo.com", "parkingcrew.net", "bodis.com", "dan.com",
                 "afternic.com", "hugedomains.com", "godaddy.com", "above.com", "undeveloped.com")
PARKED_PHRASES = ("domain is for sale", "buy this domain", "this domain may be for sale",
                  "domain for sale", "is parked free", "parked domain", "domain has expired",
                  "this domain has been registered", "renew this domain")
PLACEHOLDER_PHRASES = ("coming soon", "under construction", "welcome to nginx",
                       "apache2 ubuntu default page", "it works!", "index of /",
                       "account suspended", "website expired", "site not found")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zA-Z]{2,}")
# Placeholder addresses from website templates, and addresses of the site builders themselves.
JUNK_EMAIL_DOMAINS = ("example.com", "domain.com", "yourdomain.com", "website.com", "yoursite.com",
                      "mysite.com", "company.com", "email.com", "sentry.io", "wixpress.com",
                      "godaddy.com", "squarespace.com")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


@dataclass
class Page:
    url: str    # final URL after redirects
    html: str


@dataclass
class SiteReport:
    level: str          # has_site | weak | social
    reason: str
    email: str | None


def check_site(website: str, timeout: float) -> SiteReport:
    """Load a website and decide whether it's fine, weak, or really a social page."""
    parsed = urllib.parse.urlparse(website if "://" in website else f"http://{website}")
    https_url = parsed._replace(scheme="https").geturl()
    http_url = parsed._replace(scheme="http").geturl()
    issues = []

    # Try HTTPS first; fall back to plain HTTP if HTTPS is broken or missing.
    page, error = _try_fetch(https_url, timeout)
    if error and error[0] == "ssl":
        issues.append("broken HTTPS certificate")
        page, error = _try_fetch(https_url, timeout, verify=False)
    if page is None and error[0] in ("down", "ssl"):
        page, http_error = _try_fetch(http_url, timeout)
        if page is None and http_error[0] == "down":   # one retry for network hiccups
            page, http_error = _try_fetch(http_url, timeout)
        if page and page.url.startswith("http:") and not issues:
            issues.append("no HTTPS")
        error = error if page else http_error

    if page is None:
        kind, detail = error
        if kind == "dns":
            return SiteReport("weak", "domain doesn't exist", None)
        if kind == "http" and detail in BLOCKED_CODES:
            return SiteReport("has_site", f"couldn't check: site blocked the check (HTTP {detail})", None)
        if kind == "http":
            return SiteReport("weak", f"site returns error {detail}", None)
        return SiteReport("weak", f"site doesn't load ({detail})", None)

    # Redirects to a social or booking page mean there's no real site.
    level, reason = classify(page.url)
    if level == "social":
        return SiteReport("social", f"website redirects to {reason.removesuffix(' only')}", None)

    host = (urllib.parse.urlparse(page.url).hostname or "").lower()
    text = visible_text(page.html)
    lower = text.lower()
    title = _title(page.html).lower()
    words = len(text.split())

    if host.endswith(PARKING_HOSTS) or (words < 300 and any(p in lower for p in PARKED_PHRASES)):
        return SiteReport("weak", "domain parked or for sale", None)
    placeholder = next((p for p in PLACEHOLDER_PHRASES
                        if p in title or (words < 150 and p in lower)), None)
    if placeholder:
        issues.append(f"placeholder page ('{placeholder}')")
    if not re.search(r"<meta[^>]+name=[\"']?viewport", page.html, re.IGNORECASE):
        issues.append("not mobile-friendly")
    year = copyright_year(text)
    if year and year <= date.today().year - OUTDATED_YEARS:
        issues.append(f"copyright {year}")

    email = find_email(page, timeout)
    if issues:
        return SiteReport("weak", "; ".join(issues), email)
    return SiteReport("has_site", "website OK", email)


def fetch(url: str, timeout: float, verify: bool = True) -> Page:
    context = ssl.create_default_context() if verify else ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
        return Page(url=response.geturl(), html=body.decode(charset, errors="replace"))


def _try_fetch(url: str, timeout: float, verify: bool = True):
    """Fetch a page. Returns (page, None) or (None, (kind, detail)) where kind is
    http (error status), ssl (certificate problem), dns (no such domain) or down."""
    try:
        return fetch(url, timeout, verify), None
    except urllib.error.HTTPError as exc:
        return None, ("http", exc.code)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLError):
            return None, ("ssl", str(exc.reason))
        if isinstance(exc.reason, socket.gaierror):
            return None, ("dns", str(exc.reason))
        return None, ("down", str(exc.reason))
    except ssl.SSLError as exc:
        return None, ("ssl", str(exc))
    except (TimeoutError, socket.timeout):
        return None, ("down", "timed out")
    except (OSError, http.client.HTTPException, ValueError, LookupError) as exc:
        return None, ("down", str(exc) or type(exc).__name__)


def visible_text(page_html: str) -> str:
    """Rough visible text of a page: drop scripts/styles and tags, collapse spaces."""
    page_html = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", page_html)
    text = re.sub(r"(?s)<[^>]+>", " ", page_html)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _title(page_html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", page_html)
    return html.unescape(match.group(1)).strip() if match else ""


def copyright_year(text: str) -> int | None:
    """Latest year in a copyright notice, e.g. '© 2016-2019 Joe's' -> 2019."""
    years = []
    for match in re.finditer(r"(?:©|\(c\)|copyright)\D{0,20}?((?:19|20)\d{2})"
                             r"(?:\s*[-–—]\s*((?:19|20)\d{2}))?", text, re.IGNORECASE):
        years += [int(y) for y in match.groups() if y]
    years = [y for y in years if y <= date.today().year]
    return max(years) if years else None


def find_email(page: Page, timeout: float) -> str | None:
    """An email from the homepage, or from its contact page if the homepage has none."""
    host = urllib.parse.urlparse(page.url).hostname or ""
    emails = extract_emails(page.html)
    if not emails:
        contact_url = _contact_link(page)
        if contact_url:
            contact, _ = _try_fetch(contact_url, timeout, verify=False)
            if contact:
                emails = extract_emails(contact.html)
    return _pick_email(emails, host)


def extract_emails(page_html: str) -> list[str]:
    found = [urllib.parse.unquote(m) for m in re.findall(r"mailto:([^\"'?>\s]+)", page_html, re.I)]
    found += [_decode_cfemail(m) for m in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', page_html)]
    found += EMAIL_RE.findall(html.unescape(page_html))

    emails = []
    for email in found:
        email = email.strip().strip(".").lower()
        domain = email.rpartition("@")[2]
        if (EMAIL_RE.fullmatch(email) and email not in emails
                and not email.endswith(IMAGE_SUFFIXES)
                and not domain.endswith(JUNK_EMAIL_DOMAINS)):
            emails.append(email)
    return emails


def _decode_cfemail(hex_string: str) -> str:
    """Decode an email hidden by Cloudflare's email obfuscation."""
    key = int(hex_string[:2], 16)
    return "".join(chr(int(hex_string[i:i + 2], 16) ^ key) for i in range(2, len(hex_string), 2))


def _contact_link(page: Page) -> str | None:
    """URL of the first same-site link that looks like a contact page."""
    site = urllib.parse.urlparse(page.url).hostname
    for href, label in re.findall(r"(?is)<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", page.html):
        if "contact" in href.lower() or "contact" in label.lower():
            url = urllib.parse.urljoin(page.url, href)
            if urllib.parse.urlparse(url).hostname == site:
                return url
    return None


def _pick_email(emails: list[str], host: str) -> str | None:
    """Prefer an email on the site's own domain, e.g. info@joesbarbers.com."""
    site = host.removeprefix("www.")
    own = [e for e in emails if e.endswith("@" + site) or e.endswith("." + site)]
    return (own or emails or [None])[0]


class SiteCheck:
    """One run of the check-sites command: check every saved website that hasn't
    been checked yet (or all of them with --recheck) and update its level."""

    WORKERS = 8   # websites checked at the same time

    def __init__(self, timeout: float = 10.0, recheck: bool = False, db_path: str = "finder.db"):
        self.timeout = timeout
        self.recheck = recheck
        self.db_path = db_path

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "SiteCheck":
        return cls(timeout=args.timeout, recheck=args.recheck, db_path=args.db)

    def run(self) -> int:
        with Database(self.db_path) as db:
            rows = db.places_to_check(self.recheck)
            if not rows:
                print("no websites to check (run scan first, or use --recheck)")
                return 0
            print(f"checking {len(rows)} websites...")

            counts = Counter()
            with ThreadPoolExecutor(self.WORKERS) as pool:
                futures = {pool.submit(check_site, row["website"], self.timeout): row for row in rows}
                try:
                    for done, future in enumerate(as_completed(futures), 1):
                        row = futures[future]
                        try:
                            report = future.result()
                        except Exception as exc:  # a bug in a check; leave the place unchecked
                            print(f"[{done}/{len(rows)}] ! {row['name']}: {exc!r}", file=sys.stderr)
                            continue
                        db.save_site_check(row["place_id"], report.level, report.reason, report.email)
                        counts[report.level] += 1
                        email = f" | {report.email}" if report.email else ""
                        print(f"[{done}/{len(rows)}] [{report.level}] {row['name']} | "
                              f"{row['website']} | {report.reason}{email}")
                except KeyboardInterrupt:
                    pool.shutdown(wait=False, cancel_futures=True)
                    print("\nstopped by user")

        print(f"\ndone: {counts['weak']} weak, {counts['social']} social, "
              f"{counts['has_site']} fine, saved to {self.db_path}")
        return 0
