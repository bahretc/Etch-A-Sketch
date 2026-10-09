#!/usr/bin/env node
// Crash pattern summary and HSIP warrant analysis memo for TEAAS study 41000079736 (docx-js).
// Reads review/collision_diagram_listing.csv for the crash table; figures from maps/ and review/fig/.
const fs = require("fs"), path = require("path");
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, AlignmentType, ImageRun,
        PageOrientation, LevelFormat, BorderStyle, ShadingType, Footer, PageNumber, VerticalAlign, PageBreak } = require("docx");
const HERE = __dirname;
const OUT = path.join(HERE, "41000079736_CrashPatternSummary.docx");
const FONT = "Calibri";

// ---------- helpers ----------
const run = (t, o = {}) => new TextRun({ text: t, font: FONT, size: o.size || 21, bold: o.bold, italics: o.italics, color: o.color });
const p = (t, o = {}) => new Paragraph({ children: Array.isArray(t) ? t : [run(t, o)], spacing: { after: o.after ?? 120, before: o.before ?? 0 },
                                          alignment: o.align, numbering: o.numbering, keepNext: o.keepNext });
const h1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 280, after: 120 }, keepNext: true,
                                children: [new TextRun({ text: t, font: FONT, size: 28, bold: true, color: "1F3864" })] });
const h2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 200, after: 80 }, keepNext: true,
                                children: [new TextRun({ text: t, font: FONT, size: 23, bold: true, color: "1F3864" })] });
const bullet = (parts, lvl = 0) => new Paragraph({ numbering: { reference: "bullets", level: lvl }, spacing: { after: 80 },
                                                   children: (Array.isArray(parts) ? parts : [parts]).map(x => typeof x === "string" ? run(x) : x) });
const num = parts => new Paragraph({ numbering: { reference: "numbers", level: 0 }, spacing: { after: 100 },
                                     children: (Array.isArray(parts) ? parts : [parts]).map(x => typeof x === "string" ? run(x) : x) });
const caption = t => new Paragraph({ spacing: { before: 60, after: 200 }, alignment: AlignmentType.CENTER, children: [run(t, { italics: true, size: 18 })] });
const b = t => run(t, { bold: true });
const border = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(headers, rows, widths, opts = {}) {
  const size = opts.size || 18, total = widths.reduce((a, c) => a + c, 0);
  const cell = (txt, w, hdr, i) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders, verticalAlign: VerticalAlign.CENTER,
    shading: hdr ? { fill: "D9E2F3", type: ShadingType.CLEAR, color: "auto" } : (opts.shade && opts.shade(txt, i) ? { fill: opts.shade(txt, i), type: ShadingType.CLEAR, color: "auto" } : undefined),
    margins: { top: 40, bottom: 40, left: 70, right: 70 },
    children: [new Paragraph({ alignment: (opts.align && opts.align[i]) || AlignmentType.LEFT, spacing: { after: 0 },
                               children: [new TextRun({ text: String(txt ?? ""), font: FONT, size, bold: hdr || (opts.boldCol === i) })] })] });
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, cantSplit: true, children: headers.map((h, i) => cell(h, widths[i], true, i)) }),
           ...rows.map(r => new TableRow({ cantSplit: true, children: r.map((v, i) => cell(v, widths[i], false, i)) }))] });
}
function image(file, widthIn, maxHeightIn) {
  const buf = fs.readFileSync(file); const sz = pngSize(buf);
  let w = widthIn * 96, h = w * sz.h / sz.w;
  if (maxHeightIn && h > maxHeightIn * 96) { h = maxHeightIn * 96; w = h * sz.w / sz.h; }
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 0 },
                         children: [new ImageRun({ type: "png", data: buf, transformation: { width: Math.round(w), height: Math.round(h) } })] });
}
function pngSize(buf) { return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) }; }
function csv(text) {   // minimal RFC-4180 reader
  const rows = [], re = /("([^"]|"")*"|[^,\r\n]*)(,|\r?\n|$)/g; let row = [], m;
  while ((m = re.exec(text)) !== null) { let v = m[1]; if (v.startsWith('"')) v = v.slice(1, -1).replace(/""/g, '"'); row.push(v);
    if (m[3] !== ",") { if (row.length > 1 || row[0] !== "") rows.push(row); row = []; } if (m.index === re.lastIndex) re.lastIndex++; if (m[3] === "") break; }
  return rows;
}
const listing = csv(fs.readFileSync(path.join(HERE, "review", "collision_diagram_listing.csv"), "utf8"));
const crashes = listing.slice(1).filter(r => r.length >= 9);

