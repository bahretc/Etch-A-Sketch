"""Streamlit shell for the NCDOT safety-evaluation workflow (docs/07).

Run with:  streamlit run safety_eval/app.py

Three tabs:

1. **Build Evaluation** - upload the TEAAS exports and YAMLs, pick a template,
   generate the populated workbook (crash sheets, Set-up, results, Binned
   Crashes, pre-screened Filtered Fiche) and download it.
2. **Redact Crash Reports** - every uploaded DMV-349 is redacted BEFORE it is
   stored or shown: names, addresses, DOB, phone, and license numbers are
   blacked out; ZIP codes and crash IDs are kept. Output is image-only.
3. **Review Queue** - the interactive fiche review (docs/07 Phase 3): load a
   workbook's Filtered Fiche and an OCR binder index, walk the queue crash by
   crash with the REDACTED DMV-349 pages beside the coded data, and record
   IS/RE/ADD/DEL/NIS determinations with validation and an audit trail. The
   tool prepares and records; the engineer decides every status.
"""
from __future__ import annotations

import functools
import os
import tempfile


def _save_upload(uploaded, workdir: str) -> str | None:
    if uploaded is None:
        return None
    path = os.path.join(workdir, uploaded.name)
    with open(path, "wb") as fh:
        fh.write(uploaded.getbuffer())
    return path


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="NCDOT Safety Evaluations", layout="wide")
    st.title("NCDOT HSIP Safety Evaluations")
    tab_build, tab_redact, tab_review = st.tabs(
        ["Build Evaluation", "Redact Crash Reports", "Review Queue"])

    with tab_build:
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
                from .cli import main as cli_main
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

    with tab_redact:
        st.caption("Crash reports are redacted BEFORE review: names, "
                   "addresses, DOB, phone, and license numbers are removed. "
                   "ZIP codes and crash IDs are kept. Spot-check the result; "
                   "OCR can miss handwriting.")
        report_up = st.file_uploader("Crash report (PDF/TIFF/PNG/JPG)",
                                     type=["pdf", "tif", "tiff", "png", "jpg"])
        keep_zip = st.checkbox("Keep ZIP codes visible", True)
        if report_up and st.button("Redact", type="primary"):
            from .redact import redact_file
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

    with tab_review:
        _review_queue_tab(st)


@functools.lru_cache(maxsize=16)
def _queue_pages(index_path: str, crash_id: str, keep_zip: bool = True):
    """Redacted page images for one crash (cached; OCR redaction is slow)."""
    from .binder import BinderIndex, render_crash_pages
    idx = BinderIndex.load(index_path)
    return render_crash_pages(idx, crash_id, dpi=idx.dpi, keep_zip=keep_zip)


def _review_queue_tab(st) -> None:
    from . import review_queue as rq

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
            "Detailed export with coordinates (optional)",
            help="TEAAS Detailed Crash ID List; enables the GPS distance "
                 "pre-screen.")
        study_pt = st.text_input("Study point lat,lon (optional)",
                                 help="Used with coordinates to sort the "
                                      "queue by distance.")
        mp_rng = st.text_input("Study milepost range lo:hi (optional)")

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
        from .binder import BinderIndex, reconcile_index
        binder_index = BinderIndex.load(index_path)
        suggestions = reconcile_index(
            binder_index, {r.crash_id for r in review.rows})
        if suggestions:
            st.warning(
                "Possible misread binder header IDs (fix with "
                "`safety-eval binder-index --known-ids ...` and reload): "
                + ", ".join(f"{a} -> {b}" for a, b in sorted(suggestions.items())))

    coords = rq.parse_coordinates(coords_path) if coords_path else None
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

        left, right = st.columns([2, 3])
        with left:
            st.subheader(f"Crash {row.crash_id}")
            meta = [f"queue {pos + 1} of {len(pending)}",
                    f"sheet row {row.row}", f"group: {row.banner or '?'}"]
            if item.dist_ft is not None:
                meta.append(f"{item.dist_ft:,.0f} ft from study point")
            st.caption(" · ".join(meta))
            if item.skip_reason:
                st.info(f"Skip suggested: {item.skip_reason}")
            show = {k: v for k, v in row.fields.items() if v not in (None, "")}
            st.table({"field": list(show), "value": [str(v) for v in show.values()]})

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
            if binder_index is None:
                st.info("No binder index loaded; reviewing coded data only.")
            elif not item.has_report:
                st.warning("No DMV-349 for this crash in the indexed binder; "
                           "flag as unverifiable if a determination needs "
                           "the report (docs/03).")
            else:
                st.caption("Redacted DMV-349 (front page first; PII removed "
                           "before display, ZIPs and crash IDs kept).")
                with st.spinner("Rendering redacted pages..."):
                    try:
                        pages = _queue_pages(index_path, row.crash_id)
                    except Exception as exc:   # noqa: BLE001 - show, don't die
                        st.error(f"Page retrieval failed: {exc}")
                        pages = []
                for i, img in enumerate(pages, 1):
                    st.image(img, caption=f"page {i} of {len(pages)}",
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


if __name__ == "__main__":
    main()
