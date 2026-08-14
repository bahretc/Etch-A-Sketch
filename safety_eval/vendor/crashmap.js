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

  // The diagram is a finished exhibit: no zoom buttons, no layer picker.
  const map = L.map("map", { layers: first ? [first] : [],
                             zoomControl: !D.diagram,
                             minZoom: D.zmin, maxZoom: D.zmax });
  L.control.scale({ imperial: true, metric: false }).addTo(map);

  function popup(c) {
    const move = (c.new_mp != null && c.coded_mp != null)
      ? `<br>coded MP ${c.coded_mp.toFixed(3)} &rarr; ` +
        `<b>New MP ${c.new_mp.toFixed(3)}</b>` : "";
    return `<b>#${c.id}</b> &mdash; <b>${c.status}</b>` +
      `<br>${c.date}${c.type ? " &middot; " + c.type : ""}` +
      `${c.sev ? " &middot; severity " + c.sev : ""}` +
      `${c.dir ? " &middot; " + c.dir : ""}` +
      `${c.road ? "<br>on " + c.road : ""}` + move +
      (c.src ? `<br><span class="dim">${c.src}</span>` : "");
  }

  const RING = { Dry: "#111111", Wet: "#31b4e8", Snow: "#9fc5e8",
                 Unknown: "#8a8f98" };
  function badge(c) {
    const fill = c.target === "Target" ? "#ffe14d" : "#c9ccd1";
    const red = (c.sev === "A" || c.sev === "K") ? " red" : "";
    // odx/ody are the ladder's SCREEN offsets: the marker anchors on the
    // road and the icon is shifted in pixels, so a stack keeps the same
    // clean spacing at every zoom. The popup follows the badge.
    const ox = c.odx || 0, oy = c.ody || 0;
    return L.marker([c.lat, c.lon], { icon: L.divIcon({
      className: "badge",
      html: `<div class="oct" style="background:${RING[c.cond] || RING.Unknown}">` +
            `<div class="oct in" style="background:${fill}">` +
            `<span class="${red}">${c.sev}</span></div></div>`,
      iconSize: [26, 26], iconAnchor: [13 - ox, 13 - oy],
      popupAnchor: [ox, oy - 16] }) }).bindPopup(popup(c));
  }

  const layers = { IS: [], RE: [], ADD: [], DEL: [], NIS: [], moves: [] };
  for (const c of D.crashes) {
    if (D.diagram) {
      (layers[c.status] || layers.NIS).push(badge(c));
      continue;
    }
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
  // A real (LRS/calibrated) centreline draws solid; the crash-cloud
  // approximation stays dotted as its own honesty cue.
  L.polyline(D.line, D.shape_src === "lrs"
    ? { color: "#f8fafc", weight: 2.5, opacity: 0.85 }
    : { color: "#31445c", weight: 2, opacity: 0.7, dashArray: "1 6" })
    .addTo(study);
  for (const ld of ovl.ladders || []) {
    // Screen-space guide line: a rotated div from the road anchor out to
    // the last badge, fixed length like the stack itself.
    L.marker([ld.lat, ld.lon], { interactive: false, zIndexOffset: -900,
      icon: L.divIcon({ className: "ladder", iconSize: [1, 1],
        iconAnchor: [0, 0],
        html: `<div class="ln" style="width:${ld.len}px;` +
              `transform:rotate(${ld.angle}deg)"></div>` }) }).addTo(study);
  }
  for (const tk of ovl.mp_ticks || []) {
    L.circleMarker([tk.lat, tk.lon], { radius: 3, color: "#1e7d32",
      weight: 2, fillColor: "#ffffff", fillOpacity: 1,
      interactive: false }).addTo(study);
    L.marker([tk.lat, tk.lon], { interactive: false, icon: L.divIcon({
      className: "lbl mp", html: `<span>${tk.mp.toFixed(1)}</span>`,
      iconSize: [34, 16], iconAnchor: [30, -4] }) }).addTo(study);
  }
  if (ovl.window) {
    L.polyline(ovl.window.line, { color: "#D55E00", weight: 9, opacity: 0.30 })
      .bindPopup(ovl.window.label).addTo(study);
    if (D.diagram) {
      const w = ovl.window;
      const wo = w.label_off || [0, 90];
      L.marker(w.mid, { interactive: false, icon: L.divIcon({
        className: "lbl hot",
        html: `<span><b>HOT SPOT &middot; MP ${w.lo.toFixed(3)} to ` +
              `${w.hi.toFixed(3)}</b><br>${w.label}</span>`,
        iconSize: [300, 54],
        iconAnchor: [150 - wo[0], 27 - wo[1]] }) }).addTo(study);
    }
  }
  for (const lim of ovl.limits || []) {
    L.circleMarker([lim.lat, lim.lon], { radius: 5, color: "#111827",
      weight: 2.5, fillColor: "#ffffff", fillOpacity: 1 })
      .bindPopup(lim.label).addTo(study);
    const txt = D.diagram
      ? `${lim.kind === "begin" ? "BEGIN" : "END"} STUDY<br>MP ` +
        `${lim.mp.toFixed(3)}`
      : lim.mp.toFixed(3);
    L.marker([lim.lat, lim.lon], { interactive: false, icon: L.divIcon({
      className: D.diagram ? "lbl limit" : "lbl", html: `<span>${txt}</span>`,
      iconAnchor: D.diagram ? [-14, -18] : [-8, 18] }) }).addTo(study);
  }
  for (const mk of ovl.markers || []) {
    L.marker([mk.lat, mk.lon], { icon: L.divIcon({ className: "lbl mm",
      html: `<span>${mk.short}</span>`,
      iconAnchor: D.diagram ? [22, -16] : [16, -6] }) })
      .bindPopup(`${mk.label} (MP ${mk.mp.toFixed(3)})`).addTo(study);
  }
  for (const cv of ovl.points || []) {
    L.circleMarker([cv.lat, cv.lon], { radius: 3, color: "#31445c",
      weight: 1.5, fillColor: "#fff", fillOpacity: 0.9 })
      .bindPopup(`${cv.label} (MP ${cv.mp.toFixed(3)})`).addTo(study);
  }

  inAnalysis.addTo(map); moves.addTo(map); dels.addTo(map); study.addTo(map);

  if (!D.diagram) {
    const k = D.counts;
    const over = {
      [`In analysis (${(k.IS || 0) + (k.RE || 0) + (k.ADD || 0)})`]:
        inAnalysis };
    if (layers.moves.length) over["RE / ADD moves"] = moves;
    if (k.DEL) over[`Deleted (${k.DEL})`] = dels;
    if (k.NIS) over[`Not in study (${k.NIS})`] = nis;
    over["Study overlays"] = study;
    L.control.layers(bases, over,
      { collapsed: false, position: "topright" }).addTo(map);
  }

  const b = D.fit_bounds
    ? L.latLngBounds(D.fit_bounds)
    : L.latLngBounds(D.line.map(p => L.latLng(p[0], p[1])));
  map.setMaxBounds(b.pad(0.6));
  if (D.fit_bounds) {
    // data.pad carries the screen reach of the ladders and callouts per
    // side; the left pad also reserves the legend column strip.
    const pd = D.pad || [40, 60, 150, 40];
    map.fitBounds(b, { paddingTopLeft: [Math.max(170, pd[0]), pd[1]],
                       paddingBottomRight: [pd[2], pd[3]] });
  } else
    map.fitBounds(b.pad(0.12));
  // Exposed for automation: the PDF export and tests drive the view.
  window._map = map;
})();
