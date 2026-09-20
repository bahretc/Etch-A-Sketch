"""The Start page: one study, one drop zone, one next step.

An engineer who has never seen the app should be able to open it, drop the
TEAAS exports and the crash reports in one go, and be told what to click
next. The page therefore does three things, top to bottom:

1. **Study** - open one or create one, right here (the sidebar mirrors it).
2. **Drop zone** - every file is recognised from its content
   (:mod:`safety_eval.intake`) and filed under its study role; anything
   the sniff cannot place is offered back with its choices.
3. **Steps** - the workflow as numbered cards with what is done, and the
   next step made obvious.

State is never carried by colour alone; every status is a word.
"""
from __future__ import annotations

import os


def _card_css() -> str:
    return """
    <style>
    .se-hero {padding: 0.2rem 0 0.6rem 0;}
    .se-hero h1 {font-size: 2.0rem; margin: 0 0 0.25rem 0;}
    .se-hero p {margin: 0; opacity: 0.72; font-size: 1.02rem;}
    .se-drop-title {font-weight: 600; font-size: 1.05rem; margin-bottom: 0.1rem;}
    .se-drop-sub {opacity: 0.7; font-size: 0.92rem; margin-bottom: 0.6rem;}
    .se-chip {display: inline-block; padding: 3px 10px; margin: 2px 6px 2px 0;
              border-radius: 999px; font-size: 0.86rem;
              border: 1px solid rgba(23,27,38,0.12);
              background: var(--secondary-background-color);}
    .se-chip.done {border-color: rgba(0,158,115,0.45);}
    .se-chip.todo {opacity: 0.75;}
    .se-step-n {font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase;
                opacity: 0.6;}
    .se-step-t {font-weight: 600; font-size: 1.05rem;}
    </style>"""


def study_panel(st, ws, kinds, keys, wsm) -> None:
    """Open or create the study in the main column."""
    with st.container(border=True):
        if ws:
            label = kinds.get(ws.study_type)
            facts = [label.label if label else ws.study_type]
            for key, fmt in (("route", "{}"), ("mp_lo", "MP {}"),
                             ("mp_hi", "to {}"), ("context", "{}")):
                v = ws.param(key)
                if v is not None and v != "":
                    facts.append(fmt.format(v))
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.subheader(f"Study {ws.study}")
            c1.caption(" · ".join(str(f) for f in facts))
            c2.caption(f"Folder: {os.path.relpath(ws.root)}")
            return
        st.markdown("**Start a study**")
        st.caption("Type the study number and pick the study type; every "
                   "file you drop below is filed into its folder.")
        c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        number = c1.text_input("Study number", key="start_study_number",
                               placeholder="41000079549")
        kind_key = c2.selectbox("Study type", keys, key="start_study_type",
                                format_func=lambda k: kinds[k].label)
        if c3.button("Create", type="primary", key="start_create",
                     use_container_width=True):
            if not number.strip():
                st.warning("Type the study number first.")
                st.stop()
            try:
                if number.strip() in wsm.list_studies():
                    wsm.Workspace.open(number.strip())   # open, not error
                else:
                    wsm.Workspace.create(number.strip(), study_type=kind_key)
            except (ValueError, OSError) as exc:
                st.error(str(exc))
            else:
                # the sidebar reads the type off the manifest next run
                st.session_state["pending_study"] = number.strip()
                st.rerun()
        existing = wsm.list_studies()
        if existing:
            st.caption("Or open one: " + ", ".join(existing[:8])
                       + (" ..." if len(existing) > 8 else "")
                       + " (the **Study** box in the sidebar).")


def drop_zone(st, ws, ROLES) -> None:
    """One zone for everything; each file is recognised and filed."""
    from safety_eval import intake

    nonce = st.session_state.get("intake_nonce", 0)
    with st.container(border=True):
        st.markdown('<div class="se-drop-title">Drop your files here</div>'
                    '<div class="se-drop-sub">TEAAS exports, the Features '
                    'Report, crash report scans, workbooks. Any number at '
                    'once; each one is recognised from its content and '
                    'filed under the right role.</div>',
                    unsafe_allow_html=True)
        files = st.file_uploader(
            "Drop files here", accept_multiple_files=True,
            key=f"intake_{nonce}", label_visibility="collapsed",
            help=intake.RECOGNISED)
        if not files:
            st.caption("Recognised: " + intake.RECOGNISED)
            return
        labels = {r: lab for r, (lab, _) in ROLES.items()}
        picks = {}
        st.markdown("**What was recognised**")
        for up in files:
            data = up.getvalue()
            det = intake.sniff(up.name, data)
            c1, c2, c3 = st.columns([3, 3, 2], vertical_alignment="center")
            c1.write(f"**{up.name}**")
            c1.caption(f"{len(data) / 1e6:.1f} MB · {det.why}")
            if det.sure:
                c2.write(f"Recognised as **{det.label}**")
                options = ["As recognised"] + [
                    labels[r] for r in ROLES if r != det.role] + ["Skip"]
            else:
                c2.write(f"**{det.label}**: not sure, so skipped unless "
                         "you pick a role")
                options = ["Skip"] + [labels[r] for r in det.choices] + [
                    labels[r] for r in ROLES if r not in det.choices]
            choice = c3.selectbox("File as", options, key=f"pick_{nonce}_{up.name}",
                                  label_visibility="collapsed")
            if choice == "As recognised":
                picks[up.name] = det.role
            elif choice == "Skip":
                picks[up.name] = "skip"
            else:
                picks[up.name] = next(r for r, lab in labels.items()
                                      if lab == choice)
        n_add = sum(1 for r in picks.values() if r != "skip")
        if not ws:
            st.info("Create or open a study above and these files are filed "
                    "into it.")
        elif st.button(f"Add {n_add} file{'s' if n_add != 1 else ''} to study "
                       f"{ws.study}", type="primary", disabled=n_add == 0,
                       key=f"intake_add_{nonce}"):
            done, skipped = intake.attach_all(
                ws, [(up.name, up.getvalue()) for up in files], roles=picks)
            st.session_state["intake_nonce"] = nonce + 1
            st.session_state["intake_last"] = (
                [(d.name, labels[d.role]) for d in done],
                [n for n, _ in skipped])
            st.rerun()
    last = st.session_state.get("intake_last")
    if last and not files:
        done, skipped = last
        if done:
            st.success("Filed: " + "; ".join(f"{n} as {lab}" for n, lab in done))
        if skipped:
            st.caption("Not filed: " + ", ".join(skipped))


