/* Crash-map behaviour (safety_eval.crash_map). Everything local: the tile
   layers read window.TILES (data URIs) and never touch the network. Colours
   are Okabe-Ito (colourblind-safe) and every meaning is also in words. */
(function () {
  const D = window.DATA;
  const COLOURS = { IS: "#0072B2", RE: "#E69F00", ADD: "#009E73",
                    DEL: "#6b7280", NIS: "#b8bec7" };
  const BLANK = "data:image/gif;base64," +
    "R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

  const EmbeddedLayer = L.TileLayer.extend({
    getTileUrl: function (c) {
      return window.TILES[this.options.kind + "/" + c.z + "/" + c.x + "/" + c.y]
        || BLANK;
    }
  });
  const bases = {};
  if (D.basemaps.includes("a"))
    bases["Aerial"] = new EmbeddedLayer("", { kind: "a", minZoom: D.zmin,
      maxZoom: D.zmax, attribution: "Imagery: Esri World Imagery" });
  if (D.basemaps.includes("s"))
    bases["Streets"] = new EmbeddedLayer("", { kind: "s", minZoom: D.zmin,
      maxZoom: D.zmax,
      attribution: "Map data: &copy; OpenStreetMap contributors" });
  const first = Object.values(bases)[0];

  const map = L.map("map", { layers: first ? [first] : [],
                             zoomControl: true,
                             minZoom: D.zmin, maxZoom: D.zmax });
  L.control.scale({ imperial: true, metric: false }).addTo(map);

  function popup(c) {
    const move = (c.new_mp != null && c.coded_mp != null)
      ? `<br>coded MP ${c.coded_mp.toFixed(3)} &rarr; ` +
        `<b>New MP ${c.new_mp.toFixed(3)}</b>` : "";
    return `<b>#${c.id}</b> &mdash; <b>${c.status}</b>` +
      `<br>${c.date}${c.type ? " &middot; " + c.type : ""}` +
      `${c.sev ? " &middot; severity " + c.sev : ""}` +
      `${c.road ? "<br>on " + c.road : ""}` + move +
      (c.src ? `<br><span class="dim">${c.src}</span>` : "");
  }

  const layers = { IS: [], RE: [], ADD: [], DEL: [], NIS: [], moves: [] };
  for (const c of D.crashes) {
    const m = L.circleMarker([c.lat, c.lon], {
      radius: c.status === "NIS" ? 3.5 : (c.status === "DEL" ? 4.5 : 7),
      color: "#ffffff",
      weight: c.status === "NIS" ? 0.5 : 1.4,
      fillColor: COLOURS[c.status] || "#888",
      fillOpacity: c.status === "NIS" ? 0.55 : 0.92,
    }).bindPopup(popup(c));
    (layers[c.status] || layers.NIS).push(m);
    if (c.from_lat != null) {
      layers.moves.push(L.polyline([[c.from_lat, c.from_lon], [c.lat, c.lon]],
        { color: COLOURS[c.status], weight: 2, dashArray: "5 5",
          opacity: 0.85 }));
      layers.moves.push(L.circleMarker([c.from_lat, c.from_lon],
        { radius: 3.5, color: COLOURS[c.status], weight: 1.5,
          fillOpacity: 0 }).bindPopup(
          `#${c.id} coded position (before the ${c.status} move)`));
    }
  }

  const inAnalysis = L.layerGroup([...layers.IS, ...layers.RE, ...layers.ADD]);
  const moves = L.layerGroup(layers.moves);
  const dels = L.layerGroup(layers.DEL);
  const nis = L.layerGroup(layers.NIS);

  const ovl = D.overlays;
  const study = L.layerGroup();
  L.polyline(D.line, { color: "#31445c", weight: 2, opacity: 0.7,
                       dashArray: "1 6" }).addTo(study);
  if (ovl.window)
    L.polyline(ovl.window.line, { color: "#D55E00", weight: 9, opacity: 0.30 })
      .bindPopup(ovl.window.label).addTo(study);
  for (const lim of ovl.limits || []) {
    L.circleMarker([lim.lat, lim.lon], { radius: 5, color: "#111827",
      weight: 2.5, fillColor: "#ffffff", fillOpacity: 1 })
      .bindPopup(lim.label).addTo(study);
    L.marker([lim.lat, lim.lon], { interactive: false, icon: L.divIcon({
      className: "lbl", html: `<span>${lim.mp.toFixed(3)}</span>`,
      iconAnchor: [-8, 18] }) }).addTo(study);
  }
  for (const mk of ovl.markers || []) {
    L.marker([mk.lat, mk.lon], { icon: L.divIcon({ className: "lbl mm",
      html: `<span>${mk.short}</span>`, iconAnchor: [16, -6] }) })
      .bindPopup(`${mk.label} (MP ${mk.mp.toFixed(3)})`).addTo(study);
  }
  for (const cv of ovl.points || []) {
    L.circleMarker([cv.lat, cv.lon], { radius: 3, color: "#31445c",
      weight: 1.5, fillColor: "#fff", fillOpacity: 0.9 })
      .bindPopup(`${cv.label} (MP ${cv.mp.toFixed(3)})`).addTo(study);
  }

  inAnalysis.addTo(map); moves.addTo(map); dels.addTo(map); study.addTo(map);

  const k = D.counts;
  const over = {
    [`In analysis (${(k.IS || 0) + (k.RE || 0) + (k.ADD || 0)})`]: inAnalysis };
  if (layers.moves.length) over["RE / ADD moves"] = moves;
  if (k.DEL) over[`Deleted (${k.DEL})`] = dels;
  if (k.NIS) over[`Not in study (${k.NIS})`] = nis;
  over["Study overlays"] = study;
  L.control.layers(bases, over,
    { collapsed: false, position: "topright" }).addTo(map);

  const b = L.latLngBounds(D.line.map(p => L.latLng(p[0], p[1])));
  map.setMaxBounds(b.pad(0.6));
  map.fitBounds(b.pad(0.12));
})();
