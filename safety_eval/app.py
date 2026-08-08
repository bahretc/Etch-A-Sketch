"""Streamlit shell for the NCDOT safety-study workflow (docs/07).

Run with:  streamlit run safety_eval/app.py

The study type chosen in the sidebar governs the run (docs/12): every type
shares the fiche, redaction and review core; an Evaluation adds the workbook
population tab and an HSIP Package Analysis adds the warrant tab. The tabs a
study cannot use are not shown.

* **Fiche Workbook** - assemble the study workbook from the TEAAS exports and
  run the colour screen (IS / ? / NIS, DEL for animals on HSIP).
* **Evaluation Workbook** - populate a real NCDOT template; every write is
  integrity-verified and drawings stay byte-identical.
* **HSIP Warrants** - after the review: section or intersection warrant
  screen, the Warrant sheet, sub-section findings, import list and feature
  inclusions.
* **Redact Crash Reports** - every DMV-349 is redacted BEFORE it is stored or
  shown; ZIP codes and crash IDs are kept.
* **Review Queue** - the interactive fiche review with the redacted report
  beside the coded data. The tool prepares and records; the engineer decides
  every status.

Accessibility: state is never carried by colour alone. Verdicts are words
("Met", "Yes"), warnings carry icons and text, and the theme's primary colour
is Okabe-Ito blue, distinguishable under the common colour-vision
deficiencies.
"""
from __future__ import annotations

import functools
import os
import tempfile

#: Okabe-Ito palette entries used for in-app accents (hex, colourblind-safe).
_BLUE, _ORANGE, _GREEN = "#0072B2", "#E69F00", "#009E73"


def _save_upload(uploaded, workdir: str) -> str | None:
    if uploaded is None:
        return None
    path = os.path.join(workdir, uploaded.name)
    with open(path, "wb") as fh:
        fh.write(uploaded.getbuffer())
    return path


def _style(st) -> None:
    """A light hand: spacing, soft cards, no chrome. The theme itself lives
    in .streamlit/config.toml so Streamlit renders natively."""
    st.markdown("""
        <style>
        #MainMenu, footer {visibility: hidden;}
        [data-testid="stToolbar"], [data-testid="stAppDeployButton"],
        [data-testid="stDecoration"] {display: none;}
        .block-container {padding-top: 1.8rem; padding-bottom: 3rem;
                          max-width: 1150px;}
        h1, h2, h3 {letter-spacing: -0.015em;}
        [data-testid="stMetric"] {
            background: var(--secondary-background-color);
            border: 1px solid rgba(23, 27, 38, 0.08);
            border-radius: 12px; padding: 14px 18px;}
        [data-testid="stMetric"] label {opacity: 0.75;}
        div[data-testid="stExpander"] {
            border: 1px solid rgba(23, 27, 38, 0.08); border-radius: 12px;}
        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(23, 27, 38, 0.06);}
        [data-testid="stFileUploader"] section {border-radius: 10px;}
        div[data-testid="stTable"] {border-radius: 10px; overflow: hidden;}
        </style>""", unsafe_allow_html=True)


def main() -> None:
    import streamlit as st

    from safety_eval.study_type import EVALUATION, STUDY_TYPES, choices

    st.set_page_config(page_title="NCDOT Safety Studies", layout="wide",
                       initial_sidebar_state="expanded")
    _style(st)

    # The study type is chosen once, at set-up, and governs the run. The fiche
    # and crash-review core is the same for all three; only the warrant screen
    # and the animal-crash rule branch (docs/12).
    keys = [k for k, _ in choices()]
    with st.sidebar:
        st.title("NCDOT Safety Studies")
        st.caption("TEAAS-faithful crash analysis, review and deliverables.")
        st.divider()
        study_key = st.selectbox(
            "Study type", keys,
            format_func=lambda k: STUDY_TYPES[k].label)
        kind = STUDY_TYPES[study_key]
        st.caption(kind.description)
        notes = []
        if kind.deletes_animals:
            notes.append("animal crashes become DEL")
        if kind.runs_warrants:
            notes.append("the HSIP warrant screen runs")
        if notes:
            st.info("For this study type, " + " and ".join(notes) + ".")
        st.divider()
        st.caption("The engineer decides every status; the app prepares, "
                   "checks and records.")
    st.session_state["study_type"] = study_key

    # Tabs a study type cannot use are not shown: an Evaluation never sees a
    # warrant screen it must not rely on, and only an Evaluation populates
    # the NCDOT Evaluation Workbook template (docs/12).
    names = ["Fiche Workbook"]
    if study_key == EVALUATION:
        names.append("Evaluation Workbook")
    if kind.runs_warrants:
        names.append("HSIP Warrants")
    names += ["Redact Crash Reports", "Review Queue"]
    tabs = dict(zip(names, st.tabs(names)))
    tab_redact = tabs["Redact Crash Reports"]
    tab_review = tabs["Review Queue"]

    with tabs["Fiche Workbook"]:
        _fiche_tab(st, kind)

    if "Evaluation Workbook" in tabs:
        with tabs["Evaluation Workbook"]:
            _evaluation_tab(st)

    if kind.runs_warrants:
        with tabs["HSIP Warrants"]:
            _hsip_tab(st)

    with tab_redact:
        _redact_tab(st)

    with tab_review:
        _review_queue_tab(st)


