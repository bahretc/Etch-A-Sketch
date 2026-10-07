import zipfile, re, io, datetime, json, sys
from xml.sax.saxutils import escape
from PIL import Image
from openpyxl.formula.translate import Translator

BASE = '/tmp/claude-0/-home-user-Etch-A-Sketch/4e077ce8-b4e0-5cdc-9d6d-9c8dc9ebd0c5/'
SRC = BASE + 'scratchpad/dl/workbook.xlsm'
OUT = BASE + 'scratchpad/out/Accessible Intersection Evaluation Workbook - 05-08-203 (W-5601HP).xlsm'
IMG_AERIAL = BASE + 'images/1.webp'
IMG_MAP = BASE + 'images/2.webp'
IMG_STATIONS = BASE + 'scratchpad/out/aadt_station_map_05-08-203.png'

def serial(y, m, d): return (datetime.date(y, m, d) - datetime.date(1899, 12, 30)).days
def col_num(col):
    n = 0
    for ch in col: n = n * 26 + (ord(ch) - 64)
    return n
def split_ref(ref):
    m = re.match(r'([A-Z]+)(\d+)$', ref); return m.group(1), int(m.group(2))
def cell_re(ref): return re.compile(r'<c r="%s"(?: [^>/]*)?(?:/>|>.*?</c>)' % ref, re.S)

class Sheet:
    def __init__(self, xml): self.xml = xml
    def find(self, ref): return cell_re(ref).search(self.xml)
    def style(self, ref):
        m = self.find(ref)
        if not m: return None
        s = re.search(r' s="(\d+)"', m.group(0)); return s.group(1) if s else None
    def build(self, ref, value, kind, style):
        sattr = f' s="{style}"' if style is not None else ''
        if kind == 'blank': return f'<c r="{ref}"{sattr}/>'
        if kind == 'n': return f'<c r="{ref}"{sattr}><v>{value}</v></c>'
        if kind == 'b': return f'<c r="{ref}"{sattr} t="b"><v>{1 if value else 0}</v></c>'
        if kind == 's': return f'<c r="{ref}"{sattr} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'
        if kind == 'f':
            formula, cached = value
            formula = formula[1:] if formula.startswith('=') else formula
            if isinstance(cached, str): return f'<c r="{ref}"{sattr} t="str"><f>{escape(formula)}</f><v>{escape(cached)}</v></c>'
            if cached is None: return f'<c r="{ref}"{sattr}><f>{escape(formula)}</f></c>'
            return f'<c r="{ref}"{sattr}><f>{escape(formula)}</f><v>{cached}</v></c>'
        raise ValueError(kind)
    def set(self, ref, value, kind, style='keep'):
        if style == 'keep': style = self.style(ref)
        new = self.build(ref, value, kind, style)
        m = self.find(ref)
        if m:
            self.xml = self.xml[:m.start()] + new + self.xml[m.end():]; return
        col, row = split_ref(ref)
        rm = re.search(r'<row r="%d"(?: [^>/]*)?(?:/>|>.*?</row>)' % row, self.xml, re.S)
        if not rm:
            # create row before the next existing row (or before </sheetData>)
            rows = [(int(x), mm.start()) for mm in re.finditer(r'<row r="(\d+)"', self.xml) for x in [mm.group(1)]]
            later = [pos for r, pos in rows if r > row]
            pos = min(later) if later else self.xml.index('</sheetData>')
            self.xml = self.xml[:pos] + f'<row r="{row}">{new}</row>' + self.xml[pos:]; return
        rowxml = rm.group(0)
        if rowxml.endswith('/>'):
            rowxml2 = rowxml[:-2] + '>' + new + '</row>'
        else:
            inner_start = rowxml.index('>') + 1
            head, body = rowxml[:inner_start], rowxml[inner_start:-6]
            cells = list(re.finditer(r'<c r="([A-Z]+)\d+"(?: [^>/]*)?(?:/>|>.*?</c>)', body, re.S))
            ins = len(body)
            for c in cells:
                if col_num(c.group(1)) > col_num(col): ins = c.start(); break
            rowxml2 = head + body[:ins] + new + body[ins:] + '</row>'
        self.xml = self.xml[:rm.start()] + rowxml2 + self.xml[rm.end():]
    def set_cached(self, ref, cached):
        m = self.find(ref); assert m, ref
        c = m.group(0); assert '<f' in c, ('not a formula cell', ref, c)
        mm = re.match(r'(<c r="%s"[^>]*>)(.*)(</c>)$' % ref, c, re.S); assert mm, c
        open_tag, inner = mm.group(1), mm.group(2)
        open_tag = re.sub(r' t="[a-z]+"', '', open_tag)
        inner = re.sub(r'<v>.*?</v>|<v/>', '', inner, flags=re.S)
        if isinstance(cached, str):
            open_tag = open_tag[:-1] + ' t="str">'
            inner += f'<v>{escape(cached)}</v>'
        else:
            inner += f'<v>{cached}</v>'
        self.xml = self.xml[:m.start()] + open_tag + inner + '</c>' + self.xml[m.end():]
    def unshare(self, si):
        mm = re.search(r'<c r="([A-Z]+\d+)"([^>]*)><f t="shared" ref="([^"]+)" si="%s">([^<]*)</f>' % si, self.xml)
        assert mm, si
        master, ftxt = mm.group(1), mm.group(4).replace('&amp;', '&').replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>')
        for dm in list(re.finditer(r'<c r="([A-Z]+\d+)"([^>]*)><f t="shared" si="%s"/>' % si, self.xml)):
            ref = dm.group(1)
            tf = Translator('=' + ftxt, origin=master).translate_formula(ref)[1:]
            self.xml = self.xml.replace(dm.group(0), f'<c r="{ref}"{dm.group(2)}><f>{escape(tf)}</f>', 1)
        self.xml = self.xml.replace(mm.group(0), f'<c r="{master}"{mm.group(2)}><f>{escape(ftxt)}</f>', 1)
    def set_row_height(self, row, ht):
        rm = re.search(r'<row r="%d"([^>/]*)>' % row, self.xml); assert rm, row
        attrs = re.sub(r' ht="[^"]*"| customHeight="1"', '', rm.group(1))
        self.xml = self.xml.replace(rm.group(0), f'<row r="{row}"{attrs} ht="{ht}" customHeight="1">', 1)

