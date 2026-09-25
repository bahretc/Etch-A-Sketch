"""Edits to a finished Word one pager (the workbook macro's docx output).

The one pager is built by the workbook's macro into NCDOT's Word template and
then reviewed in Word with tracked changes. These helpers apply the review
without Word and without resaving through python-docx (which drops parts it
does not model): every edit is a string edit of one zip member, and every
other member is copied byte for byte.

* :func:`accept_all_revisions` accepts tracked insertions, deletions,
  paragraph-mark changes and formatting changes, as Word's "Accept All" does;
  :func:`stop_tracking` turns Track Changes off in settings.xml.
* :func:`replace_paragraph_text` rewrites the text of the paragraph holding a
  phrase, keeping the formatting of its first run.
* :func:`replace_picture` swaps the image of a named picture (for example the
  "Map/Satellite View"), fixes its height to the new aspect, drops the SVG
  twin Office keeps beside the PNG, and sets the alt text (``descr``), which
  NCDOT requires on every image (Assignment 37 QC, 2026-09).
* :func:`edit_docx` applies a set of member edits to a copy of the file.
"""
from __future__ import annotations

import io
import os
import posixpath
import re
import zipfile
from xml.sax.saxutils import escape, quoteattr

_P_RE = re.compile(r"<w:p\b[^>]*?(?:/>|>.*?</w:p>)", re.S)
_T_RE = re.compile(r"(<w:t\b[^>]*>)(.*?)(</w:t>)", re.S)


def _strip(pattern: str, xml: str) -> str:
    return re.sub(pattern, "", xml, flags=re.S)


_ATTRS = r'(?:[^>"]|"[^"]*")*?'


def _open(tag: str) -> str:
    """An opening (not self-closing) tag."""
    return rf"<w:{tag}\b{_ATTRS}(?<!/)>"


def _self(tag: str) -> str:
    return rf"<w:{tag}\b{_ATTRS}/>"


def _element(tag: str) -> str:
    return _open(tag) + rf"(?:(?!</w:{tag}>).)*?</w:{tag}>"


def accept_all_revisions(xml: str) -> str:
    """Accept every tracked change in a WordprocessingML part."""
    # deleted content and moved-away content disappear
    xml = _strip(_element("del"), xml)
    xml = _strip(_element("moveFrom"), xml)
    # a deleted paragraph mark merges the paragraph into the next one
    xml = _merge_deleted_marks(xml)
    # inserted and moved-in content stays, unwrapped
    for tag in ("ins", "moveTo"):
        xml = re.sub(_open(tag) + rf"((?:(?!</w:{tag}>).)*?)</w:{tag}>", r"\1", xml, flags=re.S)
    # revision markers on paragraph marks and range markers
    for tag in ("ins", "del", "moveFrom", "moveTo", "moveFromRangeStart", "moveFromRangeEnd",
                "moveToRangeStart", "moveToRangeEnd"):
        xml = _strip(_self(tag), xml)
    # formatting changes keep the new formatting: drop the recorded old one
    for tag in ("rPrChange", "pPrChange", "tblPrChange", "trPrChange", "tcPrChange",
                "sectPrChange", "tblGridChange", "numberingChange"):
        xml = _strip(_self(tag), xml)
        xml = _strip(_element(tag), xml)
    xml = _strip(r"<w:rPr>\s*</w:rPr>", xml)
    return xml


def _merge_deleted_marks(xml: str) -> str:
    """Paragraphs whose mark is deleted (<w:del/> inside pPr/rPr) join the
    following paragraph: their remaining runs move to its start."""
    out, carry, pos = [], "", 0
    for m in _P_RE.finditer(xml):
        para = m.group(0)
        out.append(xml[pos:m.start()])
        pos = m.end()
        ppr = re.search(r"<w:pPr>.*?</w:pPr>", para, re.S)
        mark_deleted = bool(ppr and re.search(r"<w:rPr>(?:(?!</w:rPr>).)*" + _self("del"),
                                               ppr.group(0), re.S))
        if carry:
            head = re.match(r"(<w:p\b[^>]*>)((?:<w:pPr>.*?</w:pPr>)?)", para, re.S)
            para = head.group(0) + carry + para[head.end():]
            carry = ""
        if mark_deleted:
            body = para
            body = re.sub(r"^<w:p\b[^>]*>", "", body)
            body = re.sub(r"</w:p>$", "", body)
            body = re.sub(r"^<w:pPr>.*?</w:pPr>", "", body, flags=re.S)
            carry = body
            continue
        out.append(para)
    out.append(xml[pos:])
    if carry:                      # a deleted mark on the last paragraph: keep it
        out.append(carry)
    return "".join(out)


