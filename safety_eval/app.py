"""Streamlit app for the NCDOT safety-evaluation workflow (docs/07).

Run with:  streamlit run safety_eval/app.py

Pages (tabs):

1. Build Evaluation: populate a real template from TEAAS exports.
2. AADT and Set-up: NCDOT station lookup, leg table with the black/red
   convention, representative years, write into the Evaluation Set-up sheet.
3. Map Block: compose the Map/Satellite Views image in the team format and
   embed it on the results page.
4. Print and Assemble: LibreOffice print of the results page matched to the
   Excel print, bind Complete Evaluation and Web PDFs.
5. QA Checks: deterministic checks on the workbook and PDFs.
6. Redact Crash Reports: PII removed before anything is stored or shown.
7. Review Filtered Fiche: determination counts.
8. Assistant: chat over the package with tool access (drafts only).

Uploads live in a per-session workspace folder so every page and the
assistant see the same files.
"""
from __future__ import annotations

import os
import sys
import tempfile

if __package__ in (None, ""):          # `streamlit run safety_eval/app.py` runs this as a script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _save_upload(uploaded, workdir: str) -> str | None:
    if uploaded is None:
        return None
    path = os.path.join(workdir, uploaded.name)
    with open(path, "wb") as fh:
        fh.write(uploaded.getbuffer())
    return path


def _workspace(st) -> str:
    if "workspace" not in st.session_state:
        st.session_state.workspace = tempfile.mkdtemp(prefix="safety-eval-")
    return st.session_state.workspace


def _download(st, label: str, path: str, name: str | None = None):
    with open(path, "rb") as fh:
        st.download_button(label, fh.read(), file_name=name or os.path.basename(path))


# --------------------------------------------------------------------------- #
def page_build(st, ws: str) -> None:
    st.caption("Populate a real NCDOT Evaluation Workbook template from TEAAS exports. "
               "Every write is integrity-verified; drawings stay byte-identical.")
    templates = sorted(
        os.path.join("templates", f) for f in os.listdir("templates")
        if f.endswith(".xlsx") and "~$" not in f
    ) if os.path.isdir("templates") else []
    template = st.selectbox("Template", templates)
    c1, c2 = st.columns(2)
    with c1:
        before_up = st.file_uploader("Before Crash ID list (5-col .txt)", key="b_before")
        before_mp_up = st.file_uploader("Before milepost import (.txt)", help="Section analyses only", key="b_bmp")
        fiche_up = st.file_uploader("Original fiche (.csv)", key="b_fiche")
        setup_up = st.file_uploader("Set-up YAML", type=["yaml", "yml"], key="b_setup")
    with c2:
        after_up = st.file_uploader("After Crash ID list (5-col .txt)", key="b_after")
        after_mp_up = st.file_uploader("After milepost import (.txt)", help="Section analyses only", key="b_amp")
        results_up = st.file_uploader("Results YAML", type=["yaml", "yml"], key="b_results")
        statuses_up = st.file_uploader("Workbook with reviewed Filtered Fiche (.xlsx)", key="b_statuses",
                                       help="The engineer's IS/RE/ADD/DEL/NIS determinations drive binning when provided.")
    routes = st.text_input("Study routes (comma-separated)", "")
    mp_range = st.text_input("Milepost range lo:hi", "")
    want_filtered = st.checkbox("Generate pre-screened Filtered Fiche", True)
    want_binned = st.checkbox("Populate Binned Crashes", True)
    recalc_pass = st.checkbox("LibreOffice recalc pass", True)

    if st.button("Build workbook", type="primary", disabled=not (template and before_up and after_up)):
        out = os.path.join(ws, "Evaluation.xlsx")
        argv = ["fill-template", "--template", template,
                "--before", _save_upload(before_up, ws), "--after", _save_upload(after_up, ws),
                "--output", out]
        for flag, up in (("--before-mp", before_mp_up), ("--after-mp", after_mp_up), ("--fiche", fiche_up),
                         ("--setup", setup_up), ("--results", results_up), ("--statuses-from", statuses_up)):
            p = _save_upload(up, ws)
            if p:
                argv += [flag, p]
        if routes.strip():
            argv += ["--bin-routes", routes.strip()]
        if mp_range.strip():
            argv += ["--bin-mp-range", mp_range.strip()]
        if want_binned and fiche_up and setup_up:
            argv += ["--binned"]
        if want_filtered and fiche_up:
            argv += ["--filtered"]
        if recalc_pass:
            argv += ["--recalc"]
        from safety_eval.cli import main as cli_main
        try:
            cli_main(argv)
        except SystemExit as exc:
            if exc.code not in (0, None):
                st.error(f"Build failed: {exc}")
                st.stop()
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
            st.stop()
        st.session_state["workbook"] = out
        _download(st, "Download populated workbook", out)
        st.success("Workbook built and integrity-verified.")


