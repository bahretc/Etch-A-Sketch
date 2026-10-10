#!/usr/bin/env python3
"""Fill the TSU "CalculatedAADT" template (4-LEG INTERSECTION ADT sheet) for study 41000079736.

Template: data/CalculatedAADT_template_41000077748.xls (from the 41000077748 package).
Outputs:  41000079736_CalculatedAADT.xls (MS Excel 97) and 41000079736_CalculatedAADT.xlsx (Excel 2007 XML),
          both stored from the same filled document.

The template is filled in LibreOffice itself (headless, Python UNO) rather than with openpyxl: openpyxl drops
the template's drawn intersection lines (line shapes), flattens the superscript footnote markers and breaks the
two-line printed page header. Only the inputs change; every formula of the template is kept, the template's
page styles are untouched except that the 4-LEG sheet is set to print on one page (fit to 1 x 1 pages).
"""
import datetime, json, socket, subprocess, tempfile, textwrap, time
from pathlib import Path

import uno                                           # python3-uno (LibreOffice's Python bridge)
from com.sun.star.beans import PropertyValue
from com.sun.star.awt.FontSlant import ITALIC

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "data" / "CalculatedAADT_template_41000077748.xls"
OUT_XLS = HERE / "41000079736_CalculatedAADT.xls"
OUT_XLSX = HERE / "41000079736_CalculatedAADT.xlsx"
A = json.loads((HERE / "aadt.json").read_text()); mid = A["entering_aadt"]["study_10yr_middle_year"]

STUDY = 41000079736
START, END = datetime.date(2016, 9, 1), datetime.date(2026, 8, 31)
ADT_USED = 12300                                     # "Annual ADT = 12300" on the TEAAS 10-yr Intersection Analysis Report
# Short template-style leg names (the value cells are 30.7 mm / 36.3 mm wide, Arial 10 bold); the full names are in the notes.
# Each leg: (template cells for street / ADT / year, short name, key in aadt.json, superscript marker or "")
LEGS = [(("D23", "D24", "D25"), "NC 180/226 (N)", "N", ""),
        (("B31", "B32", "B33"), "SR 1103 (NW)", "NW", "2"),
        (("F31", "F32", "F33"), "SR 1103 (SE)", "SE", ""),
        (("D40", "D41", "D42"), "NC 180/226 (S)", "S", "")]
NOTES = [  # (marker, text); printed under the template's note 1 (row 47), one 105-character line per row
    ("2", "SR 1103 (NW) has no 2021 count: 1,400 is a straight-line estimate between the 2018 (1,600) and 2022 (1,300) "
          "NCDOT counts, rounded per the NCDOT/AASHTO AADT rounding chart (nearest 100 for 1,000-9,999). The other legs "
          "are the published 2021 NCDOT counts. Legs: N/S = NC 180/NC 226 (S Post Rd), stations 0230000187 (N) and "
          "0230000152 (S); NW = SR 1103 (Pleasant Dr), station 0230000045; SE = SR 1103 (Pleasant Hill Church Rd), "
          "station 0230000531."),
    ("3", "ADT Used in Study = Annual ADT on the TEAAS 10-year Intersection Analysis Report (12,300)."),
]
NOTE_ROW, NOTE_WIDTH = 49, 105                        # first note row (row 48 stays blank as a spacer); chars per printed line


def pv(name, value):
    p = PropertyValue(); p.Name = name; p.Value = value; return p


