"""Lane departure CL/R ledger (docs/07 Phase 3 item 13, rules from docs/03).

Section rumble-strip evaluations classify every lane-departure crash as
**Centerline** (first-event path crossed the centerline into the opposing
side) or **Right** (ran off its own side without crossing), flag it as a
target (Target-1?), and record whether the treatment could have corrected it
(Correctable?).  Those values live in SEVERAL sheets at once - observed on
the completed SS-6002M workbook:

* Filtered Fiche: Correctable? / Departure / Travel Dir columns
* Before and After: Correctable? / Target-1? / Target-2? / Departure
* Binned Crashes: Correctable? / Departure / Travel Dir

docs/03 QC habit: when a classification changes, every location the value
appears must change with it; hand-editing one sheet and forgetting another
is a real, observed defect class.  This module reads the ledger from all
sheets, checks cross-sheet consistency and the docs/03 rules, and applies a
changed call to every sheet in ONE template-preserving patch.

Rules encoded exactly (docs/03, do not improvise):

* First harmful event rule: the classification keys to the first harmful
  event; multi-event sequences (right / overcorrect / cross) classify by the
  first event.  When narrative and stored values conflict, the stored value
  keyed to the first harmful event governs.
* Correctability by treatment: centerline rumble strips correct crashes
  whose first event crossed the centerline; edgeline strips those that
  crossed the edgeline; a DUAL treatment corrects either (applying only the
  centerline test on a dual project undercounts - the SS-6002M correction).
  Standing exemptions: mechanical failure, medical event, avoidance
  maneuver.
* Side-street run-throughs are excluded from the lane departure target set:
  remove the Target flag and the departure classification everywhere they
  appear, keep the crash in Total Crashes as a non-target, and document the
  rationale in the comment field.
* Crashes with no report in the binder stay as stored, flagged
  unverifiable - the tool never reclassifies them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .xlsx_patch import CellEdit, xlsx_patch

CENTERLINE = "Centerline"
RIGHT = "Right"

#: treatment -> departure directions its test covers (docs/03)
TREATMENT_COVERS = {
    "centerline": {CENTERLINE},
    "edgeline": {RIGHT},
    "dual": {CENTERLINE, RIGHT},
}

#: standing exemptions from correctable (docs/03)
EXEMPTIONS = ("mechanical failure", "medical event", "avoidance maneuver")

#: sheets that carry ledger columns, in the order they are patched
LEDGER_SHEETS = ("Filtered Fiche", "Before", "After", "Binned Crashes")

_ALIASES = {
    "crash id": "crash_id",
    "correctable?": "correctable", "correctable": "correctable",
    "target-1?": "target1", "target-2?": "target2",
    "departure": "departure", "travel dir": "travel_dir",
    "comment": "comment", "comments": "comment",
}


def correctable_under(treatment: str, departure: str | None,
                      exempt: bool = False) -> bool:
    """The docs/03 treatment test for a classified departure.

    ``exempt`` is the engineer's finding of a standing exemption
    (mechanical failure, medical event, avoidance maneuver).
    """
    covers = TREATMENT_COVERS.get(treatment)
    if covers is None:
        raise ValueError(
            f"Unknown treatment {treatment!r}; expected one of "
            f"{sorted(TREATMENT_COVERS)}")
    if exempt or departure is None:
        return False
    return departure in covers


@dataclass
class LedgerRow:
    """One crash's ledger values on one sheet."""
    crash_id: str
    sheet: str
    row: int
    departure: str | None = None
    correctable: str | None = None       # 'Y' / 'N' as written
    target1: str | None = None
    target2: str | None = None
    travel_dir: str | None = None
    comment: str | None = None
    columns: dict = field(default_factory=dict)   # role -> column letter