def stop_tracking(settings_xml: str) -> str:
    """Turn Track Changes off (Review > Track Changes)."""
    return _strip(r"<w:trackRevisions\b[^>]*?/>", settings_xml)


def paragraph_texts(xml: str) -> list[str]:
    from xml.sax.saxutils import unescape
    return [unescape("".join(t.group(2) for t in _T_RE.finditer(p.group(0))))
            for p in _P_RE.finditer(xml)]


def replace_paragraph_text(xml: str, old: str, new: str) -> tuple[str, int]:
    """Rewrite each paragraph whose text contains ``old``: the paragraph's full
    text becomes its text with ``old`` replaced by ``new``, written into the
    first text run (its formatting kept); the other runs' text is emptied.
    Returns (xml, paragraphs changed)."""
    from xml.sax.saxutils import unescape
    count = 0

    def one(m):
        nonlocal count
        para = m.group(0)
        ts = list(_T_RE.finditer(para))
        text = unescape("".join(t.group(2) for t in ts))
        if old not in text or not ts:
            return para
        count += 1
        full = text.replace(old, new)
        pieces, last = [], 0
        for k, t in enumerate(ts):
            pieces.append(para[last:t.start()])
            open_tag = t.group(1)
            if k == 0:
                if 'xml:space="preserve"' not in open_tag:
                    open_tag = open_tag[:-1] + ' xml:space="preserve">'
                pieces.append(open_tag + escape(full) + t.group(3))
            else:
                pieces.append(open_tag + t.group(3))
            last = t.end()
        pieces.append(para[last:])
        return "".join(pieces)

    return _P_RE.sub(one, xml), count