z = zipfile.ZipFile(SRC)
s3 = Sheet(z.read('xl/worksheets/sheet3.xml').decode('utf-8'))
s4 = Sheet(z.read('xl/worksheets/sheet4.xml').decode('utf-8'))

# ------------------------------------------------------------------ dates
TEAAS = serial(2026, 8, 31)
CON_END = serial(2022, 7, 31); CON_START = serial(2021, 5, 1); CON_MONTHS = 15
BEFORE_START = serial(2017, 4, 1); BEFORE_END = serial(2021, 4, 30)   # equal periods (B14 unchecked)
AFTER_START = serial(2022, 8, 1); AFTER_END = TEAAS
# ------------------------------------------------------------------ AADT data (NCDOT 2025 AADT Stations)
STA = {  # col: (locid, located_on, approach, crossroad, {year: aadt})
 'L': ('0920000868', 'SR 1375 (Lake Wheeler Rd)', 'NORTH OF', 'SR 1390 (Optimist Farm Rd)', {2003:5300,2005:6200,2007:6600,2009:6500,2011:6400,2013:9400,2015:6700,2017:7300,2019:8200,2021:8400,2023:7800,2025:8900}),
 'M': ('0920000991', 'SR 1375 (Lake Wheeler Rd)', 'SOUTH OF', 'SR 1503 (Donny Brook Rd)', {2003:3900,2005:4800,2007:4700,2009:4400,2011:4300,2013:9500,2015:4400,2017:5100,2019:6100,2021:6100,2023:6000,2025:7400}),
 'O': ('0920001913', 'SR 1390 (Optimist Farm Rd)', 'WEST OF', 'SR 1404 (Johnson Pond Rd)', {2014:4200,2017:5400,2019:5500,2021:5600,2023:4800,2025:4800}),
 'P': ('0920001914', 'SR 1503 (Donny Brook Rd)', 'EAST OF', 'SR 1392 (Ransdell Rd)', {2014:3000,2017:3600,2019:3700,2021:3300,2023:2000,2025:2400}),
}
ROUTEID = {'L': 40001375092, 'M': 40001375092, 'O': 40001390092, 'P': 40001503092}
BLACK = {'L': '653', 'M': '654', 'O': '655', 'P': '654'}  # counted years in black on every leg
RED = {'L': '602', 'M': '601', 'O': '600', 'P': '601'}
def xround(x):  # Excel ROUND(x,-2): half away from zero
    import math; return int(math.floor(x / 100 + 0.5) * 100)
