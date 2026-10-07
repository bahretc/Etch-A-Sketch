# Second pass: copy LibreOffice-recalculated values into the cached <v> of formula cells on the downstream sheets
import sys, zipfile, re, datetime, openpyxl
from xml.sax.saxutils import escape
sys.path.insert(0, '/tmp/claude-0/-home-user-Etch-A-Sketch/4e077ce8-b4e0-5cdc-9d6d-9c8dc9ebd0c5/scratchpad')
XLSM, LO = sys.argv[1], sys.argv[2]
SHEETS = {'xl/worksheets/sheet11.xml': 'Before', 'xl/worksheets/sheet12.xml': 'After', 'xl/worksheets/sheet14.xml': 'One Pager',
          'xl/worksheets/sheet15.xml': 'For NCDOT staff - for Tracking', 'xl/worksheets/sheet16.xml': 'For NCDOT staff - Email'}
lo = openpyxl.load_workbook(LO, data_only=True)
z = zipfile.ZipFile(XLSM)
out = {}
changed = 0
for part, name in SHEETS.items():
    xml = z.read(part).decode('utf-8'); ws = lo[name]
    def repl(m):
        global changed
        ref, attrs, inner = m.group(1), m.group(2), m.group(3)
        if '<f' not in inner: return m.group(0)
        v = ws[ref].value
        if v is None and ('Assumptions!D13' in inner or 'Assumptions!$D$13' in inner or "'One Pager'!I10" in inner or "'One Pager'!$I$10" in inner): v = 5  # XLOOKUP (division) unsupported by LibreOffice
        if v is None or (isinstance(v, str) and v.startswith('#')): return m.group(0)
        if isinstance(v, datetime.datetime): v = (v - datetime.datetime(1899, 12, 30)).days + v.hour / 24
        elif isinstance(v, datetime.date): v = (v - datetime.date(1899, 12, 30)).days
        attrs2 = re.sub(r' t="[a-z]+"', '', attrs)
        if isinstance(v, bool): attrs2 += ' t="b"'; vx = f'<v>{1 if v else 0}</v>'
        elif isinstance(v, str): attrs2 += ' t="str"'; vx = f'<v>{escape(v)}</v>'
        else: vx = f'<v>{repr(float(v)) if isinstance(v, float) and not float(v).is_integer() else int(v)}</v>'
        inner2 = re.sub(r'<v>.*?</v>|<v/>', '', inner, flags=re.S) + vx
        new = f'<c r="{ref}"{attrs2}>{inner2}</c>'
        if new != m.group(0): changed += 1
        return new
    xml2 = re.sub(r'<c r="([A-Z]+\d+)"((?: [^>/]*)?)>(.*?)</c>', repl, xml, flags=re.S)
    out[part] = xml2.encode('utf-8')
tmp = XLSM + '.tmp'
with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zo:
    for item in z.infolist():
        zi = zipfile.ZipInfo(item.filename, date_time=item.date_time); zi.compress_type = zipfile.ZIP_DEFLATED; zi.external_attr = item.external_attr
        zo.writestr(zi, out.get(item.filename, z.read(item.filename)))
z.close()
import os; os.replace(tmp, XLSM)
print('cached values refreshed:', changed)