# --------------------------------------------------------------------------- #
def page_aadt(st, ws: str) -> None:
    from safety_eval.aadt_table import (LegSeries, colours_by_year, describe, intersection_table,
                             intersection_volume, representative_year, to_legs_by_year)

    st.caption("Leg AADTs from the NCDOT 2025 AADT Stations layer. Black = published by NCDOT, "
               "red = interpolated, carried or assumed. Minor road estimates round to the nearest hundred; "
               "2020 is never a representative year.")
    c1, c2, c3 = st.columns(3)
    lat = c1.number_input("Latitude", value=35.0, format="%.6f", key="aadt_lat")
    lon = c2.number_input("Longitude", value=-80.0, format="%.6f", key="aadt_lon")
    radius = c3.number_input("Search radius (m)", value=2400, step=100, key="aadt_radius")
    if st.button("Find NCDOT stations", key="aadt_find"):
        from safety_eval.aadt_arcgis import AadtServiceError, query_stations
        try:
            stations = query_stations(point=(lon, lat), radius_meters=float(radius))
            st.session_state["stations"] = stations
        except AadtServiceError as exc:
            st.error(str(exc))
    stations = st.session_state.get("stations", [])
    if stations:
        st.dataframe([{"station": s.station_id, "route": s.route, "location": s.location,
                       **{str(y): v for y, v in sorted(s.years.items()) if y >= 2014}} for s in stations],
                     use_container_width=True)
    by_id = {s.station_id: s for s in stations}
    choices = ["(none)"] + list(by_id)
    years_lo, years_hi = st.slider("Table years", 2006, 2030, (2016, 2026), key="aadt_years")
    years = list(range(years_lo, years_hi + 1))
    legs: dict[str, LegSeries] = {}
    cols = st.columns(4)
    for i, name in enumerate(("leg1", "leg2", "leg3", "leg4")):
        with cols[i]:
            st.markdown(f"**{name}** {'(major)' if i < 2 else '(minor)'}")
            sid = st.selectbox("Station", choices, key=f"st_{name}")
            manual = st.text_input("Published values (year:aadt, ...)", key=f"man_{name}",
                                   help="Overrides or supplements the station, e.g. 2025:3200")
            assumed = st.selectbox("Assumed equal to", ["(no)"] + [n for n in ("leg1", "leg2", "leg3", "leg4") if n != name],
                                   key=f"as_{name}")
            pub = {}
            if sid != "(none)":
                pub.update({y: v for y, v in by_id[sid].years.items() if y in years})
            for tok in manual.replace(";", ",").split(","):
                if ":" in tok:
                    y, v = tok.split(":", 1)
                    try:
                        pub[int(y)] = int(float(v.replace(",", "")))
                    except ValueError:
                        st.warning(f"Ignored '{tok.strip()}'")
            legs[name] = LegSeries(name, pub, is_minor=i >= 2,
                                   assumed_from=None if assumed == "(no)" else assumed)
    if any(l.published or l.assumed_from for l in legs.values()):
        try:
            table = intersection_table(legs, years)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.code(describe(table))
        c1, c2 = st.columns(2)
        before_end = c1.number_input("Before period last year", value=years_lo + 4, key="aadt_bend")
        after_end = c2.number_input("After period last year", value=years_hi, key="aadt_aend")
        rb = representative_year(table, list(range(years_lo, int(before_end) + 1)))
        ra = representative_year(table, list(range(int(before_end) + 1, int(after_end) + 1)))
        rb = int(c1.number_input("Before representative year", value=rb or years_lo, key="aadt_rb"))
        ra = int(c2.number_input("After representative year", value=ra or years_hi, key="aadt_ra"))
        for lbl, y in (("Before", rb), ("After", ra)):
            if y in table:
                v = intersection_volume(table, y)
                st.write(f"{lbl} ({y}): major {v['major']:.0f} + minor {v['minor']:.0f} = {v['total']:.0f}, prints {v['rounded']:,}")
        wb_up = st.file_uploader("Workbook to write the table into (.xlsx)", type=["xlsx"], key="aadt_wb")
        if wb_up and st.button("Write AADT table and colours", type="primary", key="aadt_write"):
            from safety_eval.setup_sheet import SetupData, build_setup_edits
            from safety_eval.workbook_cells import CellPatch, apply_cell_patches
            from safety_eval.xlsx_patch import recalc, xlsx_patch
            src = _save_upload(wb_up, ws)
            mid = os.path.join(ws, "aadt_values.xlsx")
            out = os.path.join(ws, "aadt_done.xlsx")
            data = SetupData(rep_before_year=rb, rep_after_year=ra, legs_by_year=to_legs_by_year(table))
            try:
                xlsx_patch(src, mid, edits={"Evaluation Set-up": build_setup_edits(src, data)})
            except ValueError as exc:
                st.error(str(exc))
                st.stop()
            import openpyxl
            wsx = openpyxl.load_workbook(mid, read_only=True)["Evaluation Set-up"]
            row_of_year = {}
            for r in range(1, 60):
                v = wsx.cell(r, 11).value
                if isinstance(v, (int, float)):
                    row_of_year[int(v)] = r
            leg_cols = {"leg1": "L", "leg2": "M", "leg3": "O", "leg4": "P"}
            patches = [CellPatch("Evaluation Set-up", f"{leg_cols[leg]}{row_of_year[y]}", colour=col)
                       for y, legs_c in colours_by_year(table).items() if y in row_of_year
                       for leg, col in legs_c.items()]
            apply_cell_patches(mid, out, patches)
            ok = recalc(out)
            st.session_state["workbook"] = out
            st.success(f"Table written ({len(patches)} colour patches); recalc {'done' if ok else 'skipped (no LibreOffice)'}")
            _download(st, "Download workbook", out, "Evaluation - AADT.xlsx")