def checklist(st, ws) -> None:
    """What the study has, as words on chips."""
    from safety_eval.intake import CHECKLIST

    if not ws:
        return
    chips = []
    for role, name, what in CHECKLIST:
        n = len(ws.paths(role))
        if n:
            extra = f" ({n})" if n > 1 else ""
            chips.append(f'<span class="se-chip done">✓ {name}{extra}</span>')
        else:
            chips.append(f'<span class="se-chip todo">○ {name}</span>')
    st.markdown("**In the study** " + "".join(chips), unsafe_allow_html=True)
    missing = [what for role, _, what in CHECKLIST if not ws.paths(role)]
    if missing:
        st.caption("Still useful to drop: " + "; ".join(missing) + ".")


def steps(st, ws, kind, PAGE) -> None:
    """The workflow, numbered, with the next step made obvious."""
    from safety_eval.study_type import EVALUATION

    def done(role):
        return bool(ws and ws.path(role))

    items = [
        (PAGE["fiche"], "Build the fiche workbook",
         "Assemble the TEAAS exports into the working sheet and run the "
         "colour screen (IS / ? / NIS"
         + (" / DEL for animals" if kind.deletes_animals else "") + ").",
         done("workbook")),
        (PAGE["redact"], "Redact the crash reports",
         "Every DMV-349 is redacted before it is stored or shown; ZIP codes "
         "and crash IDs are kept.", done("binder_index")),
        (PAGE["review"], "Review the crashes",
         "The queue shows the redacted report beside the coded data; you "
         "decide every status, with optional AI assist.",
         done("reviewed_workbook")),
    ]
    if kind.runs_warrants:
        items.append((PAGE["warrants"], "Run the HSIP warrants",
                      "Section or intersection warrant screen off your "
                      "IS/RE/ADD determinations, with the import list and "
                      "the crash map.", False))
    if kind.key == EVALUATION:
        items += [
            (PAGE["evaluation"], "Populate the Evaluation Workbook",
             "A real NCDOT template; every write is integrity-verified and "
             "drawings stay byte-identical.", done("evaluation_workbook")),
            (PAGE["aadt"], "Fill the AADT table",
             "Leg AADTs from the NCDOT stations layer with the black/red "
             "convention, written into the Set-up sheet.", False),
            (PAGE["map_block"], "Compose the map block",
             "The Map/Satellite Views image in the team format.", False),
            (PAGE["report"], "Draft the report text",
             "Items for Discussion and Additional Information drafts; you "
             "review and paste.", False),
            (PAGE["assumptions"], "Send the assumptions email",
             "The team-template .docx from a YAML or the Master Evaluation "
             "Spreadsheet row.", False),
            (PAGE["print"], "Print and bind the deliverables",
             "Results page print matched to Excel; Complete Evaluation and "
             "Web PDFs.", False),
            (PAGE["qa"], "Run the QA checks",
             "Deterministic checks on the workbook and PDFs, then the "
             "optional sweep.", False),
            (PAGE["finish"], "Finish the package",
             "One pass over the WO folder: redact, map, print, bind, QA log "
             "and certificate, zip.", False),
        ]
    else:
        items.append((PAGE["package"], "Build the maps and checks",
                      "Location, Study Area and AADT maps, route curves and "
                      "crests, the location check and the CalculatedAADT "
                      "workbook.", False))
    next_i = next((i for i, it in enumerate(items) if not it[3]), None)
    st.markdown("**Steps**")
    for i, (path, title, blurb, is_done) in enumerate(items):
        with st.container(border=True):
            left, mid = st.columns([2.6, 3], vertical_alignment="center")
            with left:
                st.page_link(path, label=f"{i + 1}. {title}",
                             icon=(":material/check_circle:" if is_done
                                   else ":material/arrow_forward:"))
                if is_done:
                    st.caption("Done: saved in the study.")
                elif i == next_i:
                    st.caption("Next step.")
            mid.caption(blurb)


def start_page(st, kind, ws, PAGE, ROLES, kinds, keys, wsm, env_check) -> None:
    st.markdown(_card_css(), unsafe_allow_html=True)
    st.markdown('<div class="se-hero"><h1>NCDOT Safety Studies</h1>'
                '<p>Drop the files, follow the steps. Every number stays '
                'traceable to TEAAS and the reports.</p></div>',
                unsafe_allow_html=True)
    study_panel(st, ws, kinds, keys, wsm)
    drop_zone(st, ws, ROLES)
    checklist(st, ws)
    steps(st, ws, kind, PAGE)
    with st.expander("Environment check"):
        env_check(st)
