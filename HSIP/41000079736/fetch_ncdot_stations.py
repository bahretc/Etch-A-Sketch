#!/usr/bin/env python3
"""Pull the NCDOT AADT station records around the study (the data behind the NCDOT AADT Mapping Application popups):
AADT_2002..AADT_2025 from the 2025 station layer, ROUTE/LOCATION text from the station layer. Cached to
data/ncdot_aadt_stations.json."""
import json, urllib.request, urllib.parse
from pathlib import Path
HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "ncdot_aadt_stations.json"
BASE = "https://services.arcgis.com/NuWFvHYDMVmmxMeM/arcgis/rest/services/"
ENV = "-81.5300,35.2250,-81.4900,35.2650"      # lon/lat envelope around the study

def query(service, layer):
    q = urllib.parse.urlencode({"where": "1=1", "geometry": ENV, "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                                "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "outSR": "4326", "f": "json"})
    req = urllib.request.Request(f"{BASE}{service}/FeatureServer/{layer}/query?{q}", headers={"User-Agent": "hsip-map-script/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["features"]

s25 = query("NCDOT_2025_AADTandTrafficSegments_gdb", 1)     # AADT_2002..AADT_2025, RTE_CLS_TX, County, Located_On/Approach/Crossroad
s22 = query("NCDOT_AADT_Stations", 0)                       # ROUTE, LOCATION text as the Mapping Application shows them
txt = {f["attributes"]["LocationID"]: f["attributes"] for f in s22}
stations = []
for f in s25:
    a = f["attributes"]; lid = a["LocationID"]; t = txt.get(lid, {})
    years = {k[-4:]: a[k] for k in a if k.startswith("AADT_")}
    stations.append({"LocationID": lid, "COUNTY": (a.get("County") or t.get("COUNTY") or "").upper(), "RTE_CLS": a.get("RTE_CLS"),
                     "RTE_CLS_TX": a.get("RTE_CLS_TX") or {1: "Interstates", 2: "US Routes", 3: "NC Hwys", 4: "Secondary Routes"}.get(t.get("RTE_CLS"), "Non-System Routes"),
                     "ROUTE": t.get("ROUTE") or a.get("Located_On") or a.get("RouteID"), "LOCATION": t.get("LOCATION") or f"{a.get('Approach', '')} {a.get('Crossroad', '')}".strip(),
                     "lat": f["geometry"]["y"], "lon": f["geometry"]["x"], "AADT": years})
stations.sort(key=lambda s: s["LocationID"])
OUT.write_text(json.dumps({"source": "NCDOT Traffic Survey Group ArcGIS services NCDOT_2025_AADTandTrafficSegments_gdb (layer 1) and NCDOT_AADT_Stations (layer 0), queried " + ENV,
                           "stations": stations}, indent=1))
for s in stations:
    print(s["LocationID"], s["RTE_CLS_TX"], s["ROUTE"], "|", s["LOCATION"], "|", {y: v for y, v in s["AADT"].items() if v not in (None, "", " ")})
