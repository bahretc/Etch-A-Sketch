"""The Start page: one study, one drop zone, one next step.

An engineer who has never seen the app should be able to open it, drop the
TEAAS exports and the crash reports in one go, and be told what to click
next. The page therefore does three things, top to bottom:

1. **Study** - open one or create one, right here (the sidebar mirrors it):
   the study number, its type and its analysis (intersection, section, or a
   bike/ped intersection for an HSIP package).
2. **Drop zone** - every file is recognised from its content
   (:mod:`safety_eval.intake`) and filed under its study role; anything
   the sniff cannot place is offered back with its choices.
3. **Criteria** - the study type's criteria sheet (period, limits,
   warrants, inputs, deliverables; :mod:`safety_eval.criteria`) and what
   the open study still owes them.
4. **Steps** - the workflow as numbered cards with what is done, and the
   next step made obvious.

State is never carried by colour alone; every status is a word.
"""
from __future__ import annotations

import os


def study_panel(st, ws, kinds, keys, wsm) -> None:
    """Open or create the study in the main column."""
    from safety_eval.study_type import ANALYSIS_KINDS

    with st.container(border=True):
        if ws:
            label = kinds.get(ws.study_type)
            facts = [label.label if label else ws.study_type,
                     ANALYSIS_KINDS[ws.analysis].label]
            for key, fmt in (("route", "{}"), ("mp_lo", "MP {}"),
                             ("mp_hi", "to {}"), ("context", "{}")):
                v = ws.param(key)
                if v is not None and v != "":
                    facts.append(fmt.format(v))
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.subheader(f"Study {ws.study}")
            c1.caption(" · ".join(str(f) for f in facts))
            c2.caption(f"Folder: {os.path.abspath(ws.root)}")
            return
        st.markdown("**Start a study**")
        st.caption("Type the study number, pick the study type and what it "
                   "looks at (an intersection, a section, or a bike/ped "
                   "intersection for an HSIP package); every file you drop "
                   "below is filed into its folder.")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1], vertical_alignment="bottom")
        number = c1.text_input("Study number", key="start_study_number",
                               placeholder="41000079549")
        if "start_study_type" not in st.session_state:
            # Start from the sidebar's choice, so the panel and the sidebar
            # never disagree on first sight.
            st.session_state["start_study_type"] = st.session_state.get(
                "study_type", keys[0])
        kind_key = c2.selectbox("Study type", keys, key="start_study_type",
                                format_func=lambda k: kinds[k].label)
        a_keys = list(kinds[kind_key].analyses)
        if (st.session_state.get("start_analysis") not in a_keys
                or st.session_state.get("start_analysis_of") != kind_key):
            side = st.session_state.get("analysis")
            same_type = kind_key == st.session_state.get("study_type")
            st.session_state["start_analysis"] = (
                side if same_type and side in a_keys else a_keys[0])
        st.session_state["start_analysis_of"] = kind_key
        a_key = c3.selectbox("Analysis", a_keys, key="start_analysis",
                             format_func=lambda k: ANALYSIS_KINDS[k].label,
                             help=ANALYSIS_KINDS[
                                 st.session_state["start_analysis"]].description)
        if c4.button("Create", type="primary", key="start_create",
                     use_container_width=True):
            if not number.strip():
                # Say so in place; the rest of the page stays where it is.
                st.warning("Type the study number first, then create the "
                           "study.")
            else:
                try:
                    if number.strip() in wsm.list_studies():
                        wsm.Workspace.open(number.strip())   # open, not error
                    else:
                        wsm.Workspace.create(number.strip(),
                                             study_type=kind_key,
                                             analysis=a_key)
                except (ValueError, OSError) as exc:
                    st.error(f"{exc}. Correct the number and create it "
                             "again.")
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
            with st.spinner(f"Filing {n_add} file"
                            f"{'s' if n_add != 1 else ''} into study "
                            f"{ws.study}"):
                done, skipped = intake.attach_all(
                    ws, [(up.name, up.getvalue()) for up in files],
                    roles=picks)
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
    missing = [f"{name} ({what})" for role, name, what in CHECKLIST
               if not ws.paths(role)]
    if missing:
        st.caption("Still useful to drop: " + "; ".join(missing) + ".")