calc = {}   # (col, year) -> (formula, cached, style)
for col, (loc, on, appr, cross, data) in STA.items():
    def rowof(y): return 47 + (y - 2002)
    v = {}
    v[2017] = data[2017]; v[2019] = data[2019]; v[2021] = data[2021]; v[2023] = data[2023]; v[2025] = data[2025]
    v[2018] = xround((v[2017] + v[2019]) / 2); v[2020] = xround((v[2019] + v[2021]) / 2 * 0.85)
    v[2022] = xround((v[2021] + v[2023]) / 2); v[2024] = xround((v[2023] + v[2025]) / 2); v[2026] = v[2025]
    for y in range(2017, 2027):
        r = 18 + (y - 2017)
        if y in (2017, 2019, 2021, 2023, 2025):
            calc[(col, y)] = (f'={col}{rowof(y)}', v[y], BLACK[col])
        elif y == 2020:
            calc[(col, y)] = (f'=ROUND(AVERAGE({col}{r-1},{col}{r+1})*0.85,-2)', v[y], RED[col])
        elif y == 2026:
            calc[(col, y)] = (f'={col}{r-1}', v[y], RED[col])
        else:
            calc[(col, y)] = (f'=ROUND(AVERAGE({col}{r-1},{col}{r+1}),-2)', v[y], RED[col])
    STA[col] = (loc, on, appr, cross, data, v)

# ================================================================== SHEET 4 : Evaluation Set-up
s4.unshare(4)                                  # P19:P27 shared formula group -> explicit (all rewritten below anyway)
s4.set('D4', TEAAS, 'n'); s4.set('D5', CON_MONTHS, 'n'); s4.set('E10', CON_END, 'n')
s4.set('N5', 2021, 'n'); s4.set('N6', 2025, 'n'); s4.set('B14', False, 'b'); s4.set('D14', BEFORE_START, 'n')
# cached values of the date-range calculator
for ref, val in {'AF8': 2021, 'AG8': 4, 'AH8': 49, 'AF9': 2022, 'AG9': 7, 'AH9': 15, 'AG10': AFTER_END + 1, 'AH10': 49,
                 'D9': BEFORE_START, 'E9': BEFORE_END, 'F9': 4, 'G9': 1, 'D10': CON_START, 'F10': 1, 'G10': 3,
                 'D11': AFTER_START, 'E11': AFTER_END, 'F11': 4, 'G11': 1}.items():
    s4.set_cached(ref, val)
# AADT calculator rows 18-27
NQR = {}
for y in range(2017, 2027):
    r = 18 + (y - 2017)
    for col in 'LMOP':
        f, cached, st = calc[(col, y)]
        s4.set(f'{col}{r}', (f, cached), 'f', style=st)
    N = (calc[('L', y)][1] + calc[('M', y)][1]) / 2; Q = (calc[('O', y)][1] + calc[('P', y)][1]) / 2
    N = int(N) if N == int(N) else N; Q = int(Q) if Q == int(Q) else Q
    R = N + Q; R = int(R) if R == int(R) else R
    NQR[y] = (N, Q, R)
    s4.set_cached(f'N{r}', N); s4.set_cached(f'Q{r}', Q); s4.set_cached(f'R{r}', R)
s4.set_cached('R5', xround(NQR[2021][2])); s4.set_cached('R6', xround(NQR[2025][2]))
# station metadata rows 37-46 and AADT history rows 47-70
for col, (loc, on, appr, cross, data, v) in STA.items():
    s4.set(f'{col}37', loc, 's'); s4.set(f'{col}38', 'Wake', 's'); s4.set(f'{col}39', 'VOLUME', 's'); s4.set(f'{col}40', '2-WAY', 's')
    s4.set(f'{col}41', ROUTEID[col], 'n'); s4.set(f'{col}42', on, 's'); s4.set(f'{col}43', appr, 's'); s4.set(f'{col}44', cross, 's')
    s4.set(f'{col}45', 'SR', 's'); s4.set(f'{col}46', 'Major Collector', 's')
    for y in range(2002, 2026):
        r = 47 + (y - 2002)
        if y in data: s4.set(f'{col}{r}', data[y], 'n', style='652')
        elif s4.find(f'{col}{r}'):
            s4.xml = cell_re(f'{col}{r}').sub('', s4.xml, count=1)
# make sure every P37..P46 / O37.. have the same style as the L column
for r in range(37, 47):
    st = s4.style(f'L{r}')
    for col in 'MOP':
        m = s4.find(f'{col}{r}')
        if m and st and f' s="{st}"' not in m.group(0):
            s4.xml = s4.xml.replace(m.group(0), re.sub(r' s="\d+"', f' s="{st}"', m.group(0), count=1), 1)
