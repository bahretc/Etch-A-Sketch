"""Structural scan of completed evaluation workbooks (the Drive corpus).

Extracts, from every results-style sheet in a completed workbook, the
formatting decisions the engineer actually made -- print area, margins,
scale, each long-text merged box with its geometry and font size -- and
checks the text_fit model's prediction against the size he chose. The
output is one JSON line per workbook: a compact, durable record of the
conventions, so the rules in results_sheet.py rest on the whole corpus
rather than a handful of examples.

Usage: python3 -m safety_eval.corpus_scan out.jsonl file.xlsx [...]
"""
from __future__ import annotations

import json
import re
import sys
import zipfile

from .text_fit import box_size_pt, fit_font_size

_RESULTS_NAME = re.compile(r"page results|1 page|results -|report", re.I)


def _sheet_map(path):
    with zipfile.ZipFile(path) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    rel = {}
    for rm in re.finditer(r"<Relationship\b[^>]*/>", rels):
        rid = re.search(r'Id="(rId\d+)"', rm.group(0))
        tgt = re.search(r'Target="([^"]+)"', rm.group(0))
        if rid and tgt:
            rel[rid.group(1)] = tgt.group(1)
    out = {}
    for m in re.finditer(
            r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb):
        tgt = rel.get(m.group(2), "")
        if tgt and not tgt.startswith("/"):
            tgt = "xl/" + tgt
        out[m.group(1)] = tgt.lstrip("/")
    return wb, out


def _shared_strings(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
    except KeyError:
        return []
    out = []
    for si in re.findall(r"<si>(.*?)</si>", xml, re.S):
        out.append("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)))
    return out


def _font_size(styles, s_idx):
    xfs = re.search(r"<cellXfs.*?</cellXfs>", styles, re.S)
    if not xfs:
        return None
    lst = re.findall(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>", xfs.group(0),
                     re.S)
    if s_idx >= len(lst):
        return None
    fid = re.search(r'fontId="(\d+)"', lst[s_idx])
    if not fid:
        return None
    fonts_block = re.search(r"<fonts.*?</fonts>", styles, re.S)
    fonts = re.findall(r"<font>.*?</font>|<font/>", fonts_block.group(0),
                       re.S)
    idx = int(fid.group(1))
    if idx >= len(fonts):
        return None
    sz = re.search(r'<sz val="([\d.]+)"/?>', fonts[idx])
    return float(sz.group(1)) if sz else None


def _col_num(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n


def _unescape(t):
    return (t.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"')
            .replace("&#10;", "\n").replace("\r\n", "\n"))


def scan(path):
    wb_xml, sheets = _sheet_map(path)
    strings = _shared_strings(path)
    with zipfile.ZipFile(path) as z:
        styles = z.read("xl/styles.xml").decode("utf-8", "replace")
    try:
        from .results_sheet import _box_bottom_row
    except Exception:
        _box_bottom_row = None
    rec = {"file": path.rsplit("/", 1)[-1],
           "sheet_names": list(sheets), "sheets": []}
    areas = dict(re.findall(
        r'<definedName name="_xlnm\.Print_Area" localSheetId="(\d+)"[^>]*>'
        r"([^<]+)</definedName>", wb_xml))
    order = [m.group(1) for m in re.finditer(r'<sheet name="([^"]+)"',
                                             wb_xml)]
    for name, target in sheets.items():
        if not _RESULTS_NAME.search(name) or not target:
            continue
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read(target).decode("utf-8", "replace")
        except KeyError:
            continue
        merges = re.findall(r'<mergeCell ref="([^"]+)"/>', xml)
        cells = {}
        for cm in re.finditer(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", xml, re.S):
            attrs, body = cm.group(1), cm.group(2) or ""
            ref = re.search(r'r="([A-Z]+\d+)"', attrs)
            if not ref:
                continue
            sm = re.search(r's="(\d+)"', attrs)
            tm = re.search(r't="(\w+)"', attrs)
            cells[ref.group(1)] = (int(sm.group(1)) if sm else 0,
                                   tm.group(1) if tm else None, body)
        boxes = []
        for ref in merges:
            a, b = ref.split(":")
            r1 = int(re.search(r"\d+", a).group(0))
            r2 = int(re.search(r"\d+", b).group(0))
            c1, c2 = _col_num(a), _col_num(b)
            if r2 - r1 < 2 or c2 - c1 < 1:
                continue
            got = cells.get(a)
            if not got:
                continue
            s_idx, ctype, body = got
            text = None
            if ctype == "s":
                v = re.search(r"<v>(\d+)</v>", body)
                if v and int(v.group(1)) < len(strings):
                    text = strings[int(v.group(1))]
            elif ctype in ("str", "inlineStr") or "<is>" in body:
                text = "".join(re.findall(r"<t[^>]*>(.*?)</t>", body, re.S))
            if not text or len(text) < 60:
                continue
            text = _unescape(text)
            size = _font_size(styles, s_idx)
            w, h = box_size_pt(xml, ref)
            fitted = lines = None
            if size:
                try:
                    fitted, lines, _ = fit_font_size(
                        text, w, h,
                        sizes=(12, 11.5, 11, 10.5, 10, 9.5, 9, 8.5, 8,
                               7.5, 7, 6.5, 6))
                except Exception:
                    pass
            boxes.append({
                "ref": ref, "rows": r2 - r1 + 1, "size": size,
                "box_w": round(w, 1), "box_h": round(h, 1),
                "chars": len(text), "text": text,
                "fit_predicts": fitted, "fit_lines": lines})
        if not boxes:
            continue
        heights = {}
        for rm in re.finditer(r'<row r="(\d+)"([^>]*)>', xml):
            hm = re.search(r'ht="([\d.]+)"', rm.group(2))
            if hm:
                heights[int(rm.group(1))] = float(hm.group(1))
        margins = re.search(r"<pageMargins[^/]*/>", xml)
        setup = re.search(r"<pageSetup[^/]*/>", xml)
        bbr = None
        if _box_bottom_row:
            try:
                bbr = _box_bottom_row(xml, styles)
            except Exception:
                pass
        area = areas.get(str(order.index(name))) if name in order else None
        rec["sheets"].append({
            "name": name, "print_area": area,
            "margins": margins.group(0) if margins else None,
            "setup": setup.group(0) if setup else None,
            "box_bottom_row": bbr,
            "row_heights_50_80": {str(k): v for k, v in sorted(
                heights.items()) if 50 <= k <= 80},
            "boxes": boxes})
    return rec


def main():
    out, files = sys.argv[1], sys.argv[2:]
    with open(out, "a", encoding="utf-8") as fh:
        for f in files:
            try:
                rec = scan(f)
            except Exception as exc:                    # noqa: BLE001
                rec = {"file": f.rsplit("/", 1)[-1], "error": str(exc)}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n = len(rec.get("sheets", []))
            print(f"{rec['file']}: {n} results sheet(s)"
                  + (f"  ERROR {rec['error']}" if "error" in rec else ""))


if __name__ == "__main__":
    main()