def _evaluation_tab(st) -> None:
    st.caption("Populate a real NCDOT Evaluation Workbook template from "
               "TEAAS exports. Every write is integrity-verified; "
               "drawings stay byte-identical.")
    templates = sorted(
        os.path.join("templates", f) for f in os.listdir("templates")
        if f.endswith(".xlsx") and "~$" not in f
    ) if os.path.isdir("templates") else []
    template = st.selectbox("Template", templates)
    c1, c2 = st.columns(2)
    with c1:
        before_up = st.file_uploader("Before Crash ID list (5-col .txt)")
        before_mp_up = st.file_uploader("Before milepost import (.txt)",
                                        help="Section analyses only")
        fiche_up = st.file_uploader("Original fiche (.csv)")
        setup_up = st.file_uploader("Set-up YAML", type=["yaml", "yml"])
    with c2:
        after_up = st.file_uploader("After Crash ID list (5-col .txt)")
        after_mp_up = st.file_uploader("After milepost import (.txt)",
                                       help="Section analyses only")
        results_up = st.file_uploader("Results YAML", type=["yaml", "yml"])
        statuses_up = st.file_uploader(
            "Workbook with reviewed Filtered Fiche (.xlsx)",
            help="The engineer's IS/RE/ADD/DEL/NIS determinations drive "
                 "binning when provided.")
    routes = st.text_input("Study routes (comma-separated)", "")
    mp_range = st.text_input("Milepost range lo:hi", "")
    want_filtered = st.checkbox("Generate pre-screened Filtered Fiche", True)
    want_binned = st.checkbox("Populate Binned Crashes", True)
    recalc_pass = st.checkbox("LibreOffice recalc pass", True)

    if st.button("Build workbook", type="primary",
                 disabled=not (template and before_up and after_up)):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["fill-template", "--template", template,
                    "--before", _save_upload(before_up, tmp),
                    "--after", _save_upload(after_up, tmp),
                    "--output", os.path.join(tmp, "workbook.xlsx")]
            for flag, up in (("--before-mp", before_mp_up),
                             ("--after-mp", after_mp_up),
                             ("--fiche", fiche_up),
                             ("--setup", setup_up),
                             ("--results", results_up),
                             ("--statuses-from", statuses_up)):
                p = _save_upload(up, tmp)
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
            with open(os.path.join(tmp, "workbook.xlsx"), "rb") as fh:
                st.download_button("Download populated workbook",
                                   fh.read(), file_name="Evaluation.xlsx")
            st.success("Workbook built and integrity-verified.")


def _redact_tab(st) -> None:
    st.caption("Crash reports are redacted BEFORE review: names, "
               "addresses, DOB, phone, and license numbers are removed. "
               "ZIP codes and crash IDs are kept. Spot-check the result; "
               "OCR can miss handwriting.")
    report_up = st.file_uploader("Crash report (PDF/TIFF/PNG/JPG)",
                                 type=["pdf", "tif", "tiff", "png", "jpg"])
    keep_zip = st.checkbox("Keep ZIP codes visible", True)
    if report_up and st.button("Redact", type="primary"):
        from safety_eval.redact import redact_file
        with tempfile.TemporaryDirectory() as tmp:
            src = _save_upload(report_up, tmp)
            out = os.path.join(tmp, "redacted.pdf")
            rep = redact_file(src, out, keep_zip=keep_zip)
            st.write(f"Redacted {rep.boxes} region(s) across "
                     f"{rep.pages} page(s): {rep.by_reason}")
            for w in rep.warnings:
                st.warning(w)
            with open(out, "rb") as fh:
                st.download_button("Download redacted report", fh.read(),
                                   file_name="redacted.pdf")


