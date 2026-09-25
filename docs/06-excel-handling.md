# 06 - Excel File Handling (MANDATORY)

The deliverable workbooks are NCDOT templates containing embedded drawings, images, charts, merged cells, and defined styles. Corrupting them is a delivery failure. These rules exist because openpyxl load/save strips or damages DrawingML content.

## The standing rule

1. **openpyxl is read-only** for templated workbooks: `load_workbook(path, data_only=True)` for values, `data_only=False` for formulas. Never `wb.save()` over a template that has drawings, images, or charts.
2. **Writes happen by direct XML manipulation inside the zip**, on a copy of the pristine original:
   - Copy the original file; never touch the source.
   - Open with `zipfile`, edit only the parts you must (`xl/worksheets/sheetN.xml`, `xl/sharedStrings.xml`), rewrite the archive preserving every other member byte-for-byte, including `xl/drawings/*`, `xl/media/*`, `xl/charts/*`, content types, and rels.
   - Respect sharedStrings: adding text means either appending shared strings and updating counts or using inline strings consistently.
3. **One LibreOffice headless recalc pass at the end** so formula caches match the edited values (`soffice --headless --calc --convert-to xlsx` round-trip, or an equivalent recalc script). One pass only; repeated round-trips invite drift.
4. **Verify after recalc**: extract and hash `xl/drawings/*` and `xl/media/*` from original and output; they must be byte-identical. Diff the sheet count, defined names, and image counts. On SS-6002M this check was the acceptance gate: all 15 sheets, 8 drawings, 6 media images byte-identical.
5. **Drop `xl/calcChain.xml`** (with its `[Content_Types].xml` override and workbook relationship) from every patched package. The chain is Excel's cached calculation order for every formula cell, with markers for array formulas and threads. Writing a value over a chained cell leaves it stale, and Excel then repairs the file on open ("Removed Records: Formula from /xl/calcChain.xml part"). A chain rebuilt from the sheets is repaired just the same, because the markers cannot be reproduced without Excel's dependency engine (05-20-62123, 2026-09). Excel rebuilds the chain silently when the part is absent; `fullCalcOnLoad` on `calcPr` recomputes every cell. `xlsx_patch` and `replace_sheet_rows` do this, and `verify_integrity` allows only that member to go missing.
6. **Template sheets stay as NCDOT delivered them** (VHB QC, Assignment 37, 2026-09: "use their default trends tab ... I do not want us to make too many changes to the workbook unless they are needed to fix fundamental errors. Each evaluation we complete should start from scratch from their provided template workbook"). The prototype's Trends and One Pager formulas and several defined names point at copies of the workbook in a Downloads folder, so their numbers are another project's; report that to the engineer as prototype feedback rather than fixing it. `drop_external_links` (re-homes `[n]Sheet!` references to the workbook's own sheets and removes the link parts; `verify_integrity(allow_removed=...)` names them) and `safety_eval.trends_sheet` exist for when the reviewer asks for the fix; they are not part of the default fill.
7. **Where LibreOffice and Excel differ, the recalc keeps the file honest.** Cells calling Excel-only functions (XLOOKUP, REGEXEXTRACT and the rest of `EXCEL_ONLY_FUNCTIONS`), and every cell that reads one, keep the cache Excel stored; LibreOffice 24.2 answers #NAME? or an IFERROR fallback there. LibreOffice also trims a trailing blank cell out of a COUNTIFS range, so a blank severity on the last Before/After row (which the template counts as O) was dropped from the O count; `recalc(assume=...)` computes the caches as if such cells held the value the template treats them as, while the file keeps its blank. After the recalc, check the key counts against an independent count before delivering (the 05-20-62123 fill does).
8. **A deliberate text fix in a drawing is named, never silent.** When a drawing's text is wrong (a map block leg label), only its `<a:t>` runs change, the edit proves nothing else in the part moved, and `verify_integrity(allow_modified=...)` names that one part; every other drawing and all media stay byte-identical.

## When openpyxl writing is acceptable

- Building a new workbook from scratch (no template).
- Templates verified to contain no drawings/charts/images.
- Even then, run the recalc pass if the file contains formulas whose cached values you changed.

## Images in workbooks (field investigation Photos/Sketch sheets)

- Placement uses TwoCellAnchor at the XML level for reliable sizing/centering; openpyxl's image handling loses anchors on resave.
- Photos: enlarged, centered in their block, thin black border, centered captions, and confirm print layout (page setup, print areas) survives.
- Clearing template photo blocks: null the caption and header cells without touching merged-cell definitions.

## Preserving formula semantics

- Farmville trip generation precedent: ITE 11th edition rate formulas were preserved only because edits were XML-level; a resave would have flattened them.
- Generated analysis sheets must contain the formulas themselves (COUNTIFS, date math, buffer references), not computed constants.

## Word documents (assumptions emails)

- Generated .docx must pass schema validation before delivery.
- Known bug when generating with docx-js and yellow highlighting: it emits `<w:highlightCs w:val="yellow"/>` elements that fail validation. Fix: unpack the docx, `sed` those elements out of `word/document.xml`, repack against the original. Bake this into the generator rather than rediscovering it.
- Regenerating from a prior email as a format reference means matching its structure exactly, bullet for bullet.

## Practical helpers to build in src/

- `xlsx_patch(path_in, path_out, edits)`: dict of sheet -> {cell: value} applied via XML with sharedStrings management.
- `recalc(path)`: wraps the LibreOffice headless pass with a timeout and temp profile.
- `verify_integrity(original, output)`: drawings/media hash comparison + sheet/name/image inventory diff. Fail loudly.