def _col_letter(idx: int) -> str:
    out = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def read_ledger(workbook_path: str,
                sheets=LEDGER_SHEETS) -> dict[str, dict[str, LedgerRow]]:
    """Read ledger values from every sheet that has them.

    Returns ``{sheet: {crash_id: LedgerRow}}`` for the sheets present in the
    workbook whose header row carries a Crash ID column.  Column positions
    are header-detected per sheet (they differ between the Filtered Fiche,
    Before/After, and Binned Crashes layouts).
    """
    import openpyxl

    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    out: dict[str, dict[str, LedgerRow]] = {}
    try:
        for sheet in sheets:
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            roles: dict[int, str] = {}
            columns: dict[str, str] = {}
            rows: dict[str, LedgerRow] = {}
            for i, row in enumerate(ws.iter_rows(values_only=True), 1):
                if not roles:
                    if row and any(str(v or "").strip().lower() == "crash id"
                                   for v in row):
                        for j, v in enumerate(row):
                            key = str(v or "").strip().lower().replace("\n", " ")
                            role = _ALIASES.get(key)
                            if role and role not in columns:
                                roles[j] = role
                                columns[role] = _col_letter(j)
                    continue
                vals = {role: row[j] if j < len(row) else None
                        for j, role in roles.items()}
                cid = vals.get("crash_id")
                if cid is None or not str(cid).strip().isdigit():
                    continue
                cid = str(cid).strip()

                def _s(role):
                    v = vals.get(role)
                    return str(v).strip() if v not in (None, "") else None

                rows[cid] = LedgerRow(
                    crash_id=cid, sheet=sheet, row=i,
                    departure=_s("departure"), correctable=_s("correctable"),
                    target1=_s("target1"), target2=_s("target2"),
                    travel_dir=_s("travel_dir"), comment=_s("comment"),
                    columns=columns,
                )
            if columns.keys() & {"departure", "correctable", "target1"}:
                out[sheet] = rows
    finally:
        wb.close()
    return out


# --------------------------------------------------------------------------- #
# consistency (docs/03 QC habit: trace every location the value appears)
# --------------------------------------------------------------------------- #
def check_consistency(ledger: dict[str, dict[str, LedgerRow]],
                      treatment: str | None = None
                      ) -> tuple[list[str], list[str]]:
    """Cross-sheet and rule checks; returns ``(errors, confirmations)``.

    Errors are defects (docs/03):

    * the same crash carrying different Departure / Correctable values on
      different sheets;
    * a classified departure without a Target-1 flag (and vice versa) on
      the sheets that have a Target-1? column;
    * with ``treatment`` given, Correctable=Y for a departure the treatment
      does not cover.

    Confirmations need the engineer's eye but are not necessarily wrong:
    Correctable=N for a departure the treatment DOES cover is legitimate
    only under a standing exemption (the SS-6002M dual-treatment undercount
    started as silent N calls, docs/03).
    """
    problems: list[str] = []
    confirmations: list[str] = []
    by_crash: dict[str, list[LedgerRow]] = {}
    for rows in ledger.values():
        for cid, lr in rows.items():
            by_crash.setdefault(cid, []).append(lr)

    for cid, entries in sorted(by_crash.items()):
        for attr, label in (("departure", "Departure"),
                            ("correctable", "Correctable?")):
            vals = {(getattr(e, attr) or "").strip() for e in entries}
            if len(vals - {""}) > 1:
                where = ", ".join(f"{e.sheet}={getattr(e, attr) or 'blank'}"
                                  for e in entries)
                problems.append(
                    f"Crash {cid}: {label} differs across sheets ({where})")
        for e in entries:
            if "target1" not in e.columns:
                continue
            if e.departure and not e.target1:
                problems.append(
                    f"Crash {cid}: departure {e.departure!r} on {e.sheet} "
                    "row "
                    f"{e.row} has no Target-1? flag")
            if e.target1 and not e.departure:
                problems.append(
                    f"Crash {cid}: Target-1? set on {e.sheet} row {e.row} "
                    "with no departure classification")
        if treatment:
            covers = TREATMENT_COVERS[treatment]
            over = [e for e in entries if e.departure and e.correctable
                    and e.correctable.upper() == "Y"
                    and e.departure not in covers]
            if over:
                sheets = ", ".join(e.sheet for e in over)
                problems.append(
                    f"Crash {cid}: Correctable=Y ({sheets}) but the "
                    f"{treatment} treatment does not cover "
                    f"{over[0].departure!r} departures (docs/03)")
            under = [e for e in entries if e.departure and e.correctable
                     and e.correctable.upper() == "N"
                     and e.departure in covers]
            if under:
                confirmations.append(
                    f"Crash {cid}: Correctable=N for a "
                    f"{under[0].departure!r} departure the {treatment} "
                    "treatment covers; confirm a standing exemption "
                    f"({', '.join(EXEMPTIONS)}) applies")
    return problems, confirmations


