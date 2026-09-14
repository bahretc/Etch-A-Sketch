# 05 - Report Writing

## Style rules (apply to all generated text: report cells, memos, emails)

- Plain, peer-to-peer, understated. No LLM phrasing, no flourishes, no wordplay.
- **No em dashes anywhere.** Use commas, periods, colons, or parentheses.
- Brief; never restate values already visible in the adjacent table.
- Deliverable text is formal; internal QC notes to a reviewer drop tentative language ("I guess" comes out).
- Sentiment in client emails stays understated and plain.

## Countermeasures cell (results sheet, D16)

State the actual constructed scope, not the generic countermeasure name. AWSC example scope: removal of left-turn lanes on the major road, dual-indicated R1-1 with R1-3P plaques and flashing beacons, stop bars and pavement markings, W3-1a Stop Ahead with beacons, All-Way plaques added to existing minor-road stops, overhead flasher converted yellow to red.

## Additional Information table (rows 34-39)

Six rows of focused before/after counts that explain the story behind the totals. Row labels use short prefixes: `TC:` for target-crash subsets, `RE:` etc. for type subsets. Example set from an AWSC evaluation: TC: SR 1134 At-Fault (10 to 0), TC: NC 73 At-Fault (2 to 12), TC: No Fault Determined (0 to 2), TC: Failure to Yield (12 to 9), TC: Ran Stop Sign (0 to 5), RE: NC 73 (1 to 8). Rows with no discernible pattern (e.g. a Dark Crashes row that shows nothing) get replaced with something informative. At-fault approach splits are a recurring, useful cut for AWSC conversions.

## Items for Discussion (results sheet, C58)

Bulleted narrative covering, in rough order:

1. Construction period rationale and any construction-period crash (state date, type, severity, and whether the pre/post configuration applied, e.g. a diagram showing TWSC dates it before AWSC installation). When a companion project overlaps the location, note any period adjustment made to isolate the evaluated treatment (e.g. extending construction so the before period ends ahead of the companion work, with the companion project ID).
2. Notable severe crashes with date, time, movement, severity class, including relevant project-development-period crashes.
3. Severity narrative when frequency and severity move in opposite directions (e.g. Class A eliminated, Class B reduced, while totals rose: the known AWSC trade-off).
4. The most severe after-period target crash, described specifically.
5. Non-pattern explanations (e.g. the single before rear-end occurred downstream due to traffic ahead, not intersection operations).
6. Anything the reviewer would otherwise have to ask about (unverifiable crashes, judgment calls kept as stored, excluded side-street run-throughs).

## Assumptions emails

A .docx deliverable sent to NCDOT before the analysis is finalized, following a fixed team template. File naming: `Assumptions Email - {order-id} ({project-id}).docx`. Structure:

- Header bullets: Order ID, Project ID, GPS coordinates with a Google Maps hyperlink, County/Division, Location, Signal ID when the project involves one (omit the bullet entirely for a pure AWSC conversion with no flasher).
- Countermeasure description with sub-bullets. Items that still need imagery verification (Google Earth, Street View, NearMap) are highlighted yellow as placeholders.
- Total Cost Estimate as a main bullet with the Construction / PE / ROW-Utilities breakdown, B/C ratio, and Project Completion date.
- Time Periods table: balanced before/after periods computed back from the crash data end date, construction window between. Example: Before 11/1/2018 to 4/30/2022, Construction 5/1/2022 to 7/31/2022, After 8/1/2022 to 1/31/2026, 3 years 6 months each side. Extending the data end date rebalances both periods.
- Target Crashes section with the definition and any exclusions (see docs/03 target nuances).
- Project Development crash summary from the original study (counts by severity, crash rate, severity index).
- Additional Notes: nonstandard calls and open questions. Recurring examples: a fatal outside the sealed study timeframe but inside the 10-year B/C window, noted as falling within the proposed before period; sign sizing assumptions (e.g. 48"/30") carried from a prior email pending the field memo; companion-project notes; whether the construction window is right.

Primary data source is the Master Evaluation Spreadsheet (one row per assignment: Order ID, Project ID, location, cost, completion date). Follow the template exactly; a missing bullet (cost breakdown, completion, target crashes) is a review finding.

## One-line characterizations for reviewers

When a reviewer asks what happened, one analytically precise sentence: what moved, which direction, and the mechanism, without hedging. A formal restatement of the same sentence goes in the deliverable if needed.