// ---------- content ----------
const front = [
  new Paragraph({ spacing: { after: 60 }, children: [run("Crash Pattern Summary and HSIP Warrant Analysis", { size: 36, bold: true, color: "1F3864" })] }),
  p("NC 180/NC 226 (S Post Rd) at SR 1103 (Pleasant Dr / Pleasant Hill Church Rd), Cleveland County, NCDOT Division 12", { size: 24, bold: true, after: 60 }),
  p("Order # 41000079736   |   PH/SS # TSUINT716412   |   TEAAS Intersection Analysis Report, 9/1/2016 to 8/31/2026 (10 years), Y-line 150 ft   |   35.246324, -81.509409", { size: 19, after: 60 }),
  p("Draft for the PE's review, prepared 10/9/2026 from the TEAAS Intersection Analysis Report (29 crashes after the fiche review), the collision diagram and the reviewed fiche workbooks. Crash numbers are the TEAAS report order, which the collision diagram also uses (Appendix A lists them).", { size: 19, italics: true, after: 200 }),

  h1("1. The site"),
  p("NC 180/NC 226 (S Post Rd) is a two-lane, two-way undivided NC route posted 45 mph (every NC 180 unit on the 29 reports is coded with a 45 mph limit). SR 1103 crosses it at an acute skew of about 49 degrees: Pleasant Dr arrives from the northwest and Pleasant Hill Church Rd leaves to the southeast. Both SR 1103 approaches are stop-controlled (stop sign is the traffic control coded on 25 of the 29 reports; the other four code the double yellow centerline). The intersection is NC 180 milepost 4.601 and SR 1103 milepost 3.644 on the TEAAS features inventory. As labelled on the collision diagram, the M&D Quick Stop and a Dollar General sit on the west side of NC 180 on either side of Pleasant Dr; the east side is undeveloped land and an empty lot. Eight of the nine dark crashes are coded dark, roadway not lighted."),
  p("Traffic. Entering AADT uses each NCDOT count station's value for the middle year of the study period (2021), estimating the one missing year by straight-line interpolation (Table 1). The sum of the four legs divided by two is 12,050, rounded to 12,100 vehicles per day (TEAAS Chapter 8). The TEAAS run used 12,300, within 5 percent, so the TEAAS exposure statistics are reported as run. The two SR 1103 legs carry about 11 percent of the entering traffic."),
  table(["Leg", "NCDOT station", "2021 AADT", "Basis"],
        [["NC 180/NC 226 north", "0230000187", "11,000", "2021 count"],
         ["NC 180/NC 226 south", "0230000152", "10,500", "2021 count"],
         ["SR 1103 (Pleasant Dr) northwest", "0230000045", "1,400 (estimate)", "interpolated between the 2018 (1,600) and 2022 (1,300) counts, rounded to the nearest 100"],
         ["SR 1103 (Pleasant Hill Church Rd) southeast", "0230000531", "1,200", "2021 count"],
         ["Entering AADT", "", "12,100", "(11,000 + 10,500 + 1,400 + 1,200) / 2 = 12,050, rounded to the nearest hundred"]],
        [3000, 1500, 1500, 3360], { boldCol: 0 }),
  caption("Table 1. Middle-year (2021) AADT by leg (NCDOT Traffic Survey Group stations; 41000079736_AADT.xlsx and the ADT map)."),
  image(path.join(HERE, "maps", "41000079736_AreaMap.png"), 6.5, 5.2),
  caption("Figure 1. The study intersection (Esri World Imagery); Y-line 150 ft."),

  h1("2. Crash history and TEAAS statistics"),
  p("Ten years, 9/1/2016 to 8/31/2026, 29 crashes within the 150 ft Y-line after the fiche review (27 from the initial TEAAS pull, 2 added, 7 deleted; section 3j). No fatal crashes; 2 Class A, 4 Class B and 3 Class C injury crashes (18 injuries: 2 A, 6 B, 10 C) and 20 property damage only. Nine crashes at night (31 percent), four on a wet road (14 percent), none with alcohol or drugs suspected. Estimated property damage $182,400."),
  p("Exposure 44.92 million entering vehicles (MEV) at the TEAAS ADT of 12,300. Total crash rate 64.56 per 100 MEV; non-fatal injury 20.04; night 20.04; wet 8.90; EPDO rate 517.37. Severity index 8.01 and EPDO index 232.40 (76.8 for K/A, 8.4 for B/C). At the 12,100 middle-year entering AADT the exposure is 44.17 MEV and the total rate 65.66 per 100 MEV."),
  table(["Crash type (TEAAS)", "Crashes", "Percent", "Injury crashes (A / B / C)"],
        [["Angle", "8", "27.6", "5 (1 / 2 / 2)"],
         ["Left turn, different roadways", "9", "31.0", "2 (0 / 1 / 1)"],
         ["Left turn, same roadway", "2", "6.9", "1 (1 / 0 / 0)"],
         ["Right turn, different roadways", "2", "6.9", "1 (0 / 1 / 0)"],
         ["Right turn, same roadway", "1", "3.4", "0"],
         ["Frontal impact subtotal", "22", "75.9", "9 (2 / 4 / 3)"],
         ["Rear end, slow or stop", "5", "17.2", "0"],
         ["Fixed object (run off road)", "2", "6.9", "0"],
         ["Total", "29", "100.0", "9 (2 / 4 / 3)"]],
        [3400, 1200, 1200, 3560], { align: [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER],
          shade: (t, i) => ["Frontal impact subtotal", "Total"].includes(t) && i === 0 ? "F2F2F2" : undefined }),
  caption("Table 2. Crashes by type. Frontal impact = angle, left turn and right turn (same or different roads) and head on, per the HSIP warrant definition."),
  table(["Study year (Sep to Aug)", "Crashes", "Frontal", "Injury", "Crash numbers"],
        [["2016-17", "2", "1", "0", "1, 2"], ["2017-18", "0", "0", "0", ""], ["2018-19", "0", "0", "0", ""], ["2019-20", "2", "2", "1", "3, 4"],
         ["2020-21", "3", "3", "1", "5, 6, 7"], ["2021-22", "5", "2", "0", "8 to 12"], ["2022-23", "4", "3", "1", "13 to 16"],
         ["2023-24", "3", "2", "1", "17, 18, 19"], ["2024-25", "4", "3", "2", "20 to 23"], ["2025-26", "6", "6", "3", "24 to 29"],
         ["Total", "29", "22", "9", ""]],
        [2400, 1200, 1200, 1200, 3360], { align: [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.LEFT],
          shade: (t, i) => t === "Total" && i === 0 ? "F2F2F2" : undefined }),
  caption("Table 3. Crashes by study year. First five years 7 crashes (6 frontal, 2 injury); last five years 22 (16 frontal, 7 injury); last three years 13 (11 frontal, 6 injury); last year 6."),

  h1("3. Crash patterns"),
  bullet([b("a. Frontal-impact crossing and turning crashes dominate. "), "22 of the 29 crashes (76 percent) are angle, left-turn or right-turn collisions at the intersection, and every one of the nine injury crashes is in this group. Angle crashes are the most severe type: 5 of the 8 produced injuries (crash 23 Class A, 5 and 29 Class B, 22 and 25 Class C)."]),
  bullet([b("b. SR 1103 drivers entering or crossing NC 180 account for 17 of the 22 frontal crashes. "), "In 15 the SR 1103 driver failed to yield the right of way, in one (26) the driver disregarded the stop sign, and in one (1) the contributing circumstance is inattention. Eight were crossing straight through (angle crashes 1, 5, 22, 23, 25, 26, 28, 29), six were turning left onto NC 180 (6, 9, 10, 16, 21 and 27, where the left-turning Pleasant Dr driver met a right-turning Pleasant Hill Church Rd driver), three were turning right (4, 7, 17). The NC 180 through vehicles struck were travelling 30 to 55 mph at impact; 11 were southbound and 5 northbound."]),
  bullet([b("c. The Pleasant Dr (northwest) approach is the problem leg. "), "13 of the 17 minor-street crashes came from Pleasant Dr (1, 4, 6, 7, 9, 10, 21, 22, 23, 25, 27, 28, 29) and 4 from Pleasant Hill Church Rd (5, 16, 17, 26). Nine of the twelve NC 180 vehicles struck by Pleasant Dr drivers were southbound. With the 49 degree skew, a driver stopped on Pleasant Dr has southbound traffic approaching from well behind the left shoulder, about 130 degrees from straight ahead, while northbound traffic is seen at 50 degrees to the right. The pattern is consistent with a sight-line and head-turn problem for southbound traffic on that approach; the Dollar General and M&D Quick Stop driveways sit on the same side. Both need checking in the field."]),
  bullet([b("d. NC 180 left turns onto SR 1103: 5 crashes (3, 13, 14, 19, 24), 3 with injuries. "), "NC 180 is two lanes with no left-turn lanes, so a driver waiting to turn left onto SR 1103 stops in the through lane. Crashes 3, 13 and 14 are left-turners struck by opposing through traffic (14 at 55 mph); 19 (Class C) involved a southbound left-turner with both a following southbound vehicle and an opposing northbound vehicle; 24 (Class A, dark) was a northbound left-turner against a southbound moped that was itself turning left. The rear-end crash 15, a northbound vehicle stopped in the lane, fits the same exposure."]),
  bullet([b("e. Rear ends: 5 crashes, all property damage only. "), "Four are on the SR 1103 approaches behind a vehicle stopped at the stop sign (2 and 18 on Pleasant Dr, 8 and 20 on Pleasant Hill Church Rd); one (15) is on NC 180 northbound. Two of the four minor-street rear ends (8, 20) are the crashes the fiche review added or confirmed on the Pleasant Hill Church Rd approach."]),
  bullet([b("f. Run-off-road: 2 crashes (11, 12), not a pattern. "), "Both single-vehicle, at night on a dry road, property damage only: a northbound driver turning right at 45 mph (inattention) into the ditch, and a southbound driver who overcorrected into the ditch and embankment."]),
  bullet([b("g. Time of day. "), "14 of the 29 crashes (48 percent) occurred between 3:00 and 5:59 PM (7 in the 5:00 PM hour alone), 4 between 7:00 and 8:59 AM and 4 between 9:00 and 10:59 PM. Nine crashes were at night (31 percent): 7 frontal (1, 4, 6, 14, 21, 24, 26) and the 2 run-off-road crashes. Only crash 1 codes a lighted roadway. Tuesday (9) and Monday (6) are the most frequent days; December (6) the most frequent month."]),
  bullet([b("h. Weather and surface. "), "25 crashes on a dry road, 4 wet (9, 16, 19, 21, all left turn, different roadways). The wet rate of 8.90 per 100 MEV and the 14 percent wet share do not indicate a wet-pavement problem."]),
  bullet([b("i. Trend: frequency and severity are rising while traffic is flat. "), "7 crashes in the first five years against 22 in the last five; 13 (45 percent) in the last three years and 6 in the last year. Seven of the nine injury crashes occurred since September 2021 and six of them in the last three years, including both Class A crashes (23 on 5/19/2025, 24 on 12/16/2025) and the three injury crashes of the 2025-26 study year. NC 180 counts have stayed between 10,500 and 12,000 vehicles per day since 2016, so the increase is not volume-driven."]),
  bullet([b("j. Fiche review. "), "Two crashes were added after the DMV-349s were read: 106808749 (12/17/2021, rear end on the Pleasant Hill Church Rd approach, referenced to SR 1103 MP 3.019) and 107960640 (12/15/2024, left turn at the study intersection, not mileposted). Seven were deleted: three animal crashes (105334401, 106653569, 107468199), two fixed-object crashes (106482677; 108204170 at the Dollar General driveway), one opposite-direction sideswipe (106251888) and one left-turn crash referenced just beyond 150 ft (107921860). All seven are property damage only. Adding any of them back lowers the frontal share and the severity index without changing the warrant result (section 4)."]),

  h1("4. HSIP warrant analysis"),
  p("TEAAS classes the location as rural, so the ten-year rural intersection warrants of the NCDOT Highway Safety Improvement Program apply (2024 HSIP Overview, Safety Warrants; the criteria are unchanged in the current cycle). The criteria are applied to the 29 crashes of the study window 9/1/2016 to 8/31/2026. A frontal impact crash is an angle, left-turn, right-turn or head-on crash."),
  table(["Warrant", "Criteria (rural, 10 years)", "This location", "Result"],
        [["I-1r Frontal Impact Rural", "At least 9 frontal impact crashes, AND at least 60% of all crashes frontal impact, AND at least 20% of all crashes in the last 3 years", "22 frontal impact crashes; 75.9% of 29; 13 of 29 (44.8%) in 9/2023 to 8/2026", "MET"],
         ["I-2r Last Year Increase Rural", "At least 20 total crashes AND at least 32% of them in the last year", "29 crashes; 6 (20.7%) in 9/2025 to 8/2026", "Not met"],
         ["I-3r Frequency with Severity Index Minimum Rural", "At least 20 total crashes AND severity index at least 9.0 AND at least 30% of crashes in the last 3 years", "29 crashes; severity index 8.01; 44.8% in the last 3 years", "Not met (severity index)"],
         ["I-3 Fatal and Severe Injury (urban and rural)", "At least 3 fatal or A injury frontal impact crashes in the last 5 years", "2 in 9/2021 to 8/2026: 108120512 (angle, 5/19/2025) and 108353439 (left turn, 12/16/2025)", "Not met"],
         ["I-4r Night Location Rural", "At least 10 night crashes AND at least 46% of crashes at night AND at least 20% of crashes in the last 3 years", "9 night crashes (31.0%); 44.8% in the last 3 years", "Not met"]],
        [2000, 3000, 3000, 1360], { boldCol: 3, shade: (t, i) => i === 3 ? (t === "MET" ? "C6EFCE" : "F2F2F2") : undefined }),
  caption("Table 4. NCDOT HSIP rural intersection warrants applied to the 29-crash, 10-year study."),
  p([b("Result. "), run("The location meets Warrant I-1r, Frontal Impact Rural: 22 frontal impact crashes, 76 percent of all crashes, with 45 percent of the crashes in the last three years. The identified pattern is minor-street vehicles from SR 1103, chiefly the Pleasant Dr approach, failing to yield to NC 180 through traffic, with a secondary pattern of NC 180 left-turn crashes.")]),
  p([b("Margins on the other warrants. "), run("I-3 is one crash short: a third fatal or A injury frontal impact crash in the five-year window would satisfy it, and both A crashes to date occurred in 2025. I-3r is short only on the severity index (8.01 against 9.0); one more A injury crash would lift the index above 10. I-2r would need 10 crashes in a single study year (the last year had 6). I-4r would need 14 of 29 crashes at night (9 recorded).")]),
  p([b("Sensitivity to the fiche review. "), run("With all seven deleted crashes added back (36 crashes) the frontal share is 64 percent and the severity index 6.65; with only the two fixed-object crashes added back (31 crashes) 71 percent and 7.56; with the six non-frontal deletions added back (35 crashes) 63 percent and 6.81. I-1r is met in every case and no other warrant changes (warrants.py, review/warrant_check_10yr.txt).")]),
  p([b("Five-year check. "), run("For reference, the five-year window 9/2021 to 8/2026 (22 crashes, 16 frontal, 73 percent, 10 of 22 in the last two years) would also satisfy the urban frontal impact warrant I-1u(a) if the location were treated as urban.")]),

  h1("5. Findings"),
  num("The intersection has a clear, worsening frontal-impact pattern that meets HSIP Warrant I-1r. Three quarters of the crashes and all nine injury crashes are crossing or turning collisions at the stop-controlled SR 1103 approaches and at NC 180 left turns."),
  num("The dominant conflict is a Pleasant Dr driver entering or crossing NC 180 in front of a through vehicle, most often southbound: 13 of the 17 minor-street crashes came from that approach. The 49 degree skew places southbound traffic far behind the stopped driver's left shoulder. Sight distance, the skew and the adjacent commercial driveways are the field questions that decide the countermeasure."),
  num("NC 180 left turns onto SR 1103 are a second, severe pattern (5 crashes, 3 with injuries, one Class A) on a two-lane road without turn lanes."),
  num("Severity is concentrated in the last two years: both Class A crashes and 5 of the 9 injury crashes since March 2025. The location is one K or A frontal crash short of Warrant I-3 and one severe crash short of the I-3r severity index."),
  num("Night (31 percent) and wet (14 percent) shares are not patterns in themselves, but 7 of the 9 night crashes are frontal impacts at an unlit intersection, so lighting belongs in the countermeasure discussion."),

  h1("6. Field investigation: what to verify on site"),
  bullet("Intersection sight distance from both SR 1103 stop lines, each direction, measured against the 45 mph requirement; the skew angle; sight obstructions (signs, utility poles, vegetation, parked vehicles and merchandise at the Dollar General and M&D Quick Stop)."),
  bullet("Stop control: STOP sign size, condition and retroreflectivity, STOP AHEAD signing, stop bar and centerline condition on both SR 1103 approaches; whether a CROSS TRAFFIC DOES NOT STOP plaque is posted; approach grades."),
  bullet("NC 180 approaches: intersection warning signs (W2-1 or W2-2 with street name plaques), advance distance, lane and shoulder widths, pavement markings, presence or absence of left-turn or bypass lanes, passing-zone striping through the intersection (four reports code the double yellow line as the control)."),
  bullet("Posted speed limits in both directions on NC 180 and on SR 1103 (the reports code 45 mph on NC 180; SR 1103 units are mostly coded 45 but three are coded 35)."),
  bullet("Lighting: confirm none is present; location of the existing light at the convenience store (crash 1 is coded dark, lighted)."),
  bullet("Driveways: number, width and throat of the Dollar General and M&D Quick Stop driveways and their distance to the SR 1103 stop lines; the fixed-object crash 108204170 was deleted as a driveway (PVA) crash."),
  bullet("Spot speeds on NC 180 (impact speeds of 45 to 55 mph appear on the reports) and a count of the SR 1103 approach volumes and turning movements during the 3:00 to 6:00 PM peak, when half the crashes occurred."),
  bullet("Evidence of the pattern still visible: tire marks and debris in the southwest and northeast quadrants, damaged signs or poles."),

  h1("7. Candidate countermeasures for the PE's consideration"),
  p("The site findings decide which of these apply; they are listed from low cost to capital.", { italics: true }),
  bullet("Stop-approach conspicuity on SR 1103: oversize STOP signs with retroreflective post strips or flashing LED borders, STOP AHEAD signs, CROSS TRAFFIC DOES NOT STOP plaques, refreshed stop bars, and transverse rumble strips on the Pleasant Dr approach."),
  bullet("Advance intersection warning on NC 180 in both directions with street-name plaques, and an intersection conflict warning system (vehicle-entering flashers on NC 180 actuated from the SR 1103 approaches) if the sight-distance review supports it."),
  bullet("Sight-line clearing and driveway management at the Dollar General and M&D Quick Stop frontages on Pleasant Dr."),
  bullet("Intersection lighting, given 7 frontal crashes in the dark at an unlit location."),
  bullet("Left-turn treatment on NC 180: left-turn lanes or right-side bypass lanes for the 5 left-turn and 1 rear-end crashes involving vehicles waiting to turn onto SR 1103."),
  bullet("Geometric correction of the skew: realigning the Pleasant Dr approach toward 90 degrees or offsetting the two SR 1103 legs, which also removes the Pleasant Dr to Pleasant Hill Church Rd through movement (8 angle crashes)."),
  bullet("Access-management alternatives if frequency keeps rising: a reduced-conflict (J-turn) configuration on NC 180, or an all-way stop or signal study. Minor-street volumes of 1,200 to 1,400 vehicles per day are unlikely to satisfy volume warrants, but the 6 crashes of the last study year, 5 of them frontal, are worth a check against the MUTCD crash-experience signal warrant during the field investigation."),

  h1("8. Record"),
  bullet("TEAAS: data/41000079736_CrashAnalysis10yr.pdf (Intersection Analysis Report, 29 crashes), data/41000079736_CrashAnalysis10yr_29crashes.csv, Features Reports for NC 180 and SR 1103."),
  bullet("Fiche: 41000079736_Fiche10yr.xlsx (both reviewed fiche workbooks combined in the package layout, reviewer's comments kept); fiche_review.py and review/ for the screening."),
  bullet("Collision diagram: data/41000079736_CollisionDiagram_VHB.pdf (MicroStation sheet with the AADT and speed labels) and maps/41000079736_CollisionDiagram_labeled.pdf (the same sheet enlarged, Appendix B); review/collision_diagram_listing.csv (Appendix A)."),
  bullet("AADT: 41000079736_AADT.xlsx, 41000079736_CalculatedAADT.xls, aadt.json, maps/41000079736_ADTMap.pdf."),
  bullet("Maps: maps/41000079736_LocationMap.pdf, 41000079736_AreaMap.pdf, 41000079736_ADTMap.pdf."),
  bullet("Warrants: warrants.py and review/warrant_check_10yr.txt (scenarios A to D); criteria from the NCDOT 2024 HSIP Overview, Safety Warrants."),
];

