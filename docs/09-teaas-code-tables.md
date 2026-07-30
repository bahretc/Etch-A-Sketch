# 09 - TEAAS Code Tables

## Crash type (T) codes

Observed lookup (codes 6-12 not present in the observed table):

0 unknown, 1 ROR-R, 2 ROR-L, 3 ROR-T, 4 jackknife, 5 overturn, 13 other, 14 pedestrian, 15 cyclist, 16 RR (railroad), 17 animal, 18 MO (movable object), 19 FO (fixed object), 20 PMV (parked motor vehicle), 21 RE (rear end), 22 RE-T (rear end, turning), 23 LTSR, 24 LTDR, 25 RTSR, 26 RTDR, 27 head-on, 28 SSSD, 29 SSOD (sideswipe opposite direction), 30 angle, 31 backing, 32 other.

Frontal impact set: 23, 24, 25, 26, 27, 30.

## Route code prefixes (Road Code field)

First digit(s) of the 8-digit road code indicate route class: 1 interstate, 2 US routes (20000064 = US 64; variants observed: 21000064 US 64ALT, 22000064 US 64BYP, 29000064 US 64BUS, 206xxxxx couplets), 3 NC routes (30000049 = NC 49), 4 secondary routes (40001156 = SR 1156), 5 local/municipal streets and named roads (50008504 = DIXIE).

## Fiche field conventions

- MP 999.999: crash not mileposted; located by address or PVA driveway reference in the On Road field ("*LCL {address}", "PVA {address}").
- MA column: mileposted-accident flag (Y when the crash is mileposted on the study route).
- Y-Line: the intersection influence distance of the fiche pull, typically 150 ft.
- Severity S codes: K, A, B, C, O (PDO); blank sometimes appears and must be resolved from the report.
- Dir notation in review sheets: movement pair vehicle 1 / vehicle 2 (NBL/EBT = northbound left vs eastbound through).

## Import file formats

Milepost import (`Before_Import.txt`, `After_Import.txt`), one line per crash:

    <crash id>|<TAB><milepost to 3 dp><CR><LF>

CRLF after every line including the last. Verified byte for byte against both
files in examples/04-15-39049, which hold exactly the crashes on that
evaluation's Before and After sheets at their Final MP: the reviewer's New MP
where an RE was recorded, otherwise the coded fiche milepost. Rows are ordered
by crash date, which the sheets and the TEAAS ID exports are not; the order has
no effect on the import but matching it keeps generated files diffable against
real ones. Written by `safety_eval.teaas.write_period_imports`.

Feature-inclusion import is understood to be `<text>|<milepost>`, CRLF, with the
feature text capped at 20 characters and rejected rather than truncated beyond
it. This one is **not verified** against a real file; there is no example in the
archive. Check it against a live import before relying on it.

The 5-column Crash ID List (`Before_ID.txt`, `After_ID.txt`) is a TEAAS export,
not an import, and is read rather than written.
