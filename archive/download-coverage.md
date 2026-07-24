# Deliverable workbook download coverage (2026-07-24)

Downloads from the Drive archive folder into the benchmark working set,
via the Google Drive connector. **The connector has a hard response-size
ceiling of ~6.29 MB per file** (base64 payload capped at 8 MiB): every
file at or below 6,267,106 bytes transferred and CRC-verified; every file
at or above 6,528,858 bytes failed deterministically with "session
expired" on every attempt across six independent download agents, while
metadata calls for the same files kept succeeding. Direct
drive.google.com download is blocked by the session egress policy, and
the connector has no chunked/ranged download, so files over ~6.29 MB
cannot be fetched at all in this environment.

## Result

59 files on disk, zip-CRC-verified, byte-sizes matching Drive exactly.
Evaluations with their delivered Evaluation Workbook available:
**train 23/30, verify 25/30** (48 of the 60 archived evaluations).

## Evaluations with no usable workbook (12)

| WO | Split | Blocking file(s) | Size |
|----|-------|------------------|------|
| 41000069548 | verify | Intersection Evaluation Workbook - 05-14-7978.xlsx | 6.81 MB |
| 41000069671 | verify | Section Evaluation Workbook - 12-17-217.xlsx | 7.53 MB |
| 41000073073 | verify | Intersection Evaluation Workbook - 12-17-220 (SS-4912CL).xlsx | 7.36 MB |
| 41000073212 | verify | (workbook over 10 MB, excluded before download) | >10 MB |
| 41000073407 | verify | Section evaluation workbook (only the fiche .xlsm came through) | 7.04 MB |
| 41000073096 | train | Intersection Evaluation Workbook - 02-17-46265 (SS-4902CT).xlsx | 6.71 MB |
| 41000073175 | train | Intersection Evaluation Workbook - 04-17-49450 (SS-4904EK).xlsx | 7.04 MB |
| 41000073211 | train | Intersection Evaluation Workbook - 02-15-37560 (SS-4902CW).xlsx | 8.18 MB |
| 41000073289 | train | Section Evaluation Workbook - 06-18-51382 (SS-4906DT).xlsx | 7.01 MB |
| 41000073362 | train | Intersection evaluation workbook | 9.69 MB |
| 41000075670 | train | Intersection Evaluation Workbook - 06-20-61888 (SS-6006AL).xlsx | 7.08 MB |
| 41000078043 | train | (workbook over 10 MB, excluded before download) | >10 MB |

Partial-coverage notes:

- 41000075534 (train, 10-part workbook): only part 9 of 10 (6.27 MB) fit
  under the ceiling; parts 1-8 and 10 (6.53-7.16 MB) all failed. Part 9
  is used as the evaluation's primary workbook.
- 41000069735 (verify): the Section workbook parts (7.6/8.3 MB) failed,
  but the Ames and Pearl Intersection workbooks came through; the Ames
  workbook (4.4 MB) is the primary.

## To recover the missing 12

Re-provide each blocking workbook in a form under ~6 MB, e.g. save a copy
with imagery compressed, or split it into "(1 of N)" part files the way
02-18-52752 and 06-13-26850 already are. Do NOT resave the originals in
place (docs/06); add reduced copies alongside them. The benchmark
runs on whatever coverage exists, so this is optional: it changes the
verify denominator from 25 to 30.
