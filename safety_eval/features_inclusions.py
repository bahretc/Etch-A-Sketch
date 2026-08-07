"""Features Inclusions: features added to a route inventory by hand.

The TEAAS Features Report is the inventory NCDOT ships, and it is never quite
enough. A study needs points the report does not carry, and it sometimes needs
one the report DOES carry but under a name or milepost the fiche will not match.
Inclusions are those additions, kept beside the report rather than edited into
it, so the shipped inventory stays the shipped inventory.

The file is the CSV ``FeatureInventory.from_csv`` already reads, so an
inclusions file drops straight into ``location.resolve`` with no new plumbing:

    route,feature,milepost,latitude,longitude,note

``latitude``/``longitude`` are optional and only used when route geometry is
wanted. ``note`` is ignored on load and exists so the next engineer knows why
the row is there.

Curve points are the common case worth naming. A crash cluster on a rural
divided highway is almost always a curve, and PC / PI / PT give the review
something to say beyond a milepost: "in the curve" is a determination an
engineer can defend, "at MP 13.68" is not.
"""
from __future__ import annotations

import csv
import os

#: Header, matching FeatureInventory.from_csv plus a free-text note.
COLUMNS = ("route", "feature", "milepost", "latitude", "longitude", "note")


def curve_points(name: str, pc: float, pi: float, pt: float) -> list:
    """``("Curve 1", 13.06, 13.20, 13.34)`` -> the three named points."""
    return [(f"{name} PC", pc), (f"{name} PI", pi), (f"{name} PT", pt)]


def write_inclusions(path: str, route: str, rows, note: str = "") -> int:
    """Write an inclusions CSV. ``rows`` are ``(feature, milepost)`` or
    ``(feature, milepost, note)``."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for row in rows:
            feature, mp = row[0], float(row[1])
            why = row[2] if len(row) > 2 else note
            w.writerow([route, feature, f"{mp:.3f}", "", "", why])
            n += 1
    return n
