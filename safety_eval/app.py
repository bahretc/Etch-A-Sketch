"""Streamlit shell for the NCDOT safety-evaluation workflow (docs/07).

Run with:  streamlit run safety_eval/app.py

Three tabs:

1. **Build Evaluation** - upload the TEAAS exports and YAMLs, pick a template,
   generate the populated workbook (crash sheets, Set-up, results, Binned
   Crashes, pre-screened Filtered Fiche) and download it.
2. **Redact Crash Reports** - every uploaded DMV-349 is redacted BEFORE it is
   stored or shown: names, addresses, DOB, phone, and license numbers are
   blacked out; ZIP codes and crash IDs are kept. Output is image-only.
3. **Review Filtered Fiche** - load a workbook's Filtered Fiche and see the
   determination counts; the engineer edits statuses in Excel (the tool never
   makes determinations).
"""
from __future__ import annotations

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
        ["Build Evaluation", "Redact Crash Reports", "Review Filtered Fiche"])

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
        st.caption("Counts from a workbook's Filtered Fiche. Determinations "
                   "are made by the engineer in the sheet itself.")
        wb_up = st.file_uploader("Evaluation workbook (.xlsx)", type=["xlsx"])
        if wb_up:
            from collections import Counter

            from .binned_sheet import read_filtered_fiche
            with tempfile.TemporaryDirectory() as tmp:
                path = _save_upload(wb_up, tmp)
                try:
                    statuses = read_filtered_fiche(path)
                except KeyError as exc:
                    st.error(str(exc))
                    st.stop()
            counts = Counter((d.get("status") or "(blank)")
                             for d in statuses.values())
            st.write({k: v for k, v in counts.most_common()})
            blank = counts.get("(blank)", 0)
            if blank:
                st.info(f"{blank} crash(es) still need a determination.")


if __name__ == "__main__":
    main()