# --------------------------------------------------------------------------- #
# applying a call everywhere it appears
# --------------------------------------------------------------------------- #
@dataclass
class DepartureCall:
    """The engineer's classification for one crash (first harmful event)."""
    crash_id: str
    departure: str | None                 # Centerline / Right / None
    correctable: bool | None = None
    travel_dir: str | None = None
    comment: str | None = None
    exclude: bool = False                 # side-street run-through etc.


def apply_call(workbook_in: str, workbook_out: str, call: DepartureCall,
               ledger: dict[str, dict[str, LedgerRow]] | None = None) -> int:
    """Write one call to EVERY sheet the crash appears on, in one patch.

    Exclusion (side-street run-through) clears the Target flags, departure
    and correctability everywhere while keeping the crash row itself (it
    stays in Total Crashes as a non-target, docs/03) and requires a comment
    documenting the rationale.  Returns the number of sheets touched.
    """
    if call.exclude:
        if not (call.comment or "").strip():
            raise ValueError(
                "Excluding a crash from the lane departure target set "
                "requires the rationale in the comment field (docs/03)")
    elif call.departure not in (CENTERLINE, RIGHT):
        raise ValueError(
            f"Departure must be {CENTERLINE!r} or {RIGHT!r} "
            f"(got {call.departure!r}); use exclude=True to remove a crash "
            "from the target set")

    ledger = ledger if ledger is not None else read_ledger(workbook_in)
    edits: dict[str, list[CellEdit]] = {}
    touched = 0
    for sheet, rows in ledger.items():
        lr = rows.get(call.crash_id)
        if lr is None:
            continue
        touched += 1
        sheet_edits = edits.setdefault(sheet, [])

        def _set(role, value):
            col = lr.columns.get(role)
            if col:
                sheet_edits.append(CellEdit(f"{col}{lr.row}", value))

        if call.exclude:
            _set("departure", None)
            _set("correctable", None)
            _set("target1", None)
            _set("target2", None)
            _set("comment", call.comment)
        else:
            _set("departure", call.departure)
            if call.correctable is not None:
                _set("correctable", "Y" if call.correctable else "N")
            _set("target1", "Y")
            if call.travel_dir:
                _set("travel_dir", call.travel_dir)
            if call.comment is not None:
                _set("comment", call.comment)
    if touched == 0:
        raise KeyError(
            f"Crash {call.crash_id} appears on no ledger sheet of "
            f"{workbook_in}")
    xlsx_patch(workbook_in, workbook_out, edits)
    return touched


def tally(ledger: dict[str, dict[str, LedgerRow]],
          sheet: str) -> dict[str, int]:
    """Departure / correctable / target counts for one sheet's ledger."""
    rows = ledger.get(sheet, {})
    return {
        "crashes": len(rows),
        "centerline": sum(1 for r in rows.values()
                          if (r.departure or "") == CENTERLINE),
        "right": sum(1 for r in rows.values() if (r.departure or "") == RIGHT),
        "target1": sum(1 for r in rows.values()
                       if (r.target1 or "").upper() == "Y"),
        "correctable": sum(1 for r in rows.values()
                           if (r.correctable or "").upper() == "Y"),
    }
