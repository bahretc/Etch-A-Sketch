"""Strip collision diagram (docs/07 phase 4) from a crash list.

Fan-out layout: every crash gets an evenly spaced callout above the roadway
with a dotted leader down to its true milepost, so clusters at one milepost
stay readable. Symbology: arrows for moving units in their travel direction
(page right = increasing milepost), open square for a stopped unit, colour by
severity, N/W flags for night and wet. The engineer owns the final symbology;
this is the review draft the team has used on strip studies.

Input can be a list of :class:`CrashSymbol` or a CSV with columns
``crash_id,mp,units,type,severity,date,night,wet`` where ``units`` is a
semicolon list like ``W:mv;N:st`` (direction E/W/N/S, mv moving, st stopped).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

SEV_COLOR = {"K": "#7b0000", "A": "#c62828", "B": "#e65100", "C": "#f9a825", "O": "#1a1a1a"}
SEV_RANK = {"K": 0, "A": 1, "B": 2, "C": 3, "O": 4}
SEV_LABEL = {"K": "Fatal", "A": "Class A injury", "B": "Class B injury", "C": "Class C injury",
             "O": "Property damage only"}


@dataclass
class CrashSymbol:
    crash_id: str
    mp: float
    units: list = field(default_factory=list)   # [(dir, "mv"|"st")]
    type: str = ""
    severity: str = "O"
    date: str = ""
    night: bool = False
    wet: bool = False


@dataclass
class Feature:
    mp: float
    label: str


@dataclass
class StripSpec:
    title: str
    subtitle: str = ""
    mp_start: float = 0.0
    mp_end: float = 1.0
    features: list = field(default_factory=list)      # Feature
    note: str = ("Arrow = unit travel direction (page right = increasing milepost). "
                 "Open square = stopped vehicle. N = night, W = wet. Callouts are evenly spaced; "
                 "dotted leaders point to each crash's milepost.")


def parse_units(text: str) -> list:
    out = []
    for tok in (text or "").split(";"):
        tok = tok.strip()
        if not tok:
            continue
        d, _, m = tok.partition(":")
        out.append((d.strip().upper()[:1] or "E", (m.strip().lower() or "mv")))
    return out


def load_csv(path: str) -> list[CrashSymbol]:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(CrashSymbol(
                crash_id=str(r["crash_id"]).strip(), mp=float(r["mp"]),
                units=parse_units(r.get("units", "")), type=(r.get("type") or "").strip(),
                severity=(r.get("severity") or "O").strip().upper()[:1] or "O",
                date=(r.get("date") or "").strip(),
                night=str(r.get("night", "")).strip().lower() in ("1", "y", "yes", "true"),
                wet=str(r.get("wet", "")).strip().lower() in ("1", "y", "yes", "true")))
    return rows


def draw_strip_diagram(crashes: list[CrashSymbol], spec: StripSpec, out_stem: str,
                       dpi: int = 160) -> dict:
    """Write ``out_stem``.pdf and ``out_stem``.png; returns paths and counts."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import FancyArrow, Rectangle

    fig, ax = plt.subplots(figsize=(17, 9.5))
    span = spec.mp_end - spec.mp_start
    X0, X1 = spec.mp_start - 0.03 * span, spec.mp_end + 0.05 * span
    ROAD_Y, ROAD_H = 0.0, 0.14
    ax.add_patch(Rectangle((X0, ROAD_Y - ROAD_H / 2), X1 - X0, ROAD_H, facecolor="#e8e8e8", edgecolor="#555", zorder=1))
    ax.plot([X0, X1], [ROAD_Y, ROAD_Y], color="#f2c200", lw=1.4, ls=(0, (7, 5)), zorder=2)
    for f in spec.features:
        y0, y1 = -ROAD_H / 2, -ROAD_H / 2 - 0.12
        ax.add_patch(Rectangle((f.mp - 0.004 * span, y1), 0.008 * span, y0 - y1, facecolor="#e8e8e8", edgecolor="#555", zorder=1))
        ax.annotate(f.label, (f.mp, y1 - 0.015), ha="center", va="top", fontsize=9, style="italic", color="#333")
    step = 0.05 if span <= 1.5 else 0.1
    t = spec.mp_start
    ticks = []
    while t <= spec.mp_end + 1e-9:
        ticks.append(round(t, 2))
        t += step
    for t in ticks:
        ax.plot([t, t], [-ROAD_H / 2 - 0.015, -ROAD_H / 2 - 0.03], color="#333", lw=0.8)
        ax.annotate(f"{t:.2f}", (t, -ROAD_H / 2 - 0.04), ha="center", va="top", fontsize=8.5, color="#333")
    ax.annotate("Milepost", (X1 + 0.002 * span, -ROAD_H / 2 - 0.04), fontsize=9, color="#333", va="top")

    ordered = sorted(crashes, key=lambda c: (c.mp, c.crash_id))
    n = max(len(ordered), 1)
    slot_w = (X1 - X0) / n
    DX = {"E": 0.017 * span * 1.6, "W": -0.017 * span * 1.6, "N": 0.0, "S": 0.0}
    DY = {"E": 0.0, "W": 0.0, "N": 0.05, "S": -0.05}
    CALLOUT_Y = 0.42
    worst: dict = {}
    for c in ordered:
        if c.mp not in worst or SEV_RANK.get(c.severity, 4) < SEV_RANK.get(worst[c.mp], 4):
            worst[c.mp] = c.severity
    for mp, sev in worst.items():
        ax.plot([mp], [ROAD_H / 2], marker="o", ms=3.5, color=SEV_COLOR.get(sev, "#1a1a1a"), zorder=5)
    for i, c in enumerate(ordered):
        sx = X0 + (i + 0.5) * slot_w
        color = SEV_COLOR.get(c.severity, "#1a1a1a")
        ax.plot([sx, sx, c.mp], [CALLOUT_Y - 0.10, ROAD_H / 2 + 0.10, ROAD_H / 2], color="#b0b0b0", lw=0.8, ls=":", zorder=2)
        flags = ("  N" if c.night else "") + ("  W" if c.wet else "")
        ax.annotate(f"{c.type}{flags}", (sx, CALLOUT_Y + 0.105), ha="center", fontsize=10.5, fontweight="bold", color=color)
        for j, (d, man) in enumerate(c.units):
            off = (j - (len(c.units) - 1) / 2) * 0.026
            if man == "st":
                ax.add_patch(Rectangle((sx + DX.get(d, 0) - 0.0045 * span * 1.6, CALLOUT_Y + off - 0.011), 0.009 * span * 1.6, 0.022,
                                       facecolor="white", edgecolor=color, lw=1.2, zorder=4))
                continue
            dx, dy = DX.get(d, 0.0), DY.get(d, 0.0)
            ax.add_patch(FancyArrow(sx - dx, CALLOUT_Y + off - dy, dx * 2, dy * 2, width=0.0045 * span * 1.6,
                                    head_width=0.02, head_length=0.007 * span * 1.6 if dx else 0.018,
                                    length_includes_head=True, color=color, zorder=4))
        ax.annotate(f"{c.crash_id}\n{c.date}\nMP {c.mp:.2f}   {c.severity}", (sx, CALLOUT_Y - 0.075),
                    ha="center", va="top", fontsize=8, color="#333")
    ax.set_title(spec.title + ("\n" + spec.subtitle if spec.subtitle else ""), fontsize=12.5, pad=14)
    present = sorted({c.severity for c in ordered}, key=lambda s: SEV_RANK.get(s, 4))
    ax.legend(handles=[Line2D([0], [0], color=SEV_COLOR.get(s, "#1a1a1a"), lw=3, label=SEV_LABEL.get(s, s)) for s in present],
              loc="lower left", fontsize=9, framealpha=0.95, bbox_to_anchor=(0.0, 0.02))
    ax.text((X0 + X1) / 2, -0.30, spec.note, fontsize=8.5, ha="center", va="top", color="#444", wrap=True)
    ax.set_xlim(X0 - 0.005 * span, X1 + 0.03 * span)
    ax.set_ylim(-0.44, 0.62)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_stem + ".pdf")
    fig.savefig(out_stem + ".png", dpi=dpi)
    plt.close(fig)
    return {"pdf": out_stem + ".pdf", "png": out_stem + ".png", "crashes": len(ordered),
            "by_severity": {s: sum(1 for c in ordered if c.severity == s) for s in present}}