NOTES4 = [
 "AADT source: NCDOT 2025 AADT Stations / Traffic Segments (Traffic Survey Group, published 2026). All four legs have NCDOT count stations (counted in odd years). Black = published station counts; red = interpolated or assumed.",
 "Even years = average of the adjacent odd-year counts, rounded to the nearest 100; 2020 = 0.85 x the interpolated value (COVID); 2026 = 2025 value carried forward.",
 "Leg #3 station 0920001913 is about 1 mi west of the intersection, west of SR 1404 (Johnson Pond Rd, 4,600 vpd in 2025), so the SR 1390 leg is flagged as estimated in the Assumptions leg table (counted years are still shown in black); the TSU intersection inventory (7/2026) also assigns 4,800 vpd (2024) to the SR 1390 leg. The same stations are used in both periods, so the before/after exposure ratio is unaffected.",
 "Leg #4 station 0920001914 is about 0.15 mi east of the intersection, east of SR 1392 (Ransdell Rd, 2,300 vpd in 2025), so the SR 1503 leg volume at SR 1375 is probably higher than the station value (TSU inventory probe estimate about 4,200 vpd in 2021, about 1.28 x the station count). The station value is used unadjusted (counted years in black) and the leg is flagged as estimated in the Assumptions leg table.",
 "Representative years: 2021 (before: the last year in the before period with published counts, per the instructions above; 2020 excluded per the COVID guidance; the 2021 counts may have been taken during the 2021 construction) and 2025 (after). The before period starts 4/1/2017, so 2017 counts are included in the table. Project-development ADT: 6,500 (2010) on SR 1375; total entering volume 9,000 vpd. The 2013 counts (9,400/9,500 on SR 1375) are an outlier outside the study period.",
]
for i, t in enumerate(NOTES4):
    s4.set(f'L{72 + i}', t, 's', style='98')
s4.xml = s4.xml.replace('<dimension ref="B1:AH73"/>', '<dimension ref="B1:AH76"/>')
s4.xml = s4.xml.replace('<sheetView topLeftCell="A20" workbookViewId="0"><selection activeCell="O18" sqref="O18"/>', '<sheetView workbookViewId="0"><selection activeCell="D4" sqref="D4"/>')

