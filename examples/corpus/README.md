# Completed-workbook corpus (Drive sweep)

`drive_manifest.tsv` is the inventory of the ~120 unique completed
evaluation workbooks in the engineer's Google Drive (file id, title),
deduplicated; lock files, blank templates, and reviewer copies are
excluded. Six exceed the Drive connector's 10 MB download limit and
cannot be pulled through it: SS-6002AS, the three SS-4902CX parts,
05-18-51357, and W-5706A (1 of 3).

`metrics.jsonl` is one line per scanned workbook from
`safety_eval.corpus_scan`: for every results-style sheet, the print
area, page margins, page scale, box-bottom border row, row heights,
and each long-text merged box with its geometry, chosen font size, and
the text_fit model's prediction beside it. The scan is the evidence
base for the formatting rules in `results_sheet.py`; rerun it as more
workbooks are pulled:

    python3 -m safety_eval.corpus_scan examples/corpus/metrics.jsonl <xlsx...>

Read so far (9 workbooks): the fit-first rules hold everywhere - text
is sized to the cell on the 0.5pt ladder, the cell grows by whole
15pt rows when text cannot fit at 9ish, heading and data row heights
are never altered. Looser than first thought: grown pages keep
0.25/0.5in margins as often as they take 0.1in; the chosen size sits
a half to a full step below the maximum fit in about half the cases;
and several completed workbooks retain the template's print area,
which stops one row above the report box's bottom border.