class Soffice:
    """Headless LibreOffice listener on a private user profile and a free localhost port."""
    def __enter__(self):
        self.profile = tempfile.TemporaryDirectory(prefix="lo_profile_")
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        self.proc = subprocess.Popen(
            ["soffice", f"-env:UserInstallation={Path(self.profile.name).as_uri()}", "--headless", "--invisible",
             "--nologo", "--norestore", "--nodefault",
             f"--accept=socket,host=127.0.0.1,port={self.port};urp;StarOffice.ComponentContext"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        for _ in range(120):
            try:
                self.ctx = resolver.resolve(f"uno:socket,host=127.0.0.1,port={self.port};urp;StarOffice.ComponentContext")
                break
            except Exception:
                if self.proc.poll() is not None: raise RuntimeError("soffice exited before accepting connections")
                time.sleep(0.5)
        else:
            self.proc.kill(); raise RuntimeError("could not connect to soffice")
        self.desktop = self.ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", self.ctx)
        return self

    def __exit__(self, *exc):
        try: self.desktop.terminate()
        except Exception: pass
        try: self.proc.wait(timeout=30)
        except Exception: self.proc.kill()
        self.profile.cleanup()


def set_marked_text(cell, text, marker, *, before=""):
    """Write `text` with a superscript footnote `marker` (template style: 'ADT Year¹:'). `before` = chars of the
    cell text that precede the marker; the marker is inserted there, e.g. before the trailing colon."""
    if not marker:
        cell.setString(text); return
    cell.setString(before + marker + text[len(before):])
    cur = cell.Text.createTextCursor()
    cur.gotoStart(False); cur.goRight(len(before), False); cur.goRight(len(marker), True)
    cur.CharEscapement = 33; cur.CharEscapementHeight = 58                  # superscript


def fill(doc):
    sh = doc.Sheets.getByName("4-LEG INTERSECTION ADT")
    cell = sh.getCellRangeByName
    nd = doc.NullDate; null = datetime.date(nd.Year, nd.Month, nd.Day)
    cell("B1").setValue(float(STUDY))                 # floats: UNO setValue takes a double
    cell("B4").setValue(float((START - null).days)); cell("B5").setValue(float((END - null).days))   # keep the template date format
    cell("B6").setString("")                        # ADT adjustment %: left blank as in the package examples
    cell("B7").setValue(float(ADT_USED))
    set_marked_text(cell("A7"), cell("A7").String, "3", before="ADT Used in Study")   # "ADT Used in Study³:"
    for (c_name, c_adt, c_year), name, key, marker in LEGS:
        set_marked_text(cell(c_name), name, marker, before=name)                      # "SR 1103 (NW)²"
        cell(c_adt).setValue(float(mid["legs"][key])); cell(c_year).setValue(float(mid["year"]))
    # Notes: italic blue Arial 10 like the template's note 1 in A47; long notes are split into rows so nothing
    # extends past column F (A..F = 201 mm; 105 chars of Arial 10 italic is about 180 mm).
    row = NOTE_ROW
    for marker, text in NOTES:
        lines = textwrap.wrap(text, NOTE_WIDTH, subsequent_indent="   ")
        for i, line in enumerate(lines):
            c = cell(f"A{row}")
            set_marked_text(c, (" " if i == 0 else "") + line, marker if i == 0 else "")
            c.CharFontName = "Arial"; c.CharHeight = 10; c.CharPosture = ITALIC; c.CharColor = 0x0000FF
            row += 1
    # Print the 4-LEG sheet on one page (the template's layout plus the notes slightly exceeds one page in LibreOffice)
    ps = doc.StyleFamilies.getByName("PageStyles").getByName(sh.PageStyle)
    ps.ScaleToPagesX = 1; ps.ScaleToPagesY = 1
    doc.calculateAll()
    return sh


def main():
    with Soffice() as lo:
        doc = lo.desktop.loadComponentFromURL(uno.systemPathToFileUrl(str(TEMPLATE)), "_blank", 0, (pv("Hidden", True),))
        try:
            sh = fill(doc)
            doc.storeToURL(uno.systemPathToFileUrl(str(OUT_XLS)), (pv("FilterName", "MS Excel 97"), pv("Overwrite", True)))
            doc.storeToURL(uno.systemPathToFileUrl(str(OUT_XLSX)), (pv("FilterName", "Calc MS Excel 2007 XML"), pv("Overwrite", True)))
            c = sh.getCellRangeByName
            print(f"wrote {OUT_XLS.name} and {OUT_XLSX.name}: ADT used {c('B7').String}, total {c('B11').String}, "
                  f"difference {c('B12').String}, status '{c('B13').String}', shapes on 4-LEG sheet {sh.DrawPage.Count}")
        finally:
            doc.close(True)


if __name__ == "__main__":
    main()