# ================================================================== SHEET 3 : Assumptions
A = {}
A['D6'] = (41000076575, 'n'); A['D7'] = ('05-08-203 (TIP #W-5601HP)', 's'); A['D8'] = ('05-1723', 's')
A['D9'] = ('SR 1375 (Lake Wheeler Road) at SR 1390 (Optimist Farm Road)/SR 1503 (Donnybrook Road)', 's')
A['D10'] = ('35.657816, -78.717261', 's'); A['D11'] = ('Wake', 's'); A['D12'] = ('Fuquay-Varina (unincorporated Wake County)', 's')
A['D14'] = ('Realign SR 1390 (Optimist Farm Road) and SR 1503 (Donnybrook Road) to tie directly across from one another and install shoulder-mounted actuated ("Vehicle Entering When Flashing") flashers in both directions on SR 1375 (Lake Wheeler Road)', 's')
A['D15'] = ('Intersection Realignment', 's'); A['D16'] = (665000, 'n'); A['D17'] = (serial(2021, 7, 2), 'n')
A['D18'] = ('Realignment and flashers: CON start 5/24/2021 and completion 7/2/2021 per the NCDOT tracking database (the HNTB compliance memo lists 7/2/2021 as both the begin and completion date), built under the R-2721A (Complete 540) contract; RTE notified 9/16/2021; HNTB compliance review 6/7/2024 (substantial compliance). Dated aerials support the start: the Wake County orthophoto of 2/17/2021 and Nearmap captures of 9/15/2020 and 1/23/2021 show the old SR 1390 T-intersection in use and the new corridor still wooded (the grading north of the old junction in the January 2021 capture is the lot and driveway of 8736 Lake Wheeler Rd, built 2021), and the Nearmap capture of 5/20/2021 shows clearing and earthwork just under way in the southwest quadrant (excavator and spoil piles) with the old T still open. The flashers were then replaced by traffic signal 05-1723 (plan sealed 2/25/2022). Imagery brackets the turn-on: Nearmap 5/30/2022 shows the span wire up but no stop bars on SR 1375, Street View June 2022 shows the heads bagged with the side-street stop signs still up, and Nearmap 10/21/2022 shows stop bars on both SR 1375 approaches (signal operating). Turn-on is taken as July 2022, so the construction period runs from 5/1/2021 through 7/31/2022.', 's')
A['D19'] = ('150 (350 on N leg)', 's')
A['D20'] = ('Frontal Impact Crashes in the Intersection (angle, left turn different roadways, right turn different roadways, left/right turn same roadway and head-on) within the Y-line', 's')
A['D21'] = ('Rear End Crashes on SR 1375 (Lake Wheeler Road) approaching the intersection (both directions)', 's')
A['D22'] = (None, 'blank')
A['D23'] = ('Limited sight distance on SR 1375 (Lake Wheeler Road) and the offset condition of SR 1390 (Optimist Farm Road) with SR 1503 (Donnybrook Road) is contributing to angle and rear end type crashes (35 total crashes 1/1/2011-12/31/2015; 14 correctable).', 's')
A['D24'] = ("""PROJECT / CONSTRUCTION: W-5601HP (05-08-203, WBS 50138.3.225, HSIP, B/C 3.43, evaluation order 41000076575) moved the SR 1390 (Optimist Farm Rd) approach about 200 ft south so it ties into SR 1375 directly across from SR 1503 (Donnybrook Rd) at MP 4.70, and added "Vehicle Entering When Flashing" flashers on both SR 1375 approaches. Built under the R-2721A (Complete 540) contract; the tracking database gives a 5/24/2021 start (also the let date) while the HNTB memo lists 7/2/2021 as both begin and completion. Dated aerials support the start: the Wake County orthophoto of 2/17/2021 and Nearmap captures of 9/15/2020 and 1/23/2021 show the old T in use and the new corridor still wooded, and Nearmap 5/20/2021 shows clearing just under way in the southwest quadrant, so the construction period starts 5/1/2021.

SIGNAL (CONFOUNDER): In 2022 a traffic signal (05-1723, 2-phase fully actuated; plan sealed 2/25/2022; not part of W-5601HP) replaced the flashers, and the VEWF signs and beacons came out. Imagery (see the completion-date notes) brackets the turn-on between late June and mid-October 2022; with the heads already bagged in June, turn-on is taken as July 2022, so the construction period is carried through 7/31/2022 and the after period (8/1/2022-8/31/2026, 4 yr 1 mo) represents the realigned, signalized intersection.

PRIOR PROJECT: W-5205W / 05-13-6035 (sight distance improvements here) was never evaluated because this project began in 2021. Nearmap imagery shows the wooded southwest quadrant of the old SR 1390 T-intersection cleared between 9/5/2016 and 2/19/2017, so that work was complete by February 2017. The before period therefore runs 4/1/2017-4/30/2021 as an equal 4 yr 1 mo period ('Evaluation Set-up' B14 unchecked), with the sight distance improvement in place throughout.

Y-LINE: 150 ft on the south, east and west legs, extended to 350 ft on the north leg (the southbound SR 1375 approach) so the former SR 1390 junction (MP 4.66, about 200 ft north) is covered with the usual 150 ft beyond it. Per the extended-Y-line guidance for realignments; the same leg limits apply in both periods. Pull the fiche wide (SR 1375 MP 4.55-4.85 plus SR 1390, SR 1503, SR 1392), bin by leg and distance in the Fiche Prep Tool, and edit the One Pager criteria sentence for the north-leg extension; curve-exit crashes farther up the north approach can go in the additional-information table.

OTHER CHANGES: Complete 540 (NC 540; built from 2019) opened 9/24/2024 and crosses SR 1375 about 0.3 mi north with no interchange there, changing travel patterns in the after period's last two years.""", 's')
for ref, (val, kind) in A.items():
    s3.set(ref, val, kind)
s3.set_cached('D13', 5)
# Project development crash summary
s3.set('H7', serial(2011, 1, 1), 'n'); s3.set('H8', serial(2015, 12, 31), 'n')
for ref, v in {'H10': 35, 'H11': 0, 'H12': 0, 'H13': 2, 'H14': 7, 'H15': 26}.items(): s3.set(ref, v, 'n')
yrs = 5.0  # Excel YEARFRAC(1/1/2011, 12/31/2015) basis 0 = 1800/360
s3.set_cached('H6', yrs)
for r in range(10, 16):
    s3.set_cached(f'I{r}', {10: 35, 11: 0, 12: 0, 13: 2, 14: 7, 15: 26}[r] / yrs)
# speed limits
s3.set('O6', 45, 'n'); s3.set('O7', 35, 'n')
# leg table
LEGS = {12: ('East', 'SR 1503 (Donnybrook Road)', 45, 2025, "'Evaluation Set-up'!P26", 2400, True),
        13: ('West', 'SR 1390 (Optimist Farm Road)', 35, 2025, "'Evaluation Set-up'!O26", 4800, True),
        14: ('North', 'SR 1375 (Lake Wheeler Road)', 45, 2025, "'Evaluation Set-up'!L26", 8900, False),
        15: ('South', 'SR 1375 (Lake Wheeler Road)', 45, 2025, "'Evaluation Set-up'!M26", 7400, False)}