def _fiche_tab(st, kind) -> None:
    """Assemble the study fiche workbook from the TEAAS exports (docs/02)."""
    st.caption("The Fiche Report becomes the formatted working sheet "
               "(columns split, sorted by Milepost Road, MP, From Road), "
               "with the ID cross-reference, Initial Study and DetailedFiche "
               "sheets beside it. With a Features Report and study limits, "
               "the colour screen marks IS, ?, and NIS"
               + (", and animal crashes are deleted (DEL)"
                  if kind.deletes_animals else "")
               + ", and the grey NOT-REVIEWED banner is placed.")
    study = st.text_input("Study number", placeholder="41000079305")
    c1, c2 = st.columns(2)
    with c1:
        fiche_up = st.file_uploader("Fiche Report (.csv)", type=["csv"])
        initial_up = st.file_uploader(
            "Strip/Intersection Analysis Report (.csv)",
            help="Becomes the Initial Study sheet; the Dir formulas walk it.")
        detailed_up = st.file_uploader(
            "Detailed Fiche (.csv)",
            help="Carries latitude/longitude for the coordinate formulas.")
    with c2:
        ids_up = st.file_uploader(
            "TEAAS ID export (.txt)",
            help="Pipe-delimited; marks the Initial Study crashes IS.")
        features_up = st.file_uploader(
            "Features Report (.pdf/.txt/.csv)",
            help="Enables the colour screen: a From/Toward feature inside "
                 "the limits, or a blue/yellow bracket, sends the crash to "
                 "review (?).")
        r1, r2, r3 = st.columns(3)
        route = r1.text_input("Study route", placeholder="US 74")
        lo = r2.number_input("MP begin", min_value=0.0, format="%.3f",
                             step=0.005, key="fiche_lo")
        hi = r3.number_input("MP end", min_value=0.0, format="%.3f",
                             step=0.005, key="fiche_hi")

    want_screen = features_up is not None and route.strip() and hi > lo
    if features_up is not None and not want_screen:
        st.info("Add the study route and MP limits to run the colour screen "
                "with the build.")
    if st.button("Build fiche workbook", type="primary",
                 disabled=not (study.strip() and fiche_up)):
        from safety_eval.fiche_workbook import build_fiche_workbook, parse_initial_ids

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, f"{study.strip()}_Fiche.xlsx")
            try:
                counts = build_fiche_workbook(
                    out, fiche_csv=_save_upload(fiche_up, tmp),
                    initial_study_csv=_save_upload(initial_up, tmp),
                    initial_id_txt=_save_upload(ids_up, tmp),
                    detailed_fiche_csv=_save_upload(detailed_up, tmp),
                    study=study.strip())
            except (ValueError, KeyError) as exc:
                st.error(f"Build failed: {exc}")
                st.stop()
            tally = None
            if want_screen:
                import openpyxl

                from safety_eval.fiche_screen import parse_features_report, screen_sheet
                ids = []
                if ids_up is not None:
                    _, raw = parse_initial_ids(
                        os.path.join(tmp, ids_up.name))
                    ids = [r[0] for r in raw]
                wb = openpyxl.load_workbook(out)
                ws = wb[f"{study.strip()}_Fiche"]
                tally = screen_sheet(
                    ws, parse_features_report(_save_upload(features_up, tmp)),
                    lo, hi, ids, route=route.strip(),
                    study=kind.key)
                wb.save(out)
            cols = st.columns(4)
            cols[0].metric("Fiche rows",
                           counts.get(f"{study.strip()}_Fiche", 0))
            if tally:
                cols[1].metric("IS", tally.get("IS", 0))
                cols[2].metric("To review (?)", tally.get("?", 0))
                label = ("NIS / DEL" if kind.deletes_animals else "NIS")
                cols[3].metric(label, tally.get("NIS", 0)
                               + tally.get("DEL", 0))
            with open(out, "rb") as fh:
                st.download_button("Download fiche workbook", fh.read(),
                                   file_name=os.path.basename(out))
            st.success("Workbook assembled"
                       + (" and screened; review the ? rows next."
                          if tally else "; supply the Features Report and "
                          "limits to screen it."))