// ---------- appendices (landscape) ----------
const sevName = { PDO: "O", A: "A", B: "B", C: "C" };
const appA = [
  h1("Appendix A. The 29 crashes (TEAAS report order)"),
  table(["No", "Crash ID", "Date", "Time", "Type", "Sev", "Light", "Road", "Units (direction / maneuver / impact speed / contributing circumstance)", "Frontal"],
        crashes.map(r => [r[0], r[1], r[2], r[3], r[4], sevName[r[5]] || r[5], r[6], r[7], r[8], r[9] === "yes" ? "yes" : ""]),
        [450, 1050, 1000, 650, 2250, 500, 1350, 650, 5230, 550],
        { size: 16, align: [AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.CENTER],
          shade: (t, i) => (i === 5 && ["A", "B", "C"].includes(t)) ? "FCE4D6" : undefined }),
  caption("Severity O = property damage only. Frontal = angle, left-turn and right-turn crashes counted by the HSIP frontal impact warrant. Source: TEAAS collision diagram export (data/41000079736_CollisionDiagramData.csv)."),
];
const appB = [
  h1("Appendix B. Collision diagram"),
  image(path.join(HERE, "review", "fig", "collision_diagram_labeled.png"), 9.5, 6.2),
  caption("Figure 2. Collision diagram, 9/1/2016 to 8/31/2026 (MicroStation sheet, enlarged; maps/41000079736_CollisionDiagram_labeled.pdf). Numbers are the TEAAS report order of Appendix A."),
];

const footer = new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
  new TextRun({ text: "41000079736  |  Crash pattern summary and HSIP warrant analysis  |  Draft 10/9/2026  |  Page ", font: FONT, size: 16, color: "595959" }),
  new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "595959" }),
  new TextRun({ text: " of ", font: FONT, size: 16, color: "595959" }),
  new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: "595959" })] })] });
const portrait = { page: { size: { width: 12240, height: 15840 }, margin: { top: 1080, bottom: 1080, left: 1440, right: 1440 } } };
const landscape = { page: { size: { width: 12240, height: 15840, orientation: PageOrientation.LANDSCAPE }, margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 } } };

const doc = new Document({
  creator: "VHB", title: "Crash Pattern Summary and HSIP Warrant Analysis, 41000079736",
  styles: { default: { document: { run: { font: FONT, size: 21 } } } },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] }] },
  sections: [
    { properties: portrait, footers: { default: footer }, children: front },
    { properties: landscape, footers: { default: footer }, children: appA },
    { properties: landscape, footers: { default: footer }, children: appB },
  ],
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, buf.length, "bytes;", crashes.length, "crashes in Appendix A"); });
