"""The map command: write an HTML map of leads, with pins colored by level."""

import argparse
import html
import json
import os
import sys
from collections import Counter

from db import Database

LEVEL_COLORS = {
    "none": "#d64545",      # red: no website at all
    "social": "#e8912d",    # orange: social or booking page only
    "weak": "#7b61ff",      # purple: broken or outdated website
    "has_site": "#8a8f98",  # grey: working website
}
LEVEL_LABELS = {
    "none": "No website",
    "social": "Social / booking only",
    "weak": "Weak website",
    "has_site": "Has website",
}

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body { margin: 0; height: 100%; font: 14px/1.4 system-ui, sans-serif; }
  #map { height: 100%; }
  .legend { background: #fff; padding: 8px 10px; border-radius: 6px;
            box-shadow: 0 1px 4px rgba(0,0,0,.3); }
  .legend h4 { margin: 0 0 6px; font-size: 14px; }
  .legend label { display: flex; align-items: center; gap: 6px; cursor: pointer; margin: 2px 0; }
  .dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
  .popup h3 { margin: 0 0 4px; font-size: 15px; }
  .popup .reason { color: #555; margin: 0 0 6px; }
  .popup div { margin: 2px 0; word-break: break-word; }
</style>
</head>
<body>
<div id="map"></div>
<script>
const places = __PLACES__;
const levels = __LEVELS__;

const map = L.map("map");
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

function popup(p) {
  const rows = [];
  if (p.phone) rows.push(`📞 <a href="tel:${esc(p.phone)}">${esc(p.phone)}</a>`);
  if (p.email) rows.push(`✉️ <a href="mailto:${esc(p.email)}">${esc(p.email)}</a>`);
  if (p.address) rows.push(`📍 ${esc(p.address)}`);
  if (p.category || p.rating) rows.push(`${esc(p.category)}${p.rating ? " · ★ " + p.rating : ""}`);
  if (p.website) rows.push(`🌐 <a href="${esc(p.website)}" target="_blank" rel="noopener">${esc(p.website)}</a>`);
  if (p.url) rows.push(`<a href="${esc(p.url)}" target="_blank" rel="noopener">Open in Google Maps</a>`);
  return `<div class="popup"><h3>${esc(p.name)}</h3><p class="reason">${esc(p.reason)}</p>`
       + rows.map(r => `<div>${r}</div>`).join("") + `</div>`;
}

const groups = {};
for (const [level, info] of Object.entries(levels)) groups[level] = L.layerGroup().addTo(map);
for (const p of places) {
  L.circleMarker([p.lat, p.lng], {
    radius: 7, weight: 1, color: "#fff", fillColor: levels[p.level].color, fillOpacity: 0.9,
  }).bindPopup(popup(p)).bindTooltip(p.name).addTo(groups[p.level]);
}

const legend = L.control({position: "topright"});
legend.onAdd = () => {
  const div = L.DomUtil.create("div", "legend");
  div.innerHTML = "<h4>__HEADING__</h4>" + Object.entries(levels).map(([level, info]) =>
    `<label><input type="checkbox" data-level="${level}" checked>
     <span class="dot" style="background:${info.color}"></span>${esc(info.label)} (${info.count})</label>`
  ).join("");
  div.querySelectorAll("input").forEach(box => box.addEventListener("change", () => {
    const group = groups[box.dataset.level];
    box.checked ? group.addTo(map) : map.removeLayer(group);
  }));
  L.DomEvent.disableClickPropagation(div);
  return div;
};
legend.addTo(map);

map.fitBounds(L.latLngBounds(places.map(p => [p.lat, p.lng])).pad(0.1));
</script>
</body>
</html>
"""


class LeadMap:
    """One run of the map command: write leads with coordinates to an HTML map."""

    def __init__(self, levels: list[str], output: str = "leads.html", db_path: str = "finder.db"):
        self.levels = levels
        self.output = output
        self.db_path = db_path

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "LeadMap":
        return cls(levels=args.levels, output=args.output, db_path=args.db)

    def run(self) -> int:
        if not os.path.exists(self.db_path):
            print(f"error: {self.db_path} doesn't exist; run scan first", file=sys.stderr)
            return 1
        with Database(self.db_path) as db:
            rows = db.leads(self.levels)

        places = [{
            "name": row["name"], "level": row["level"], "reason": row["level_reason"],
            "lat": row["lat"], "lng": row["lng"], "phone": row["phone"], "email": row["email"],
            "address": row["address"], "category": row["category"], "rating": row["rating"],
            "website": row["website"], "url": row["url"],
        } for row in rows if row["lat"] is not None and row["lng"] is not None]
        if not places:
            print("no leads with coordinates to map (run scan first, or change --levels)")
            return 0

        counts = Counter(place["level"] for place in places)
        levels = {level: {"label": LEVEL_LABELS[level], "color": LEVEL_COLORS[level],
                          "count": counts[level]}
                  for level in self.levels if counts[level]}
        page = (PAGE
                .replace("__TITLE__", "Lead map")
                .replace("__HEADING__", html.escape(f"{len(places)} leads"))
                .replace("__LEVELS__", _script_json(levels))
                .replace("__PLACES__", _script_json(places)))

        try:
            with open(self.output, "w", encoding="utf-8") as file:
                file.write(page)
        except PermissionError:
            print(f"error: can't write {self.output}", file=sys.stderr)
            return 1

        skipped = len(rows) - len(places)
        note = f" ({skipped} without coordinates left out)" if skipped else ""
        print(f"wrote {len(places)} leads to {self.output}{note}; open it in a browser")
        return 0


def _script_json(value) -> str:
    """JSON that's safe to put inside a <script> tag (a name can't close the tag)."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")