for r, (leg, road, spd, yr, f, aadt, est) in LEGS.items():
    s3.set(f'K{r}', leg, 's'); s3.set(f'L{r}', road, 's'); s3.set(f'M{r}', spd, 'n'); s3.set(f'N{r}', yr, 'n')
    s3.set(f'O{r}', (f, aadt), 'f'); s3.set(f'P{r}', est, 'b')
    s3.set_cached(f'Q{r}', f'{leg} leg: {road}, {spd} mph, {yr} AADT: {aadt}' + (' (est)' if est else ''))
# time period echo
for ref, v in {'M19': BEFORE_START, 'N19': BEFORE_END, 'O19': 4, 'P19': 1, 'M20': CON_START, 'N20': CON_END, 'O20': 1, 'P20': 3,
               'M21': AFTER_START, 'N21': AFTER_END, 'O21': 4, 'P21': 1}.items():
    s3.set_cached(ref, v)
s3.set_row_height(24, 409)
for _r, _h in ((14, 33), (18, 150), (20, 33), (23, 33)): s3.set_row_height(_r, _h)
s3.xml = s3.xml.replace('<selection activeCell="D10" sqref="D10"/>', '<selection activeCell="D6" sqref="D6"/>')

# ================================================================== drawings
d2 = z.read('xl/drawings/drawing2.xml').decode('utf-8')
PIC_CX, PIC_CY = 4845686, 2602032
MAP_CX, MAP_CY = 1668925, 896178
COL, ROW, COLOFF, ROWOFF = 6, 18, 22224, 174869
_cols = {int(m.group(1)): float(m.group(2)) for m in re.finditer(r'<col min="(\d+)" max="\d+" width="([\d.]+)"', s3.xml)}
def col_emu(c0):  # 0-based column index -> width in EMU (Excel: px = floor(chars*7+5) at 96 dpi)
    w = _cols.get(c0 + 1, 9.15625); return int(w * 7 + 5) * 9525
_rows = {int(m.group(1)): float(m.group(2)) for m in re.finditer(r'<row r="(\d+)"[^>]*? ht="([\d.]+)"', s3.xml)}
def row_emu(r0):  # 0-based row index -> height in EMU
    return int(_rows.get(r0 + 1, 14.4) * 12700)
def anchor(dx, dy, cx, cy, inner):
    c, x = COL, COLOFF + dx
    while x >= col_emu(c): x -= col_emu(c); c += 1
    r, y = ROW, ROWOFF + dy
    while y >= row_emu(r): y -= row_emu(r); r += 1
    return (f'<xdr:oneCellAnchor><xdr:from><xdr:col>{c}</xdr:col><xdr:colOff>{int(x)}</xdr:colOff><xdr:row>{r}</xdr:row><xdr:rowOff>{int(y)}</xdr:rowOff></xdr:from>'
            f'<xdr:ext cx="{cx}" cy="{cy}"/>{inner}<xdr:clientData/></xdr:oneCellAnchor>')