def _hsip_tab(st) -> None:
    """The reviewed fiche workbook, taken the rest of the way (docs/12).

    Everything on this tab runs AFTER the crash review: it reads the
    engineer's IS/RE/ADD determinations off the working sheet and never
    changes one.
    """
    from safety_eval.warrant_sheet import FACILITY_LABELS

    st.caption("Runs after the review, off your IS/RE/ADD determinations. "
               "A section analysis rebuilds the Warrant sheet (live "
               "formulas, facility dropdown, per-warrant sub-section "
               "findings); an intersection analysis screens the urban or "
               "rural intersection warrants. The ADD+RE milepost import is "
               "written alongside. Determinations are read, never changed.")
    analysis = st.radio(
        "Analysis", ["Section (strip)", "Intersection"], horizontal=True,
        help="Sections are milepost-dependent, intersections are "
             "road-combination-dependent; this is the fundamental split in "
             "crash identification (docs/01).")
    is_section = analysis.startswith("Section")

    wb_up = st.file_uploader("Reviewed fiche workbook (.xlsx)", type=["xlsx"])
    ids_up = st.file_uploader(
        "TEAAS ID export (.txt)",
        help="Enables the branch-vocabulary gate (docs/03): the run refuses "
             "while any status contradicts Initial Study membership.")

    if is_section:
        c1, c2, c3, c4 = st.columns(4)
        facility = c1.selectbox("Facility", list(FACILITY_LABELS),
                                format_func=FACILITY_LABELS.get)
        lo = c2.number_input("MP begin", min_value=0.0, format="%.3f",
                             step=0.005)
        hi = c3.number_input("MP end", min_value=0.0, format="%.3f",
                             step=0.005)
        multilane = c4.checkbox(
            "Multi-lane", value=False,
            help="Counts SSSD as run-off-road (docs/12; off by default).")
        ready = hi > lo
    else:
        c1, c2 = st.columns(2)
        context = c1.radio("Context", ["urban", "rural"], horizontal=True,
                           help="Urban and rural differ in every threshold "
                                "and in the recency window (2 vs 3 years).")
        end_date = c2.date_input(
            "Analysis end date", value=None,
            help="The recency tests count back from here; without it, from "
                 "the most recent crash.")
        ready = True

    overrides_text = st.text_area(
        "Engineer overrides, one CRASH_ID:FIELD=VALUE per line",
        placeholder="107591377:l=5",
        help="The analysis uses the corrected value and the Warrant sheet "
             "paints that one cell the reserved yellow. The fiche sheet "
             "keeps the original; add your comment blurb there.")
    features_text = st.text_area(
        "Feature inclusions, one '<text>|<milepost>' per line (optional)",
        placeholder="MILE MARKER 166|13.715",
        help="Written as a TEAAS feature-inclusion import (20-character "
             "cap; format unverified against a live import, docs/09).")

    if st.button("Run warrants", type="primary",
                 disabled=not wb_up or not ready):
        import safety_eval.hsip as hsip
        from safety_eval.qc import check_branch_vocabulary
        from safety_eval.teaas import write_feature_list

        with tempfile.TemporaryDirectory() as tmp:
            path = _save_upload(wb_up, tmp)
            if ids_up:
                from safety_eval.fiche_workbook import parse_initial_ids
                _, raw = parse_initial_ids(_save_upload(ids_up, tmp))
                bad = check_branch_vocabulary(path, "", [r[0] for r in raw])
                if bad:
                    st.error(f"{len(bad)} branch violation(s); fix the "
                             "review before the warrants (docs/03).")
                    st.table([{"row": p["row"], "crash": p["crash_id"],
                               "status": p["status"],
                               "problem": p["problem"]} for p in bad])
                    st.stop()
            try:
                overrides = hsip.parse_overrides(
                    [ln.strip() for ln in overrides_text.splitlines()
                     if ln.strip()])
            except ValueError as exc:
                st.error(str(exc))
                st.stop()

            if is_section:
                try:
                    run = hsip.run_hsip(
                        path, facility, lo, hi, multilane=multilane,
                        overrides=overrides,
                        import_out=os.path.join(tmp, "import.txt"))
                except ValueError as exc:
                    st.error(str(exc))
                    st.stop()
                _section_results(st, run)
                import_lines, import_path = (run.import_lines,
                                             os.path.join(tmp, "import.txt"))
            else:
                try:
                    s, pairs, flags = _screen_intersection_wb(
                        path, context, end_date, overrides)
                except ValueError as exc:
                    st.error(str(exc))
                    st.stop()
                from safety_eval.teaas import write_import_list
                import_path = os.path.join(tmp, "import.txt")
                import_lines = write_import_list(import_path, pairs,
                                                 strip_zeros=True)
                _intersection_results(st, s, flags)

            base = os.path.splitext(os.path.basename(wb_up.name))[0]
            stem = base.replace("_Fiche", "")
            d1, d2, d3 = st.columns(3)
            if is_section:
                with open(path, "rb") as fh:
                    d1.download_button("Workbook with Warrant sheet",
                                       fh.read(),
                                       file_name=f"{stem}_Fiche.xlsx")
            if import_lines:
                with open(import_path, "rb") as fh:
                    d2.download_button(
                        f"Import list ({import_lines} ADD/RE)", fh.read(),
                        file_name=f"{stem}_Import.txt")
            feature_lines = [ln.strip() for ln in features_text.splitlines()
                             if ln.strip()]
            if feature_lines:
                try:
                    rows = []
                    for ln in feature_lines:
                        text, mp = ln.rsplit("|", 1)
                        rows.append((text.strip(), float(mp)))
                    fpath = os.path.join(tmp, "features.txt")
                    write_feature_list(fpath, rows)
                    with open(fpath, "rb") as fh:
                        d3.download_button(
                            f"Feature inclusions ({len(rows)})", fh.read(),
                            file_name=f"{stem}_FeatureInclusions.txt")
                except ValueError as exc:
                    st.error(f"Feature inclusions: {exc}")


