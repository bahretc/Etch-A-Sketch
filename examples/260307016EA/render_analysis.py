"""Render the TEAAS Strip Analysis Report CSV as a paged PDF.

The CSV is a page dump of the TEAAS printed report: every page starts
with the three line report header and ends with the dated disclaimer.
Each page is rendered generically: single cell rows become section
headings, runs of multi cell rows become tables (first row styled as a
header when it looks like one), and "Unit" rows in the Report Details
become indented sub rows under their crash.
"""
import csv
import html
import re
import subprocess
import os
import sys

src, out_html, out_pdf = sys.argv[1:4]
rows = list(csv.reader(open(src, encoding="utf-8", newline="")))


def esc(s):
    return html.escape(s or "").replace("\n", "<br>")


def is_page_head(r):
    return len(r) > 1 and r[0] == "" and r[1].startswith("North Carolina")


def is_disclaimer(r):
    return len(r) > 1 and re.match(r"\d\d/\d\d/\d{4}$", r[0] or "") \
        and r[1].startswith("All data")


pages, cur, disclaimer, head = [], [], "", ""
for r in rows:
    if is_page_head(r):
        head = r[1]
        if cur:
            pages.append(cur)
        cur = []
        continue
    if is_disclaimer(r):
        disclaimer = r[1]
        continue
    cur.append(r)
if cur:
    pages.append(cur)

NUM = re.compile(r"^[\s$]*-?[\d,]+(\.\d+)?\s*(\(.*\))?$")


def looks_header(r, nxt):
    cells = [c for c in r if c != ""]
    if any("\n" in c for c in cells):
        return True
    if any(c.rstrip().endswith((":", "=")) for c in cells):
        return False
    if all(not NUM.match(c) for c in cells) and nxt is not None:
        return any(NUM.match(c) for c in nxt if c)
    return False


def render_table(group):
    out = ["<table>"]
    first = True
    for k, r in enumerate(group):
        nxt = group[k + 1] if k + 1 < len(group) else None
        if r and r[0] == "Unit":
            txt = " ".join(esc(x) for x in r if x != "")
            out.append(f"<tr class='u'><td class='k' colspan='24'>{txt}</td></tr>")
            continue
        tag = "th" if (first and looks_header(r, nxt)) else "td"
        first = False
        cells = list(r)
        while cells and cells[-1] == "":
            cells.pop()
        out.append("<tr>" + "".join(
            f"<{tag} class='{'n' if NUM.match(c or '') else 't'}'>{esc(c)}</{tag}>"
            for c in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


css = """
@page{size:letter landscape;margin:0.45in 0.5in}
body{font-family:Arial,Helvetica,sans-serif;font-size:8.6px;color:#000;margin:0}
.hd{text-align:center;font-weight:bold;font-size:11px;line-height:1.3;margin-bottom:8px}
h3{font-size:9.5px;margin:9px 0 3px;border-bottom:1px solid #000}
table{border-collapse:collapse;margin-bottom:4px}
th{background:#D9D9D9;border:1px solid #888;padding:2px 5px;font-size:8px;text-align:center;vertical-align:bottom}
td{border:1px solid #CCC;padding:1.5px 5px;vertical-align:top;white-space:nowrap}
td.n{text-align:right}td.t{text-align:left}
tr.u td{border:none;color:#333;font-size:8.2px;background:#F6F6F6}
tr.u td.k{padding-left:24px}
.dis{margin-top:10px;font-size:7.4px;color:#333}
.pg{page-break-after:always}
.pg:last-child{page-break-after:auto}
"""
parts = [f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>"]
for pg in pages:
    parts.append(f"<div class='pg'><div class='hd'>{esc(head)}</div>")
    group = []
    for r in pg + [[]]:
        cells = [c for c in r if c != ""]
        if len(cells) == 1 and r[0] != "Unit" and not (r[0] == "" and r[1:]):
            if group:
                parts.append(render_table(group))
                group = []
            parts.append(f"<h3>{esc(cells[0])}</h3>")
        elif len(cells) == 0:
            if group:
                parts.append(render_table(group))
                group = []
        else:
            group.append(r)
    parts.append(f"<div class='dis'>{esc(disclaimer)}</div></div>")
parts.append("</body></html>")
open(out_html, "w", encoding="utf-8").write("\n".join(parts))
subprocess.run(["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "--headless",
                "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                "--print-to-pdf=" + os.path.abspath(out_pdf), "file://" + os.path.abspath(out_html)],
               check=True, capture_output=True)
print("pdf ->", out_pdf, "pages:", len(pages))
