"""Decide a place's online-presence level from its Maps website link.

Levels:
  none     - no website link at all
  social   - the link is a social profile, link-in-bio or booking page, not a real site
  has_site - a website of its own (check-sites may later downgrade it to "weak")
"""

import urllib.parse

SOCIAL_DOMAINS = {
    "facebook.com": "Facebook page",
    "fb.com": "Facebook page",
    "fb.me": "Facebook page",
    "instagram.com": "Instagram profile",
    "tiktok.com": "TikTok profile",
    "x.com": "X profile",
    "twitter.com": "X profile",
    "youtube.com": "YouTube channel",
    "linkedin.com": "LinkedIn page",
    "linktr.ee": "Linktree",
    "wa.me": "WhatsApp link",
    "whatsapp.com": "WhatsApp link",
    "yelp.com": "Yelp listing",
    "business.site": "Google Business site",
    "sites.google.com": "Google Sites page",
    "g.page": "Google Business link",
}

BOOKING_DOMAINS = {
    "squareup.com": "Square booking page",
    "square.site": "Square booking page",
    "booksy.com": "Booksy booking page",
    "vagaro.com": "Vagaro booking page",
    "fresha.com": "Fresha booking page",
    "setmore.com": "Setmore booking page",
    "schedulicity.com": "Schedulicity booking page",
    "styleseat.com": "StyleSeat booking page",
    "glossgenius.com": "GlossGenius booking page",
    "calendly.com": "Calendly page",
    "acuityscheduling.com": "Acuity booking page",
    "thecut.co": "theCut booking page",
    "getsquire.com": "Squire booking page",
    "toasttab.com": "Toast ordering page",
    "doordash.com": "DoorDash listing",
    "ubereats.com": "Uber Eats listing",
    "grubhub.com": "Grubhub listing",
}


def classify(website: str | None) -> tuple[str, str]:
    """Return (level, reason) for a place's website link."""
    if not website:
        return "none", "no website on Google Maps"

    host = urllib.parse.urlparse(website if "://" in website else f"http://{website}").hostname or ""
    host = host.lower().removeprefix("www.")

    for domain, label in {**SOCIAL_DOMAINS, **BOOKING_DOMAINS}.items():
        if host == domain or host.endswith("." + domain):
            return "social", f"{label} only"

    return "has_site", f"website: {host}"
