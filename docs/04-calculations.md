# 04 - Calculations

Source documents: NCDOT TEPPL N-13 (HSIP methodology), TEAAS training chapters 8 (AADT), 11 (Intersection Studies), 12 (Strip Studies), 15 (Analysis Techniques), 2021 HSIP Warrants, NCDOT Crash Type Descriptions (June 2022). All on connect.ncdot.gov; pull and verify against the current versions rather than trusting this summary blind.

## EPDO and Severity Index

- Active NCDOT weights: **K/A = 76.8, B/C = 8.4, PDO = 1.0**. Do not substitute other agencies' values.
- EPDO = 76.8*(K+A) + 8.4*(B+C) + 1.0*PDO.
- Severity Index = EPDO / total crashes.
- Known-value unit test target from the spec work: EPDO = 372.2 for the reference example (recreate the example from TEAAS Ch. 15 when building tests).
- Observed real-world reference: NC 63 / Elida Home Rd study reported crash rate 75.35 per 100 MEV... note: intersection rates are per MEV entering; that figure came from the TEAAS output for that study. Severity Index 5.38, EPDO 220.40 on 41 crashes.

## Crash rates

- Intersection: rate per million entering vehicles (MEV). Exposure = AADT_entering * days / 1,000,000 over the study period.
- Strip/section: rate per 100 million vehicle miles (100 MVM). Exposure = AADT * length_miles * days / 100,000,000.
- Critical crash rate: statewide/comparable average rate adjusted for exposure (Poisson-based, per TEPPL N-13); a location is over-critical when its rate exceeds it. Pull statewide average rate tables from NCDOT crash data pages for the analysis years.

## AADT

- Intersection AADT: entering volume assembled from approach AADTs (TEAAS Ch. 8 method). Known-value test target: 19,900 for the reference example.
- Strip AADT: length-weighted along the section. Known-value test target: 1,700 for the reference example.
- Side/minor road estimates round to the nearest hundred.
- Growth adjustments when counts and study years differ; document the assumption.
- Evaluation workbook AADT rules (see docs/02 Evaluation Set-up): representative year = last year in each period with actual collected data, never 2020; black font for actual values, red for calculated/interpolated/assumed; one-way roads and 5+ leg intersections get manually computed entering volumes.

## Before/after comparison

- Annualized frequencies: count / period_years, period_years = (end - start)/365.25.
- Compare total, target, severity distribution, crash types, and rates. Report as before/after pairs (e.g. 88/68 target crashes).
- Change and percent change on annualized values when periods differ in length; with symmetric periods raw counts are directly comparable and both get shown.
- Construction-period crashes are excluded from both sides.

## Warrant screening

2021 HSIP Warrants: intersection, section, pedestrian/bicycle, and bridge warrant families, each with frequency and severity thresholds over defined analysis periods. Encode every warrant with its exact thresholds from the 2021 document (do not paraphrase thresholds from memory; parse the PDF). Screening output should state which warrants pass, the qualifying values, and the margin.

## Sliding scale and sub-analyses

- Sliding scale: fixed-length window slid along a strip at fixed increments to find crash concentration segments; report window MP ranges, counts, densities.
- Intersection-within-strip: buffer-based (adjustable, typically 150 ft each side of the intersection MP) COUNTIFS sub-analysis inside a section study.
- SSSD concentration zones and countermeasure-correlation type tallies (SSSD, LT, angle, RE, head-on) per zone.