# --------------------------------------------------------------------------- #
def page_map(st, ws: str) -> None:
    from safety_eval.map_block import (BlockSpec, LegLabel, block_extent_px, compose_map_block, crop_around,
                            embed_picture, fit_within, leg_label_lines)

    st.caption("Team format: the aerial fills the block, location map inset in the corner no leg "
               "crosses, a white bordered box beside each leg (route, speed, AADT (Year), N vpd (year)), "
               "north arrow, imagery credit. Use the after representative year row of the AADT table.")
    c1, c2 = st.columns(2)
    aerial_up = c1.file_uploader("Aerial (PNG/JPG, junction near the centre)", type=["png", "jpg", "jpeg"], key="map_aerial")
    inset_up = c2.file_uploader("Location map (PNG/JPG)", type=["png", "jpg", "jpeg"], key="map_inset")
    credit = st.text_input("Imagery credit", "Nearmap imagery", key="map_credit")
    with st.expander("No Nearmap export? Fetch Esri World Imagery for a point"):
        e1, e2, e3 = st.columns(3)
        elat = e1.number_input("Latitude", value=35.081578, format="%.6f", key="esri_lat")
        elon = e2.number_input("Longitude", value=-80.500362, format="%.6f", key="esri_lon")
        ewid = e3.number_input("Ground width (m)", value=520, step=20, key="esri_w")
        if st.button("Fetch Esri aerial", key="esri_fetch"):
            from safety_eval.map_block import fetch_esri_world_imagery
            try:
                img = fetch_esri_world_imagery(elat, elon, ground_width_m=float(ewid))
                p = os.path.join(ws, "esri_aerial.png")
                img.save(p)
                st.session_state["esri_aerial"] = p
                st.image(p, caption="Esri World Imagery (credit: Esri, Maxar, Earthstar Geographics)", use_container_width=True)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Fetch failed: {exc}")
    st.markdown("**Legs** (direction in image pixels from the junction, x right, y down)")
    rows = st.data_editor([
        {"route": "SR 1001", "name": "Sikes Mill Road", "speed": 45, "aadt": 3200, "year": 2025, "dx": 437, "dy": -481, "side": 1, "distance": 420},
        {"route": "SR 1001", "name": "Sikes Mill Road", "speed": 45, "aadt": 3500, "year": 2025, "dx": -713, "dy": 481, "side": 1, "distance": 470},
        {"route": "SR 1617", "name": "Tom Boyd Road", "speed": 45, "aadt": 1900, "year": 2025, "dx": -513, "dy": -481, "side": 1, "distance": 420},
        {"route": "SR 1619", "name": "Tom Boyd Road", "speed": 45, "aadt": 1900, "year": 2025, "dx": 813, "dy": 509, "side": -1, "distance": 430},
    ], num_rows="dynamic", key="map_legs")
    aerial_path = _save_upload(aerial_up, ws) if aerial_up else st.session_state.get("esri_aerial")
    if aerial_path:
        from PIL import Image
        aerial = Image.open(aerial_path).convert("RGB")
        if not aerial_up and not credit.lower().startswith("esri"):
            credit = "Esri World Imagery"
        cx = st.number_input("Junction x (px)", value=aerial.width // 2, key="map_cx")
        cy = st.number_input("Junction y (px)", value=aerial.height // 2, key="map_cy")
        crop_w = st.number_input("Crop width (px)", value=min(aerial.width, 2600), key="map_cw")
        crop_h = int(crop_w * 962 / 1626)
        crop = crop_around(aerial, (int(cx), int(cy)), (int(crop_w), crop_h))
        jx = int(cx) - max(0, min(aerial.width - int(crop_w), int(cx) - int(crop_w) // 2))
        jy = int(cy) - max(0, min(aerial.height - crop_h, int(cy) - crop_h // 2))
        inset = Image.open(_save_upload(inset_up, ws)).convert("RGB") if inset_up else None
        legs = []
        for r in rows:
            try:
                legs.append(LegLabel(leg_label_lines(str(r["route"]), r.get("name") or None,
                                                     int(r["speed"]) if r.get("speed") else None,
                                                     int(r["aadt"]), int(r["year"])),
                                     (float(r["dx"]), float(r["dy"])), float(r.get("distance") or 420),
                                     int(r.get("side") or 1)))
            except (KeyError, TypeError, ValueError):
                continue
        img, layout = compose_map_block(crop, (jx, jy), legs, inset, BlockSpec(credit=credit or None))
        st.image(img, caption=f"inset {layout.inset_corner}; clashes: {layout.clashes or 'none'}", use_container_width=True)
        png = os.path.join(ws, "map_block.png")
        img.save(png)
        st.session_state["map_block"] = png
        wb_up = st.file_uploader("Workbook to embed into (.xlsx)", type=["xlsx"], key="map_wb")
        anchor = st.text_input("Anchor cell / block range", "H41:K56", key="map_anchor")
        if wb_up and st.button("Embed on results page", type="primary", key="map_embed"):
            src = _save_upload(wb_up, ws)
            out = os.path.join(ws, "map_done.xlsx")
            a, b = (anchor.split(":") + [None])[:2]
            size = fit_within(img.size, block_extent_px(src, "1 page results - 1 Target", a, b or a))
            touched = embed_picture(src, out, "1 page results - 1 Target", png, a, size)
            st.session_state["workbook"] = out
            st.success(f"Embedded {size[0]}x{size[1]} px at {a}: {touched}")
            _download(st, "Download workbook", out, "Evaluation - map.xlsx")


# --------------------------------------------------------------------------- #
def page_print(st, ws: str) -> None:
    from safety_eval.print_results import (assemble_deliverables, fonts_report, ink_extents_inches, print_sheet,
                                render_png, soffice_path)

    fr = fonts_report()
    st.caption("LibreOffice print of the results page. Carlito (Calibri metric match) and Liberation "
               "Serif keep the column widths and fit-to-page scale of the Excel print.")
    st.write({"LibreOffice": bool(soffice_path()), **fr})
    wb_up = st.file_uploader("Workbook (.xlsx)", type=["xlsx"], key="pr_wb")
    sheet = st.selectbox("Results sheet", ["1 page results - 1 Target", "1 page results - 2 Targets"], key="pr_sheet")
    lossless = st.checkbox("Lossless aerial (larger file)", False, key="pr_lossless")
    if wb_up and st.button("Print results page", type="primary", key="pr_print"):
        src = _save_upload(wb_up, ws)
        page1 = os.path.join(ws, "results_page.pdf")
        try:
            rep = print_sheet(src, page1, sheet=sheet, lossless=lossless)
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()
        for w in rep.warnings:
            st.warning(w)
        st.session_state["page1"] = page1
        png = render_png(page1, os.path.join(ws, "results_page"))
        st.image(png, caption=f"page {rep.page_index} of {rep.pages_total} in the export", use_container_width=True)
        st.write({k: round(v, 2) for k, v in ink_extents_inches(png).items()})
        _download(st, "Download results page PDF", page1)
    st.markdown("**Bind deliverables**")
    disc_up = st.file_uploader("2020 data disclaimer page (PDF)", type=["pdf"], key="pr_disc")
    app_ups = st.file_uploader("TEAAS reports in order (PDF)", type=["pdf"], accept_multiple_files=True, key="pr_apps")
    title = st.text_input("PDF title", "Safety Project Evaluation", key="pr_title")
    if st.session_state.get("page1") and st.button("Assemble Complete Evaluation and Web PDFs", key="pr_bind"):
        disc = _save_upload(disc_up, ws)
        apps = [_save_upload(u, ws) for u in (app_ups or [])]
        ce, web = os.path.join(ws, "Complete Evaluation.pdf"), os.path.join(ws, "Web.pdf")
        out = assemble_deliverables(st.session_state["page1"], disc, apps, ce, web, title=title)
        st.success(str(out))
        _download(st, "Download Complete Evaluation", ce)
        _download(st, "Download Web", web)


# --------------------------------------------------------------------------- #
def page_qa(st, ws: str) -> None:
    from safety_eval.qa_checks import diff_cached_values, format_report, run_package_checks

    st.caption("Deterministic checks: workbook structure and the docs/06 drawings gate, results text "
               "style, fiche Type versus T code, AADT colour convention, PDF assembly.")
    wb_up = st.file_uploader("Workbook (.xlsx)", type=["xlsx"], key="qa_wb")
    ref_up = st.file_uploader("Reference workbook (template or original, optional)", type=["xlsx"], key="qa_ref")
    ce_up = st.file_uploader("Complete Evaluation PDF (optional)", type=["pdf"], key="qa_ce")
    web_up = st.file_uploader("Web PDF (optional)", type=["pdf"], key="qa_web")
    pub = st.text_area("Published AADT years per leg (optional)", "", key="qa_pub",
                       help="One leg per line: leg1: 2017, 2019, 2021")
    if wb_up and st.button("Run QA checks", type="primary", key="qa_run"):
        wb = _save_upload(wb_up, ws)
        ref = _save_upload(ref_up, ws)
        published = {}
        for line in pub.splitlines():
            if ":" in line:
                leg, ys = line.split(":", 1)
                published[leg.strip()] = {int(y) for y in ys.replace(",", " ").split() if y.strip().isdigit()}
        years = sorted({y for s in published.values() for y in s}) if published else None
        if years:
            years = list(range(min(years) - 1, max(years) + 2))
        rep = run_package_checks(wb, ref, _save_upload(ce_up, ws), _save_upload(web_up, ws),
                                 published_years=published or None, years=years)
        st.code(format_report(rep))
        if ref:
            diffs = diff_cached_values(wb, ref)
            st.write({k: len(v) for k, v in diffs.items()} or "No cached value differs from the reference.")
            for sheet, d in diffs.items():
                with st.expander(f"{sheet}: {len(d)} changed cells"):
                    st.dataframe([{"cell": c, "reference": str(a), "value": str(b)} for c, a, b in d[:400]])


    st.markdown("---")
    st.markdown("**Multi-agent QA sweep** (six reviewers, three refuters, Claude Opus 5)")
    from safety_eval.chat import Assistant
    from safety_eval.qa_sweep import DIMENSIONS
    pkg_dir = st.session_state.get("package_dir")
    if not pkg_dir:
        st.info("Load a package zip on the Home tab first; the sweep reads the whole folder.")
    elif not Assistant.available():
        st.info("Set ANTHROPIC_API_KEY to run the sweep.")
    else:
        dims = st.multiselect("Dimensions", list(DIMENSIONS), default=list(DIMENSIONS),
                              format_func=lambda k: DIMENSIONS[k][0], key="sweep_dims")
        c1, c2 = st.columns(2)
        refuters = c1.number_input("Refuters per finding", 0, 5, 3, key="sweep_ref")
        effort = c2.selectbox("Effort", ["medium", "high", "xhigh", "max"], index=1, key="sweep_effort")
        if st.button("Run sweep", type="primary", key="sweep_run"):
            from safety_eval.qa_sweep import gather_context, run_sweep, sweep_to_markdown
            log = st.empty()
            lines = []
            def _p(m):
                lines.append(m)
                log.code("\n".join(lines))
            with st.spinner("Reading the package"):
                ctx = gather_context(pkg_dir)
            _p(f"context: {len(ctx)} parts, {sum(len(v) for v in ctx.values())} chars")
            rep = run_sweep(ctx, dimensions=dims, n_refuters=int(refuters), effort=effort, progress=_p)
            md = sweep_to_markdown(rep, title=f"QA sweep, {os.path.basename(pkg_dir)}")
            st.session_state["sweep_md"] = md
            c = len(rep.by_status("CONFIRMED")); r = len(rep.by_status("REFUTED")); p_ = len(rep.by_status("PARTIAL"))
            st.session_state["sweep_summary"] = {"confirmed": c, "partial": p_, "refuted": r,
                                                 "items": [f"{f.id} [{f.severity}] {f.where}: {f.claim}" for f in rep.by_status("CONFIRMED")]}
            st.success(f"{len(rep.findings)} findings: {c} confirmed, {p_} partial, {r} refuted. Tokens: {rep.usage}")
        if st.session_state.get("sweep_md"):
            st.markdown(st.session_state["sweep_md"])
            st.download_button("Download sweep report (.md)", st.session_state["sweep_md"], file_name="QA sweep.md")


# --------------------------------------------------------------------------- #
def page_home(st, ws: str) -> None:
    from safety_eval.package import discover, workbook_summary
    from safety_eval.print_results import fonts_report, soffice_path

    st.caption("Load a package zip (the team's WO folder) and every tab works on it. "
               "Or work file by file on the other tabs.")
    zip_up = st.file_uploader("Package zip", type=["zip"], key="home_zip")
    if zip_up and st.button("Load package", type="primary", key="home_load"):
        import zipfile
        dest = os.path.join(ws, "package")
        if os.path.isdir(dest):
            import shutil
            shutil.rmtree(dest)
        with zipfile.ZipFile(_save_upload(zip_up, ws)) as z:
            z.extractall(dest)
        tops = [d for d in os.listdir(dest) if os.path.isdir(os.path.join(dest, d))]
        st.session_state["package_dir"] = os.path.join(dest, tops[0]) if len(tops) == 1 else dest
    pkg_dir = st.session_state.get("package_dir")
    c1, c2 = st.columns([2, 1])
    with c2:
        st.markdown("**Tool chain**")
        fr = fonts_report()
        import shutil as _sh
        rows = {"LibreOffice": bool(soffice_path()), "Carlito (Calibri metrics)": fr.get("carlito", False),
                "Liberation Serif": fr.get("liberation_serif", False), "tesseract (redaction)": bool(_sh.which("tesseract")),
                "poppler (pdftoppm)": bool(_sh.which("pdftoppm"))}
        for mod in ("pikepdf", "matplotlib", "anthropic"):
            try:
                __import__(mod)
                rows[mod] = True
            except ImportError:
                rows[mod] = False
        rows["ANTHROPIC_API_KEY"] = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        for k, v in rows.items():
            st.write(("✅ " if v else "⚠️ ") + k)
    with c1:
        if pkg_dir:
            pkg = discover(pkg_dir)
            st.markdown(f"**Package:** `{os.path.basename(pkg_dir)}`")
            st.write({"workbook": os.path.basename(pkg.workbook) if pkg.workbook else None,
                      "TEAAS reports": [os.path.basename(p) for p in (pkg.before_pdf, pkg.after_pdf) if p],
                      "deliverables": [os.path.basename(p) for p in (pkg.complete_pdf, pkg.web_pdf) if p],
                      "disclaimer": bool(pkg.disclaimer_pdf), "crash reports to redact": len(pkg.crash_reports),
                      "notes": sorted(os.listdir(pkg.notes_dir)) if pkg.notes_dir and os.path.isdir(pkg.notes_dir) else []})
            if pkg.workbook:
                st.session_state["workbook"] = pkg.workbook
                summ = workbook_summary(pkg.workbook)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total crashes", f"{summ.get('total_before')} → {summ.get('total_after')}")
                m2.metric("Severity index", f"{summ.get('si_before') or 0:.2f} → {summ.get('si_after') or 0:.2f}")
                m3.metric("Target crashes", f"{summ.get('target_before')} → {summ.get('target_after')}")
                m4.metric(str(summ.get("volume_label") or "Volume"), f"{summ.get('volume_before')} → {summ.get('volume_after')}")
                st.write({k: (v.date().isoformat() if hasattr(v, "date") else v) for k, v in summ.items()
                          if k in ("order_id", "project_id", "location", "county", "date")})
        else:
            st.info("No package loaded.")
    files = []
    for dp, _, fn in os.walk(ws):
        for f in fn:
            files.append(os.path.relpath(os.path.join(dp, f), ws))
    with st.expander(f"Workspace files ({len(files)})"):
        st.write(sorted(files))


# --------------------------------------------------------------------------- #
def page_diagram(st, ws: str) -> None:
    from safety_eval.collision_diagram import CrashSymbol, Feature, StripSpec, draw_strip_diagram, parse_units

    st.caption("Strip collision diagram: fan-out callouts with leaders to the true milepost, arrows by travel "
               "direction, open square for a stopped unit, colour by severity, N/W flags for night and wet.")
    c1, c2, c3 = st.columns(3)
    title = c1.text_input("Title", "Collision Diagram - Order 41000079307 (PH 77S00141)", key="cd_title")
    mp0 = c2.number_input("Begin MP", value=1.31, format="%.3f", key="cd_mp0")
    mp1 = c3.number_input("End MP", value=1.80, format="%.3f", key="cd_mp1")
    subtitle = st.text_input("Subtitle", "SR 1320 (Milk Dairy Road), Stone Drive (MP 1.31) to SR 1387 (Springside Road) (MP 1.80)", key="cd_sub")
    feats = st.text_input("Features (mp:label; ...)", "1.31:Stone Dr; 1.45:SR 1321; 1.80:SR 1387 (Springside Rd)", key="cd_feats")
    rows = st.data_editor([
        {"crash_id": "107089722", "mp": 1.450, "units": "W:mv", "type": "FO", "severity": "B", "date": "09/23/22", "night": True, "wet": False},
        {"crash_id": "107304540", "mp": 1.469, "units": "W:mv;W:st", "type": "RE", "severity": "O", "date": "04/14/23", "night": False, "wet": False},
    ], num_rows="dynamic", key="cd_rows")
    csv_up = st.file_uploader("Or upload a CSV (crash_id,mp,units,type,severity,date,night,wet)", type=["csv"], key="cd_csv")
    if st.button("Draw diagram", type="primary", key="cd_draw"):
        if csv_up:
            from safety_eval.collision_diagram import load_csv
            crashes = load_csv(_save_upload(csv_up, ws))
        else:
            crashes = [CrashSymbol(str(r["crash_id"]), float(r["mp"]), parse_units(str(r.get("units") or "")),
                                   str(r.get("type") or ""), str(r.get("severity") or "O")[:1].upper(), str(r.get("date") or ""),
                                   bool(r.get("night")), bool(r.get("wet"))) for r in rows if r.get("crash_id")]
        features = []
        for tok in feats.split(";"):
            if ":" in tok:
                mp, _, label = tok.strip().partition(":")
                features.append(Feature(float(mp), label.strip()))
        out = draw_strip_diagram(crashes, StripSpec(title, subtitle, float(mp0), float(mp1), features),
                                 os.path.join(ws, "collision_diagram"))
        st.image(out["png"], use_container_width=True)
        st.write(out)
        _download(st, "Download diagram PDF", out["pdf"])


# --------------------------------------------------------------------------- #
def page_finish(st, ws: str) -> None:
    from safety_eval.package import FinishOptions, discover, finish_package

    pkg_dir = st.session_state.get("package_dir")
    st.caption("One pass over the loaded package: redact and verify crash reports, embed the map block, print the "
               "results page, bind Complete Evaluation and Web, run the QA checks, write the QA log, zip with clean names.")
    if not pkg_dir:
        st.info("Load a package zip on the Home tab first.")
        return
    pkg = discover(pkg_dir)
    st.write({"workbook": os.path.basename(pkg.workbook or ""), "crash reports": len(pkg.crash_reports),
              "disclaimer": bool(pkg.disclaimer_pdf), "TEAAS": [os.path.basename(p) for p in (pkg.before_pdf, pkg.after_pdf) if p]})
    c1, c2 = st.columns(2)
    use_map = c1.checkbox("Embed the map block from the Map Block tab", bool(st.session_state.get("map_block")), key="fin_map")
    strip = c1.checkbox("Drop 'TIP #' from file and folder names", True, key="fin_strip")
    redact = c2.checkbox("Redact and verify crash reports", True, key="fin_redact")
    lossless = c2.checkbox("Lossless aerial", False, key="fin_lossless")
    disc_up = st.file_uploader("Disclaimer page PDF (if not in the package)", type=["pdf"], key="fin_disc")
    ref_up = st.file_uploader("Original workbook for the drawings gate (optional)", type=["xlsx"], key="fin_ref")
    if st.button("Finish package", type="primary", key="fin_run"):
        log = st.empty()
        lines = []
        def _p(m):
            lines.append(m)
            log.code("\n".join(lines))
        opts = FinishOptions(map_block_png=st.session_state.get("map_block") if use_map else None,
                             disclaimer_pdf=_save_upload(disc_up, ws), redact_reports=redact, strip_tip_prefix=strip,
                             reference_workbook=_save_upload(ref_up, ws), lossless_aerial=lossless,
                             zip_out=os.path.join(ws, "package_out.zip"),
                             sweep_summary=st.session_state.get("sweep_summary"))
        rep = finish_package(pkg_dir, opts, progress=_p)
        st.table([{"step": s.name, "ok": "✅" if s.ok else "❌", "detail": s.detail[:160]} for s in rep.steps])
        if rep.qa_text:
            with st.expander("QA checks"):
                st.code(rep.qa_text)
        if rep.certificate and os.path.exists(rep.certificate):
            _download(st, "Download QA certificate (.docx)", rep.certificate)
        if rep.zip_path and os.path.exists(rep.zip_path):
            from safety_eval.package import clean_name
            _download(st, "Download finished package zip", rep.zip_path,
                      (clean_name(os.path.basename(pkg_dir)) if strip else os.path.basename(pkg_dir)) + ".zip")


# --------------------------------------------------------------------------- #
def page_redact(st, ws: str) -> None:
    st.caption("Crash reports are redacted BEFORE review: names, addresses, DOB, phone, and license "
               "numbers are removed. ZIP codes and crash IDs are kept. Spot-check the result; OCR can miss handwriting.")
    report_up = st.file_uploader("Crash report (PDF/TIFF/PNG/JPG)", type=["pdf", "tif", "tiff", "png", "jpg"], key="rd_up")
    keep_zip = st.checkbox("Keep ZIP codes visible", True, key="rd_zip")
    verify = st.checkbox("Verify the output (OCR the redacted pages and search for the original's personal tokens)",
                         True, key="rd_verify")
    if report_up and st.button("Redact", type="primary", key="rd_run"):
        from safety_eval.redact import redact_file
        src = _save_upload(report_up, ws)
        out = os.path.join(ws, os.path.splitext(report_up.name)[0] + "_REDACTED.pdf")
        with st.spinner("Redacting"):
            rep = redact_file(src, out, keep_zip=keep_zip)
        st.write(f"Redacted {rep.boxes} region(s) across {rep.pages} page(s): {rep.by_reason}")
        for w in rep.warnings:
            st.warning(w)
        if verify:
            from safety_eval.redact_verify import verify_redaction
            with st.spinner("Verifying"):
                v = verify_redaction(src, out)
            (st.success if v.clean else st.error)(v.summary())
            for page, kind, tok in v.leaks + v.patterns:
                st.write(f"page {page}: {kind} {tok}")
            st.session_state.setdefault("redaction_log", []).append(
                f"{report_up.name}: {rep.boxes} regions on {rep.pages} pages; {v.summary()}")
        _download(st, "Download redacted report", out)
        try:
            os.remove(src)          # the unredacted upload does not stay in the workspace
        except OSError:
            pass


def page_review(st, ws: str) -> None:
    st.caption("Counts from a workbook's Filtered Fiche. Determinations are made by the engineer in the sheet itself.")
    wb_up = st.file_uploader("Evaluation workbook (.xlsx)", type=["xlsx"], key="rv_wb")
    if wb_up:
        from collections import Counter

        from safety_eval.binned_sheet import read_filtered_fiche
        path = _save_upload(wb_up, ws)
        try:
            statuses = read_filtered_fiche(path)
        except KeyError as exc:
            st.error(str(exc))
            st.stop()
        counts = Counter((d.get("status") or "(blank)") for d in statuses.values())
        st.write({k: v for k, v in counts.most_common()})
        blank = counts.get("(blank)", 0)
        if blank:
            st.info(f"{blank} crash(es) still need a determination.")


# --------------------------------------------------------------------------- #
def page_assistant(st, ws: str) -> None:
    from safety_eval.chat import Assistant

    st.caption("Ask about the package, run the QA checks, look up NCDOT AADT stations, or draft "
               "Items for Discussion in the docs/05 style. Drafts only: nothing here edits a deliverable.")
    files = sorted(os.listdir(ws)) if os.path.isdir(ws) else []
    with st.expander("Files the assistant can read (this session's workspace)"):
        st.write(files or "Nothing uploaded yet. Files uploaded on other tabs appear here.")
        extra = st.file_uploader("Add files", accept_multiple_files=True, key="as_up")
        for u in extra or []:
            _save_upload(u, ws)
    if not Assistant.available():
        st.info("Set ANTHROPIC_API_KEY (or sign in with `ant auth login`) to enable the assistant. "
                "Every other page works without it.")
        return
    if "assistant" not in st.session_state:
        st.session_state.assistant = Assistant(allowed_dirs=[ws, os.getcwd()])
    pkg_hint = f"Loaded package folder: {st.session_state['package_dir']}\n" if st.session_state.get("package_dir") else ""
    asst: Assistant = st.session_state.assistant
    for t in asst.turns:
        with st.chat_message(t.role):
            st.markdown(t.text)
            for name, inp, out in t.tool_calls:
                with st.expander(f"tool: {name}"):
                    st.json(inp)
                    st.code(out[:4000])
    prompt = st.chat_input("Ask about the evaluation, or say what to draft")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Working"):
                try:
                    turn = asst.send(f"Workspace folder: {ws}\n{pkg_hint}\n{prompt}")
                except Exception as exc:  # noqa: BLE001 - shown to the engineer
                    st.error(f"Assistant error: {exc}")
                    return
            st.markdown(turn.text)
            for name, inp, out in turn.tool_calls:
                with st.expander(f"tool: {name}"):
                    st.json(inp)
                    st.code(out[:4000])


PAGES = [
    ("Home", page_home), ("Build Evaluation", page_build), ("AADT and Set-up", page_aadt), ("Map Block", page_map),
    ("Collision Diagram", page_diagram), ("Print and Assemble", page_print), ("QA Checks", page_qa),
    ("Redact Crash Reports", page_redact), ("Review Filtered Fiche", page_review),
    ("Finish Package", page_finish), ("Assistant", page_assistant),
]


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="NCDOT Safety Evaluations", layout="wide")
    st.title("NCDOT HSIP Safety Evaluations")
    ws = _workspace(st)
    st.sidebar.markdown("**Workspace**")
    st.sidebar.code(ws)
    if st.session_state.get("workbook"):
        st.sidebar.write("Current workbook:", os.path.basename(st.session_state["workbook"]))
    tabs = st.tabs([name for name, _ in PAGES])
    for tab, (name, fn) in zip(tabs, PAGES):
        with tab:
            fn(st, ws)


if __name__ == "__main__":
    main()