def pic(idn, name, descr, rid, cx, cy):
    return (f'<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{idn}" name="{name}" descr="{escape(descr, {chr(34): "&quot;"})}"/><xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>'
            f'<xdr:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rid}" cstate="print"/><a:srcRect/><a:stretch/></xdr:blipFill>'
            f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:ln w="12700"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill></a:ln></xdr:spPr></xdr:pic>')
def tbox(idn, name, lines, cx=1750000, cy=580000):
    runs = '<a:br><a:rPr lang="en-US" sz="1000"/></a:br>'.join(f'<a:r><a:rPr lang="en-US" sz="1000"/><a:t>{escape(t)}</a:t></a:r>' for t in lines)
    return (f'<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="{idn}" name="{name}"/><xdr:cNvSpPr txBox="1"/></xdr:nvSpPr>'
            f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:schemeClr val="lt1"/></a:solidFill><a:ln w="9525" cmpd="sng"><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:ln></xdr:spPr>'
            f'<xdr:style><a:lnRef idx="0"><a:scrgbClr r="0" g="0" b="0"/></a:lnRef><a:fillRef idx="0"><a:scrgbClr r="0" g="0" b="0"/></a:fillRef><a:effectRef idx="0"><a:scrgbClr r="0" g="0" b="0"/></a:effectRef><a:fontRef idx="minor"><a:schemeClr val="dk1"/></a:fontRef></xdr:style>'
            f'<xdr:txBody><a:bodyPr vertOverflow="clip" horzOverflow="clip" wrap="square" rtlCol="0" anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/>{runs}</a:p></xdr:txBody></xdr:sp>')
AERIAL_DESCR = ('Aerial of SR 1375 (Lake Wheeler Road) at SR 1390 (Optimist Farm Road)/SR 1503 (Donnybrook Road), unincorporated Wake County near Fuquay-Varina (Nearmap, February 2026). '
                'North leg: SR 1375 (Lake Wheeler Road), 45 mph, 2025 AADT: 8900. South leg: SR 1375 (Lake Wheeler Road), 45 mph, 2025 AADT: 7400. '
                'West leg: SR 1390 (Optimist Farm Road), 35 mph, 2025 AADT: 4800 (est). East leg: SR 1503 (Donnybrook Road), 45 mph, 2025 AADT: 2400 (est).')
MAP_DESCR = 'Location map showing SR 1375 (Lake Wheeler Road) at SR 1390 (Optimist Farm Road)/SR 1503 (Donnybrook Road) in southern Wake County, just south of NC 540 between Holly Springs and Garner and north of Fuquay-Varina.'
def fx(f): return int(f * PIC_CX)
def fy(f): return int(f * PIC_CY)
body = ''.join([
    anchor(0, 0, PIC_CX, PIC_CY, pic(12, 'Picture 11', AERIAL_DESCR, 'rId1', PIC_CX, PIC_CY)),
    anchor(fx(0.58), fy(0.03), 1750000, 580000, tbox(13, 'TextBox 12', ['SR 1375 (Lake Wheeler Road)', '45 mph', '2025 AADT: 8,900'])),
    anchor(fx(0.03), fy(0.75), 1750000, 580000, tbox(14, 'TextBox 13', ['SR 1375 (Lake Wheeler Road)', '45 mph', '2025 AADT: 7,400'])),
    anchor(fx(0.03), fy(0.47), 1750000, 580000, tbox(15, 'TextBox 14', ['SR 1390 (Optimist Farm Road)', '35 mph', '2025 AADT: 4,800 (est)'])),
    anchor(fx(0.62), fy(0.36), 1750000, 580000, tbox(9, 'TextBox 8', ['SR 1503 (Donnybrook Road)', '45 mph', '2025 AADT: 2,400 (est)'])),
    anchor(0, 0, MAP_CX, MAP_CY, pic(6, 'Picture 5', MAP_DESCR, 'rId2', MAP_CX, MAP_CY)),
])
head = d2[:d2.index('<xdr:twoCellAnchor')]
d2_new = head + body + '</xdr:wsDr>'
d3 = z.read('xl/drawings/drawing3.xml').decode('utf-8')
d3_new = re.sub(r'descr="[^"]*"', 'descr="AADT count stations used for each leg of SR 1375 (Lake Wheeler Rd) at SR 1390 (Optimist Farm Rd)/SR 1503 (Donny Brook Rd), from NCDOT 2025 AADT station data"', d3, count=1)

# images
def to_bytes(path, fmt, width, **kw):
    im = Image.open(path).convert('RGB')
    if im.width > width: im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, fmt, **kw); return b.getvalue()
aerial_bytes = to_bytes(IMG_AERIAL, 'JPEG', 1600, quality=88, optimize=True)
map_bytes = to_bytes(IMG_MAP, 'PNG', 1000, optimize=True)
sta_bytes = open(IMG_STATIONS, 'rb').read()

# workbook-level parts
wbx = z.read('xl/workbook.xml').decode('utf-8').replace('<calcPr calcId="191029"/>', '<calcPr calcId="191029" fullCalcOnLoad="1"/>')
assert 'fullCalcOnLoad' in wbx
ct = z.read('[Content_Types].xml').decode('utf-8')
ct = re.sub(r'<Override PartName="/xl/calcChain.xml"[^>]*/>', '', ct)
rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8')
rels = re.sub(r'<Relationship Id="rId\d+" Type="[^"]*calcChain" Target="calcChain.xml"/>', '', rels)
assert 'calcChain' not in rels and 'calcChain' not in ct
core = z.read('docProps/core.xml').decode('utf-8')
core = re.sub(r'<dcterms:modified xsi:type="dcterms:W3CDTF">[^<]*</dcterms:modified>', '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-10-07T12:00:00Z</dcterms:modified>', core)

# sanity: no orphan shared formulas, XML well-formed
import xml.dom.minidom
for name, x in (('sheet3', s3.xml), ('sheet4', s4.xml), ('drawing2', d2_new), ('drawing3', d3_new), ('workbook', wbx), ('ct', ct), ('rels', rels), ('core', core)):
    xml.dom.minidom.parseString(x.encode('utf-8'))
