"""NCDOT AADT lookup via the public ArcGIS feature services.

The AADT web map (ncdot.maps.arcgis.com, webmap ff72d8f9...) is backed by
public feature services on services.arcgis.com; this module queries them
directly so yearly station AADTs can flow into the Evaluation Set-up sheet
without hand transcription.

Known services (override with ``service_url=`` if NCDOT moves them):

* Stations:  NCDOT_AADT_Stations/FeatureServer/0
* Segments:  NCDOT_AADT_Traffic_Segmentation/FeatureServer/2

Schema drift tolerance: yearly values are auto-detected either as wide columns
(``AADT_2019``/``AADT2019``/``YR_2019``...) or long format (a year field plus
an AADT field). Use :func:`station_years` on any attribute dict.

All results are estimates for the analyst to review; side-road estimates are
rounded to the nearest hundred elsewhere (docs/04) and 2020 is never a
representative year.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

STATIONS_URL = ("https://services.arcgis.com/NuWFvHYDMVmmxMeM/ArcGIS/rest/"
                "services/NCDOT_AADT_Stations/FeatureServer/0")
SEGMENTS_URL = ("https://services.arcgis.com/NuWFvHYDMVmmxMeM/arcgis/rest/"
                "services/NCDOT_AADT_Traffic_Segmentation/FeatureServer/2")

_YEAR_FIELD_RE = re.compile(r"^(?:AADT[_ ]?|YR[_ ]?|Y)?(19|20)(\d{2})$", re.I)


class AadtServiceError(RuntimeError):
    """Raised when the ArcGIS service cannot be reached or returns an error."""


@dataclass
class AadtStation:
    station_id: str
    route: str = ""
    county: str = ""
    location: str = ""
    x: float | None = None
    y: float | None = None
    years: dict = field(default_factory=dict)     # {year: aadt}
    attributes: dict = field(default_factory=dict)


def station_years(attributes: dict) -> dict[int, int]:
    """Extract {year: aadt} from a feature's attributes (wide format)."""
    out: dict[int, int] = {}
    for name, value in attributes.items():
        if value in (None, "", 0):
            continue
        m = _YEAR_FIELD_RE.match(str(name).strip())
        if not m:
            continue
        try:
            year = int(m.group(1) + m.group(2))
            out[year] = int(round(float(value)))
        except (TypeError, ValueError):
            continue
    return out


def _first(attributes: dict, *candidates: str) -> str:
    lowered = {k.lower(): v for k, v in attributes.items()}
    for cand in candidates:
        v = lowered.get(cand.lower())
        if v not in (None, ""):
            return str(v)
    return ""


def parse_features(payload: dict) -> list[AadtStation]:
    """Convert an ArcGIS ``query`` response into :class:`AadtStation` records.

    Handles wide-format yearly columns; long-format responses (one feature per
    station-year with ``YEAR``/``AADT`` fields) are merged by station id.
    """
    if "error" in payload:
        err = payload["error"]
        raise AadtServiceError(f"ArcGIS error {err.get('code')}: {err.get('message')}")
    stations: dict[str, AadtStation] = {}
    for feat in payload.get("features", []):
        attrs = feat.get("attributes", {}) or {}
        geom = feat.get("geometry", {}) or {}
        sid = _first(attrs, "STATION_ID", "STATION", "LOCATION_ID", "LOC_ID",
                     "SITE_ID", "OBJECTID")
        st = stations.get(sid)
        if st is None:
            st = AadtStation(
                station_id=sid,
                route=_first(attrs, "ROUTE", "ROUTE_NAME", "RTE_NM", "ROAD",
                             "STREET_NAME"),
                county=_first(attrs, "COUNTY", "COUNTY_NAME", "CO_NAME"),
                location=_first(attrs, "LOCATION", "DESCRIPTION", "LOC_DESC"),
                x=geom.get("x"), y=geom.get("y"),
                attributes=attrs,
            )
            stations[sid] = st
        st.years.update(station_years(attrs))
        # long format: explicit year + aadt fields
        year_v = _first(attrs, "YEAR", "AADT_YEAR", "COUNT_YEAR")
        aadt_v = _first(attrs, "AADT", "AADT_VALUE", "VOLUME")
        if year_v.isdigit() and aadt_v.replace(".", "").isdigit():
            st.years[int(year_v)] = int(round(float(aadt_v)))
    return list(stations.values())


def _get(url: str, params: dict, timeout: int) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}",
                                 headers={"User-Agent": "safety-eval/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - normalize network errors
        raise AadtServiceError(
            f"Could not reach the NCDOT AADT service at {url}: {exc}. "
            "Run this on a machine with access to services.arcgis.com, or "
            "supply AADTs via a CSV/YAML file instead.") from exc


def query_stations(
    where: str = "1=1",
    point: tuple[float, float] | None = None,
    radius_meters: float = 800.0,
    service_url: str = STATIONS_URL,
    max_records: int = 200,
    timeout: int = 60,
) -> list[AadtStation]:
    """Query AADT stations by attribute filter and/or point-radius.

    ``where`` uses ArcGIS SQL, e.g. ``UPPER(ROUTE) LIKE '%NC 91%'`` or
    ``COUNTY = 'GREENE'``. ``point`` is (lon, lat) WGS84.
    """
    params = {
        "f": "json", "where": where, "outFields": "*",
        "returnGeometry": "true", "outSR": 4326,
        "resultRecordCount": max_records,
    }
    if point is not None:
        params.update({
            "geometry": json.dumps(
                {"x": point[0], "y": point[1],
                 "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
            "spatialRel": "esriSpatialRelIntersects",
            "distance": radius_meters, "units": "esriSRUnit_Meter",
            "inSR": 4326,
        })
    payload = _get(f"{service_url}/query", params, timeout)
    return parse_features(payload)


def stations_to_csv(stations: list[AadtStation]) -> str:
    """Serialize stations to the CSV shape the setup writer accepts."""
    years = sorted({y for s in stations for y in s.years})
    lines = ["station_id,route,county,location," + ",".join(map(str, years))]
    for s in stations:
        row = [s.station_id, s.route, s.county, s.location.replace(",", ";")]
        row += [str(s.years.get(y, "")) for y in years]
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"