def _section_results(st, run) -> None:
    s = run.screen
    m1, m2, m3 = st.columns(3)
    m1.metric("Crashes in analysis", s.total)
    m2.metric("Crashes per mile", f"{s.rate:.1f}")
    m3.metric(f"Minimums ({s.min_total} / {s.min_rate} per mi)",
              "Met" if s.meets_minimums else "Not met")
    st.table([{"Warrant": w.warrant, "Description": w.description,
               "Crashes": f"{w.count}/{w.total}",
               "Share": f"{w.share:.0%}", "Needs": f"{w.threshold:.0%}",
               "Met": "Yes" if w.met else "No"} for w in s.warrants])
    st.subheader("Sub-section findings")
    for line in run.finding_lines:
        st.write(line)
    _daylight_warnings(st, run.daylight_flags)
    st.success("Warrant sheet rebuilt; open the workbook and change the "
               "facility dropdown to see the other warrant set live.")


def _intersection_results(st, s, flags) -> None:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Crashes in analysis", s.total)
    m2.metric("Frontal impact", f"{s.fi} ({s.fi_share:.0%})")
    m3.metric("Night", f"{s.night} ({s.night_share:.0%})")
    m4.metric("K/A frontal, 5 yr", s.ka_fi_5yr)
    st.caption(f"EPDO severity: frontal impact {s.fi_severity:.1f} of "
               f"{s.total_severity:.1f} total. Last year {s.recent_1yr} "
               f"({s.recent_1yr_share:.0%}); last {s.recency_years} years "
               f"{s.recent_n} ({s.recent_n_share:.0%}).")
    st.table([{"Warrant": w.warrant, "Description": w.description,
               "Met": "Yes" if w.met else "No"} for w in s.warrants])
    _daylight_warnings(st, flags)
    st.caption("The SN24-style Warrant sheet is section-specific; "
               "intersection results live here and in the report text.")


def _daylight_warnings(st, flags) -> None:
    for f in flags or ():
        st.warning(
            f"Daylight check: {f['crash_id']} has L={f['l']} at "
            f"{f['time']:%H:%M} but {f['problem']} (sunrise "
            f"{f['sunrise']:%H:%M}, sunset {f['sunset']:%H:%M}). If the "
            "report confirms, record an override above and note it in the "
            "fiche comment.")


def _screen_intersection_wb(path, context, end_date, overrides):
    """Screen the intersection warrants off a reviewed fiche workbook."""
    import openpyxl

    import safety_eval.hsip as hsip
    from safety_eval.qc import daylight_check
    from safety_eval.warrants import Crash, screen_intersection

    wb = openpyxl.load_workbook(path)
    ws = wb[hsip.fiche_sheet_name(wb)]
    rows = hsip.read_analysis_rows(ws)
    if not rows:
        raise ValueError("no IS/RE/ADD rows on the working sheet; review "
                         "the fiche first")
    wrows = hsip.warrant_rows(rows, overrides)
    crashes = []
    for d in wrows:
        when = d.get("date")
        crashes.append(Crash(
            crash_id=str(d.get("crash_id", "")),
            crash_type=str(d.get("type") or ""),
            road_condition=d.get("c") if isinstance(d.get("c"), int) else None,
            light_condition=d.get("l") if isinstance(d.get("l"), int)
            else None,
            severity=str(d.get("s") or ""),
            date=when.date() if hasattr(when, "date") else when))
    screen = screen_intersection(crashes, context, end_date or None)
    times = hsip.crash_times(wb)
    flags = daylight_check(
        [(a.crash_id, times.get(a.crash_id, a.date), a.l)
         for a in rows if a.l is not None])
    return screen, hsip.import_pairs(rows), flags


@functools.lru_cache(maxsize=16)
def _queue_pages(index_path: str, crash_id: str, keep_zip: bool = True):
    """Redacted page images for one crash (cached; OCR redaction is slow)."""
    from safety_eval.binder import BinderIndex, render_crash_pages
    idx = BinderIndex.load(index_path)
    return render_crash_pages(idx, crash_id, dpi=idx.dpi, keep_zip=keep_zip)