def criteria_card(st, ws, kind, analysis=None) -> None:
    """The study's criteria, in words, and what it still owes them.

    One expander: the period, the limits, the review vocabulary and the
    warrants on top; the type-specific inputs the generic checklist does
    not show, with their state; the deliverables; and, for an HSIP
    intersection, the urban or rural context picker, because it decides
    the pull length and the warrant set (docs/12).
    """
    from safety_eval import criteria as cr
    from safety_eval.intake import CHECKLIST
    from safety_eval.study_type import HSIP, INTERSECTION

    a_key = (ws.analysis if ws else
             analysis.key if analysis else kind.default_analysis)
    ctx = ws.param("context") if ws else None
    is_hsip_junction = kind.key == HSIP and a_key == INTERSECTION
    if not is_hsip_junction:
        ctx = None
    try:
        crit = cr.for_study(kind.key, a_key, ctx)
    except ValueError:
        crit = cr.for_study(kind.key, a_key)
    title = f"Study criteria: {crit.title}"
    with st.expander(title, expanded=False):
        if is_hsip_junction:
            options = ["(not set)", "urban", "rural"]
            current = ctx if ctx in ("urban", "rural") else "(not set)"
            pick = st.radio(
                "Context", options, index=options.index(current),
                horizontal=True, key="criteria_context",
                help="From the HSIP GIS City field: a municipality name is "
                     "urban (5-year pull), RURAL is rural (10-year pull). "
                     "It also picks the warrant set.")
            if ws and pick != current and pick != "(not set)":
                ws.set_params(context=pick)
                st.rerun()
        st.markdown(
            f"- **Analysis period:** {crit.period_text}.\n"
            f"- **Study limits:** {crit.limits_text}.\n"
            f"- **Review statuses:** {', '.join(crit.review_statuses)}.\n"
            f"- **Warrants:** {', '.join(crit.warrants) if crit.warrants else 'none'}.")
        if ws:
            notes = cr.check_params(crit, ws.manifest.get("params", {}))
            if notes:
                st.warning("Still owed: " + " ".join(notes))
            else:
                st.caption("The recorded study facts meet the criteria.")
        generic = {role for role, _, _ in CHECKLIST}
        extra = [i for i in crit.inputs if i.role not in generic]
        if extra:
            chips = []
            for i in extra:
                have = bool(ws and ws.paths(i.role))
                mark = "✓" if have else ("○" if i.required else "·")
                cls = "done" if have else "todo"
                opt = "" if i.required else " (optional)"
                chips.append(f'<span class="se-chip {cls}">{mark} '
                             f'{i.label}{opt}</span>')
            st.markdown("**Also for this study type** " + "".join(chips),
                        unsafe_allow_html=True)
        st.markdown("**Deliverables**")
        st.markdown("\n".join(
            f"- {d.name}{' (public document)' if d.public else ''}: {d.how}"
            for d in crit.deliverables))
        st.markdown("**Rules**")
        rows = ["| Topic | Rule | Source |", "|---|---|---|"]
        for c in crit.criteria:
            rows.append(f"| {c.topic} | {c.rule.replace('|', '/')} | "
                        f"{c.source} |")
        st.markdown("\n".join(rows))
        st.caption("The full sheet: `safety-eval criteria --type "
                   f"{crit.study_type} --analysis {crit.analysis}"
                   + (f" --context {crit.context}" if crit.context else "")
                   + "`; every sheet is docs/15.")


def steps(st, ws, kind, PAGE, analysis=None) -> None:
    """The workflow, numbered, with the next step made obvious."""
    from safety_eval.study_type import (ANALYSIS_KINDS, BIKEPED, EVALUATION,
                                        SECTION)

    a_key = (ws.analysis if ws else
             analysis.key if analysis else kind.default_analysis)
    shape = ANALYSIS_KINDS[a_key]

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
        if a_key == BIKEPED:
            blurb = ("Intersection warrant screen off your IS/RE/ADD "
                     "determinations, the import list, and the aerial-exhibit "
                     "collision diagram sheet; the pull itself is the 10-year, "
                     "300 ft y-line TEAAS export (docs/12).")
        else:
            blurb = (f"{shape.label} warrant screen off your IS/RE/ADD "
                     "determinations, with the import list and the crash "
                     "map.")
        items.append((PAGE["warrants"], "Run the HSIP warrants", blurb,
                      False))
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
        ]
        if a_key == SECTION:
            items.append((PAGE["strip_diagram"], "Draw the strip collision "
                          "diagram", "Fan-out callouts along the section "
                          "from the reviewed crashes.", False))
        items += [
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
                    # The page's one primary cue: a badge with the words.
                    st.badge("Next step", icon=":material/arrow_forward:",
                             color="blue")
            mid.caption(blurb)


def start_page(st, kind, ws, PAGE, ROLES, kinds, keys, wsm, env_check,
               analysis=None) -> None:
    # The same title and intro treatment as every other page.
    st.header("NCDOT Safety Studies")
    st.caption("Drop the files, follow the steps. Every number stays "
               "traceable to TEAAS and the reports.")
    study_panel(st, ws, kinds, keys, wsm)
    drop_zone(st, ws, ROLES)
    checklist(st, ws)
    criteria_card(st, ws, kind, analysis=analysis)
    steps(st, ws, kind, PAGE, analysis=analysis)
    with st.expander("Environment check"):
        env_check(st)