for name, sh in (('sheet3', s3), ('sheet4', s4)):
    masters = set(re.findall(r'<f t="shared" ref="[^"]+" si="(\d+)"', sh.xml))
    deps = set(re.findall(r'<f t="shared" si="(\d+)"/>', sh.xml))
    assert deps <= masters, (name, deps - masters)

def validate_sheet(name, xml):
    sd = re.search(r'<sheetData>(.*?)</sheetData>', xml, re.S).group(1)
    rows = list(re.finditer(r'<row r="(\d+)"(?: [^>/]*)?(?:/>|>(.*?)</row>)', sd, re.S))
    assert ''.join(m.group(0) for m in rows) == sd, (name, 'non-row content inside sheetData')
    last = 0
    for m in rows:
        r = int(m.group(1)); assert r > last, (name, 'row order', r, last); last = r
        body = m.group(2) or ''
        cells = list(re.finditer(r'<c r="([A-Z]+)(\d+)"(?: [^>/]*)?(?:/>|>(.*?)</c>)', body, re.S))
        assert ''.join(c.group(0) for c in cells) == body, (name, 'non-cell content in row', r, body[:200])
        lastc = 0
        for c in cells:
            assert int(c.group(2)) == r, (name, 'cell in wrong row', c.group(0)[:80], r)
            cn = col_num(c.group(1)); assert cn > lastc, (name, 'cell order', c.group(0)[:80]); lastc = cn
            inner = c.group(3) or ''
            assert inner.count('<f') <= 1 and inner.count('<v>') <= 1, (name, 'dup f/v', c.group(0)[:120])
    return len(rows)
print('rows sheet3:', validate_sheet('sheet3', s3.xml), 'rows sheet4:', validate_sheet('sheet4', s4.xml))
assert validate_sheet('sheet3-orig', z.read('xl/worksheets/sheet3.xml').decode()) == validate_sheet('sheet3', s3.xml)
assert validate_sheet('sheet4-orig', z.read('xl/worksheets/sheet4.xml').decode()) + 3 == validate_sheet('sheet4', s4.xml)
def refs_of(xml): return set(re.findall(r'<c r="([A-Z]+\d+)"', xml))
lost3 = refs_of(z.read('xl/worksheets/sheet3.xml').decode()) - refs_of(s3.xml); assert not lost3, lost3
lost4 = refs_of(z.read('xl/worksheets/sheet4.xml').decode()) - refs_of(s4.xml)
assert all(re.match(r'[LMOP](4[7-9]|5\d|6\d|70)$', c) for c in lost4), lost4
for name, sh, orig in (('sheet3', s3, z.read('xl/worksheets/sheet3.xml').decode()), ('sheet4', s4, z.read('xl/worksheets/sheet4.xml').decode())):
    n_orig = orig.count('t="shared"'); n_new = sh.xml.count('t="shared"')
    expect = n_orig - (9 if name == 'sheet4' else 0)
    assert n_new == expect, (name, n_orig, n_new, expect)
    assert '<f si=' not in sh.xml
replace = {'xl/worksheets/sheet3.xml': s3.xml.encode('utf-8'), 'xl/worksheets/sheet4.xml': s4.xml.encode('utf-8'),
           'xl/drawings/drawing2.xml': d2_new.encode('utf-8'), 'xl/drawings/drawing3.xml': d3_new.encode('utf-8'),
           'xl/media/image3.jpeg': aerial_bytes, 'xl/media/image4.png': map_bytes, 'xl/media/image5.png': sta_bytes,
           'xl/workbook.xml': wbx.encode('utf-8'), '[Content_Types].xml': ct.encode('utf-8'), 'xl/_rels/workbook.xml.rels': rels.encode('utf-8'),
           'docProps/core.xml': core.encode('utf-8')}
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as zo:
    for item in z.infolist():
        if item.filename == 'xl/calcChain.xml': continue
        data = replace.get(item.filename, z.read(item.filename))
        zi = zipfile.ZipInfo(item.filename, date_time=item.date_time); zi.compress_type = zipfile.ZIP_DEFLATED; zi.external_attr = item.external_attr
        zo.writestr(zi, data)
json.dump({'NQR': {str(k): v for k, v in NQR.items()}, 'calc': {f'{c}{y}': v[:2] for (c, y), v in calc.items()}}, open(BASE + 'scratchpad/out/calc_values.json', 'w'), indent=1)
print('written', OUT)