def _review_queue_tab(st) -> None:
    import safety_eval.review_queue as rq

    st.caption("Fiche review queue (docs/07 Phase 3). Reports are shown "
               "REDACTED; every determination is validated (docs/03) and "
               "recorded to the audit trail. The engineer decides every "
               "status; nothing is ever blanket-reclassified.")

    c1, c2 = st.columns(2)
    with c1:
        wb_path = st.text_input(
            "Evaluation workbook (.xlsx path)",
            help="The workbook whose Filtered Fiche is being reviewed. A "
                 "path, not an upload, so the reviewed copy can be saved "
                 "next to it.")
        sheet = st.text_input("Filtered Fiche sheet name", "Filtered Fiche")
        analysis_type = st.selectbox("Analysis type", ["section", "intersection"],
                                     help="Controls the status vocabulary; "
                                          "RE only exists for sections.")
    with c2:
        index_path = st.text_input(
            "Binder index JSON (from `safety-eval binder-index`)",
            help="OCR page index of the scanned DMV-349 binder. Leave blank "
                 "to review without report retrieval.")
        coords_path = st.text_input(
            "DetailedFiche (optional)",
            help="Provided alongside the Original Fiche and Initial Study; "
                 "carries per-crash Latitude/Longitude used to decide which "
                 "reports to review (fiche workbook or delimited file). "
                 "The pre-screen never takes coordinates from the reports "
                 "themselves.")
        study_pt = st.text_input("Study point lat,lon (optional)",
                                 help="Used with coordinates to sort the "
                                      "queue by distance.")
        mp_rng = st.text_input("Study milepost range lo:hi (optional)")
        features_up = st.file_uploader(
            "Features report(s) for this evaluation",
            type=["pdf", "txt", "csv"], accept_multiple_files=True,
            help="The TEAAS Features Report for each study route, provided "
                 "per analysis. Without them no milepost can be resolved from "
                 "the report's distances, and the assist is told not to infer "
                 "one.")

    if not (wb_path and os.path.exists(wb_path)):
        if wb_path:
            st.error(f"Workbook not found: {wb_path}")
        st.stop()

    try:
        review = rq.load_review_sheet(wb_path, sheet)
    except KeyError as exc:
        st.error(str(exc))
        st.stop()

    binder_index = None
    if index_path:
        if not os.path.exists(index_path):
            st.error(f"Binder index not found: {index_path}")
            st.stop()
        from safety_eval.binder import BinderIndex, reconcile_index
        binder_index = BinderIndex.load(index_path)
        suggestions = reconcile_index(
            binder_index, {r.crash_id for r in review.rows})
        if suggestions:
            st.warning(
                "Possible misread binder header IDs (fix with "
                "`safety-eval binder-index --known-ids ...` and reload): "
                + ", ".join(f"{a} -> {b}" for a, b in sorted(suggestions.items())))

    inventory = None
    if features_up:
        from safety_eval.location import FeatureInventory
        with tempfile.TemporaryDirectory() as tmp:
            paths = [_save_upload(f, tmp) for f in features_up]
            try:
                inventory = FeatureInventory.from_files(paths)
            except Exception as exc:          # noqa: BLE001 - show, don't die
                st.error(f"Could not read the features report(s): {exc}")
        if inventory is not None:
            st.caption("Features reports loaded for routes: "
                       + ", ".join(sorted(inventory.features)))
    coords = rq.parse_coordinates(coords_path) if coords_path else None
    # The DetailedFiche doubles as the route shape (location.clean_shape):
    # coordinates then resolve to a milepost instead of punting.
    if inventory is not None and coords_path:
        from safety_eval.location import clean_shape
        for key in list(inventory.features):
            pts = rq.parse_shape_points(coords_path, key)
            if pts:
                inventory.shape[key] = clean_shape(pts)
    st.session_state["rq_features"] = inventory
    point = None
    if study_pt.strip():
        try:
            lat, lon = (float(x) for x in study_pt.split(","))
            point = (lat, lon)
        except ValueError:
            st.error("Study point must be 'lat,lon'.")
            st.stop()
    mp_range = None
    if mp_rng.strip():
        try:
            lo, hi = (float(x) for x in mp_rng.split(":"))
            mp_range = (lo, hi)
        except ValueError:
            st.error("Milepost range must be 'lo:hi'.")
            st.stop()

    queue = rq.build_queue(review, binder_index=binder_index, coords=coords,
                           study_point=point, mp_range=mp_range)
    dets: dict = st.session_state.setdefault("rq_determinations", {})
    audit_path = os.path.splitext(wb_path)[0] + ".review-audit.jsonl"

    prog = rq.queue_progress(queue, set(dets))
    st.write(f"**{prog['pending'] - len(dets)} to review** · "
             f"{prog['determined']} already determined on the sheet · "
             f"{len(dets)} decided this session · "
             f"{prog['animal_skips']} animal skips")

    pending = [i for i in queue if i.pending and i.crash_id not in dets]
    if not pending:
        st.success("Queue empty. Save the reviewed workbook below.")
    else:
        pos = min(st.session_state.get("rq_pos", 0), len(pending) - 1)
        item = pending[pos]
        row = item.row

        report_pages, report_note = [], None
        if binder_index is None:
            report_note = "No binder index loaded; reviewing coded data only."
        elif not item.has_report:
            report_note = ("No DMV-349 for this crash in the indexed binder; "
                           "flag as unverifiable if a determination needs the "
                           "report (docs/03).")
        else:
            try:
                report_pages = _queue_pages(index_path, row.crash_id)
            except Exception as exc:           # noqa: BLE001 - show, don't die
                report_note = f"Page retrieval failed: {exc}"

        left, right = st.columns([2, 3])
        with left:
            st.subheader(f"Crash {row.crash_id}")
            meta = [f"queue {pos + 1} of {len(pending)}",
                    f"sheet row {row.row}", f"group: {row.banner or '?'}"]
            if item.dist_ft is not None:
                meta.append(f"{item.dist_ft:,.0f} ft from study point")
            st.caption(" · ".join(meta))
            if coords and row.crash_id in coords:
                lat, lon = coords[row.crash_id]
                st.code(f"{lat}, {lon}", language=None)  # paste into a map
            if item.skip_reason:
                st.info(f"Skip suggested: {item.skip_reason}")
            show = {k: v for k, v in row.fields.items() if v not in (None, "")}
            st.table({"field": list(show), "value": [str(v) for v in show.values()]})

            # ---- AI assist over the redacted report (docs/03; proposal only) ----
            assist_mode = st.radio(
                "AI assist", ["Off", "Decide", "Prepare"], horizontal=True,
                key=f"rq_assist_mode_{row.crash_id}",
                help="Decide: propose the determination from the redacted "
                     "report. Prepare: assemble the evidence and leave the call "
                     "to you. Runs on the redacted pages only; never auto-applied.")
            resolved = None
            if report_pages:
                from safety_eval.location import read_location_block, resolve
                from safety_eval.redact import ocr_words
                with tempfile.TemporaryDirectory() as tmp:
                    ppath = os.path.join(tmp, "loc.png")
                    report_pages[0].save(ppath)
                    words = ocr_words(ppath, page=1)
                loc = read_location_block(words, report_pages[0].width,
                                          report_pages[0].height)
                resolved = resolve(loc, st.session_state.get("rq_features"),
                                   fiche_milepost=row.mp,
                                   fallback_coordinates=(coords or {}).get(
                                       row.crash_id))
                st.caption("Resolved location: " + resolved.summary())
                for note in resolved.notes[:3]:
                    st.caption("· " + note)
            akey = f"rq_assist_res_{row.crash_id}"
            if assist_mode != "Off" and st.button("Run AI assist",
                                                  key=f"rq_run_{row.crash_id}"):
                if not report_pages:
                    st.warning("No redacted report to assist from.")
                else:
                    import safety_eval.review_assist as ra
                    ctx = ra.StudyContext(analysis_type=analysis_type,
                                          study_point=point, mp_range=mp_range,
                                          prescreen_ft=item.dist_ft,
                                          resolved_location=resolved,
                                          fiche_milepost=row.mp)
                    with st.spinner("Reviewing the redacted report..."):
                        try:
                            st.session_state[akey] = ra.assist(
                                row, ctx, report_pages, mode=assist_mode.lower(),
                                redacted=True)
                        except Exception as exc:   # noqa: BLE001 - show, don't die
                            st.error(f"Assist failed: {exc}")
            res = st.session_state.get(akey)
            if res is not None and res.mode == assist_mode.lower():
                if res.mode == "decide":
                    if res.proposed_status:
                        st.success(f"AI proposes **{res.proposed_status}** "
                                   f"({res.confidence}) — {res.where_occurred}")
                    for ev in res.evidence[:4]:
                        st.caption("• " + ev)
                    if res.validation_problems:
                        st.warning(" ".join(res.validation_problems))
                    if res.needs_manual:
                        st.warning("Low confidence or unresolved; decide manually.")
                    det = res.as_determination()
                    if (det is not None and not res.needs_manual
                            and st.button("Accept proposal and record",
                                          key=f"rq_accept_{row.crash_id}")):
                        problems = rq.validate_determination(det, analysis_type)
                        if problems:
                            for pmsg in problems:
                                st.error(pmsg)
                        else:
                            rq.record_determination(audit_path, det,
                                                    previous=row,
                                                    source="review-assist:decide")
                            dets[row.crash_id] = det
                            st.session_state["rq_pos"] = min(pos, len(pending) - 2)
                            st.rerun()
                else:
                    st.info("AI prepared the evidence; the determination is yours.")
                    for lab, val in (("Diagram", res.diagram_summary),
                                     ("Narrative", res.narrative_summary),
                                     ("Report places it", res.report_location),
                                     ("Distance", res.distance_assessment),
                                     ("Rule", res.applicable_rule)):
                        if val:
                            st.caption(f"**{lab}:** {val}")
                    if res.candidate_statuses:
                        st.caption("Plausible: " + ", ".join(res.candidate_statuses))
                    if res.comment:
                        st.caption("Draft comment (copy if useful):")
                        st.code(res.comment, language=None)

            nav1, nav2 = st.columns(2)
            if nav1.button("Previous"):
                st.session_state["rq_pos"] = max(0, pos - 1)
                st.rerun()
            if nav2.button("Skip / next"):
                st.session_state["rq_pos"] = (pos + 1) % len(pending)
                st.rerun()

            base = st.radio("Status", rq.STATUS_VOCAB[analysis_type],
                            horizontal=True, key=f"rq_status_{row.crash_id}")
            suffix = st.checkbox("Second section (-2)", key=f"rq_sfx_{row.crash_id}",
                                 help="Split-section evaluations mark section 2 "
                                      "statuses IS-2 / RE-2 / ... (SS-6002M).")
            new_mp = st.number_input("New MP", value=float(row.new_mp or 0.0),
                                     step=0.001, format="%.3f",
                                     key=f"rq_mp_{row.crash_id}")
            use_mp = st.checkbox("Record New MP", value=row.new_mp is not None,
                                 key=f"rq_usemp_{row.crash_id}")
            comment = st.text_input(
                "Comment (brief; docs/03 conventions)",
                value=row.comment or "",
                key=f"rq_cmt_{row.crash_id}",
                help="Patterns: `no intersection in diagram`, `>150'`, "
                     "`at [road]`, `Remileposted from GPS coordinates; "
                     "near [road]`.")

            if st.button("Record determination", type="primary"):
                det = rq.Determination(
                    crash_id=row.crash_id,
                    status=base + ("-2" if suffix else ""),
                    new_mp=new_mp if use_mp else None,
                    comment=comment.strip() or None,
                )
                problems = rq.validate_determination(det, analysis_type)
                if problems:
                    for pmsg in problems:
                        st.error(pmsg)
                else:
                    rq.record_determination(audit_path, det, previous=row)
                    dets[row.crash_id] = det
                    st.session_state["rq_pos"] = min(pos, len(pending) - 2)
                    st.rerun()

        with right:
            if report_note:
                (st.info if binder_index is None else st.warning)(report_note)
            if report_pages:
                st.caption("Redacted DMV-349 (front page first; PII removed "
                           "before display, ZIPs and crash IDs kept). The AI "
                           "assist sees exactly these redacted pages.")
                for i, img in enumerate(report_pages, 1):
                    st.image(img, caption=f"page {i} of {len(report_pages)}",
                             use_container_width=True)

    if dets and st.button(f"Save reviewed workbook ({len(dets)} "
                          "determination(s))"):
        out_path = os.path.splitext(wb_path)[0] + ".reviewed.xlsx"
        n = rq.apply_determinations(wb_path, out_path, list(dets.values()),
                                    sheet=sheet, analysis_type=analysis_type)
        st.success(f"Wrote {n} determination(s) -> {out_path} "
                   f"(audit trail: {audit_path})")
        with open(out_path, "rb") as fh:
            st.download_button("Download reviewed workbook", fh.read(),
                               file_name=os.path.basename(out_path))

    with st.expander("Score assist proposals against a finished review"):
        st.caption("Your reviewed statuses are ground truth; the number "
                   "measures the assist, never the review. Disagreements "
                   "are listed so the assist's rules can be tightened.")
        prop_up = st.file_uploader("proposals.jsonl (review-assist output)")
        truth_up = st.file_uploader("Your reviewed fiche workbook (.xlsx)",
                                    key="score_truth")
        if prop_up and truth_up and st.button("Score"):
            from safety_eval.review_assist import score_proposals
            with tempfile.TemporaryDirectory() as tmp:
                s = score_proposals(_save_upload(prop_up, tmp),
                                    _save_upload(truth_up, tmp))
            if not s["scored"]:
                st.warning("No proposal matched a reviewed crash.")
            else:
                st.metric("Agreement",
                          f"{s['agree']}/{s['scored']} "
                          f"({s['agree'] / s['scored']:.0%})")
                st.table([{"Engineer status": k,
                           "Matched": f"{v['agree']}/{v['n']}"}
                          for k, v in sorted(s["by_status"].items())])
                if s["disagreements"]:
                    st.table([{"Crash": c, "Engineer": a, "Assist": p,
                               "Confidence": conf}
                              for c, a, p, conf in s["disagreements"]])


if __name__ == "__main__":
    main()