def replace_picture(docx_members: dict[str, bytes], doc_pr_name: str, image: bytes,
                    descr: str, title: str | None = None) -> dict[str, bytes]:
    """Swap the image of the inline or anchored picture whose ``wp:docPr``
    name is ``doc_pr_name``; returns the edited members.

    The PNG part keeps its name (bytes replaced), the displayed width is kept
    and the height follows the new aspect, the SVG twin (``asvg:svgBlip``) is
    dropped with its relationship and part, and ``descr`` becomes the alt
    text."""
    from PIL import Image

    members = dict(docx_members)
    doc = members["word/document.xml"].decode("utf-8")
    rels_name = "word/_rels/document.xml.rels"
    rels = members[rels_name].decode("utf-8")
    drawing = None
    for m in re.finditer(r"<w:drawing>.*?</w:drawing>", doc, re.S):
        if re.search(rf'<wp:docPr\b[^>]*\bname={re.escape(quoteattr(doc_pr_name))}', m.group(0)):
            drawing = m
            break
    if drawing is None:
        raise KeyError(f"no picture named {doc_pr_name!r}")
    d = drawing.group(0)
    blip = re.search(r'<a:blip\b[^>]*\br:embed="([^"]+)"', d)
    target = re.search(rf'<Relationship\b[^>]*\bId="{blip.group(1)}"[^>]*\bTarget="([^"]+)"', rels) \
        or re.search(rf'<Relationship\b[^>]*\bTarget="([^"]+)"[^>]*\bId="{blip.group(1)}"', rels)
    part = posixpath.normpath(posixpath.join("word", target.group(1)))
    members[part] = image

    # svg twin
    svg = re.search(r'<asvg:svgBlip\b[^>]*\br:embed="([^"]+)"[^>]*/>', d)
    if svg:
        rid = svg.group(1)
        d = re.sub(r'<a:ext\b[^>]*>\s*<asvg:svgBlip\b[^>]*/>\s*</a:ext>', "", d)
        if doc.count(f'r:embed="{rid}"') == 1:
            st = re.search(rf'<Relationship\b[^>]*\bId="{rid}"[^>]*\bTarget="([^"]+)"', rels)
            rels = re.sub(rf'<Relationship\b[^>]*\bId="{rid}"[^>]*/>', "", rels)
            if st:
                members.pop(posixpath.normpath(posixpath.join("word", st.group(1))), None)
        d = re.sub(r"<a:extLst>\s*</a:extLst>", "", d)

    # height follows the new aspect at the same width
    w, h = Image.open(io.BytesIO(image)).size
    ext = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"/>', d)
    cx = int(ext.group(1))
    cy = round(cx * h / w)
    d = d.replace(ext.group(0), f'<wp:extent cx="{cx}" cy="{cy}"/>', 1)
    d = re.sub(r'(<pic:spPr\b.*?<a:ext cx=")(\d+)(" cy=")(\d+)(")',
               lambda m: f"{m.group(1)}{cx}{m.group(3)}{cy}{m.group(5)}", d, 1, flags=re.S)

    # alt text
    def docpr(m):
        tag = re.sub(r'\s(descr|title)="[^"]*"', "", m.group(0))
        extra = f" descr={quoteattr(descr)}"
        if title:
            extra += f" title={quoteattr(title)}"
        return tag[:-2].rstrip() + extra + "/>" if tag.endswith("/>") else tag[:-1] + extra + ">"
    d = re.sub(r"<wp:docPr\b[^>]*?/?>", docpr, d, 1)
    d = re.sub(r"(<pic:cNvPr\b[^>]*?)\s+descr=\"[^\"]*\"", r"\1", d)
    d = re.sub(r"<pic:cNvPr\b([^>]*?)(/?)>",
               lambda m: f"<pic:cNvPr{m.group(1)} descr={quoteattr(descr)}{m.group(2)}>", d, 1)

    doc = doc[:drawing.start()] + d + doc[drawing.end():]
    members["word/document.xml"] = doc.encode("utf-8")
    members[rels_name] = rels.encode("utf-8")
    ct = members["[Content_Types].xml"].decode("utf-8")
    if not any(n.endswith(".svg") for n in members) and 'Extension="svg"' in ct:
        ct = re.sub(r'<Default\b[^>]*Extension="svg"[^>]*/>', "", ct)
        members["[Content_Types].xml"] = ct.encode("utf-8")
    return members


def read_members(path: str) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        return infos, {i.filename: z.read(i.filename) for i in infos}


def write_members(path: str, infos: list[zipfile.ZipInfo], members: dict[str, bytes]) -> None:
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for info in infos:
            if info.filename in members:
                z.writestr(info, members[info.filename])
    os.replace(tmp, path)


def edit_docx(path_in: str, path_out: str, *, accept: bool = True,
              replacements: list[tuple[str, str]] = (), picture: dict | None = None) -> dict:
    """Accept tracked changes, stop tracking, replace paragraph texts and swap
    a picture, in one pass. ``picture`` = {name, image (bytes), descr, title}.
    Returns a report of what changed."""
    infos, members = read_members(path_in)
    report = {"replacements": {}}
    doc = members["word/document.xml"].decode("utf-8")
    if accept:
        before = len(re.findall(r"<w:(ins|del)\b", doc))
        doc = accept_all_revisions(doc)
        report["revisions_accepted"] = before
        settings = members["word/settings.xml"].decode("utf-8")
        members["word/settings.xml"] = stop_tracking(settings).encode("utf-8")
    for old, new in replacements:
        doc, n = replace_paragraph_text(doc, old, new)
        report["replacements"][old[:40]] = n
    members["word/document.xml"] = doc.encode("utf-8")
    if picture:
        members = replace_picture(members, picture["name"], picture["image"],
                                  picture["descr"], picture.get("title"))
    write_members(path_out, infos, members)
    report["left_tracked"] = len(re.findall(r"<w:(ins|del|moveFrom|moveTo)\b|Change\b",
                                            members["word/document.xml"].decode("utf-8")))
    return report
