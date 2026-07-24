# Deliverable workbook download coverage

Downloads from the Drive archive folders into the benchmark working set,
via the Google Drive connector. **The connector has a hard response-size
ceiling of ~6.29 MB per file** (base64 payload capped at 8 MiB): every
file at or below 6,267,106 bytes transferred and CRC-verified; every file
at or above 6,528,858 bytes failed deterministically with "session
expired" (or "over limit of 10 MB") on every attempt, while metadata
calls for the same files kept succeeding. Direct drive.google.com
download is blocked by the session egress policy, and the connector has
no chunked/ranged download, so files over ~6.29 MB cannot be fetched at
all in this environment.

## Archive total: 97 evaluations

- Original batch: 60 evaluations (30 train / 30 verify).
- 2023-contract batch (Assignments folder): 37 evaluations, ingested with
  the frozen-split rule (existing 60 assignments unchanged); overall
  split now 49 train / 48 verify.

## Extracted for the benchmark: 78 of 97

Evaluations whose delivered Evaluation Workbook was fetchable and yielded
authored results text: **train 37/49, verify 41/48.**

### Missing (19) - blocked by the ~6.29 MB cap unless re-provided

Train (12): 41000073096, 41000073175, 41000073211, 41000073289,
41000073356, 41000073362, 41000075670, 41000075960, 41000076139,
41000077041, 41000078043, 41000074884.

Verify (7): 41000069548, 41000069671, 41000073073, 41000073212,
41000073226, 41000073368, 41000073407.

Notes on specific cases:

- **41000073368** (verify): the real workbook is 15.8 MB; only a blank
  `2023-12-04` template copy sitting in a Background subfolder was under
  the cap. Blank templates are excluded from extraction (they have no
  authored content), so this WO is counted missing, not scored on empty
  text.
- **41000073401**: main Section workbook is 41.5 MB; smaller sibling
  intersection parts are present but are separate sub-studies, so the WO
  is treated as covered by its intersection parts.
- **41000076139 / 41000073336**: folder titles disagree with the workbook
  filenames (project-code typos). 73336's workbook (5.5 MB) was recovered
  once reclassified; 76139's is 7.2 MB and over the cap. Both carry the
  `folder-project-mismatch` manifest flag for the engineer to confirm.
- **41000075960**: carries a neighbour's 13-18-210 workbook (14.97 MB)
  alongside its own; the stray is quarantined (`stray-workbook` flag) and
  its own 10-19-230 workbook is 6.8 MB, over the cap.
- **41000073407** (verify): only a fiche-report `.xlsm` came through; the
  Section workbook was over the cap.

## To recover the missing 19

Re-provide each blocking workbook in a form under ~6 MB (save a copy with
imagery compressed, or split into `(1 of N)` part files as several
evaluations already are). Do NOT resave the originals in place (docs/06);
add reduced copies alongside them. The benchmark runs on whatever
coverage exists, so this is optional - it changes the held-out verify
pool from 41 toward 48.
