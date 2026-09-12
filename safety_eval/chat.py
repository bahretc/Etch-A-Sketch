"""Assistant chat over an evaluation package (docs/07, phase 5: drafts only).

The assistant answers questions about a package and drafts text in the docs/05
style, using tools that call the same functions the UI and CLI use: QA checks,
NCDOT AADT station lookups, workbook cell reads, style checks. It never edits a
deliverable; the engineer applies changes through the other pages.

Runs on Claude Opus 5 through the official SDK with adaptive thinking and a
tool loop. Without an API key the page still loads and says so.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-5"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are the review assistant inside an NCDOT HSIP safety evaluation tool used by a licensed PE.
You help check and draft, the engineer decides. Rules you must keep:
- NCDOT methodology only: EPDO K/A 76.8, B/C 8.4, PDO 1.0; Y-line 150 ft for intersections; 2020 is never a representative AADT year; the representative year is the last year in a period with published AADT on any leg.
- AADT table colours: black for NCDOT published values, red for interpolated, carried forward or assumed values; minor road estimates round to the nearest hundred.
- Report text is plain and understated: no em dashes or en dashes anywhere, no flourishes; use commas, periods, colons, parentheses.
- Intersection studies are road-combination dependent, strip studies are milepost dependent.
- Never claim a check was run unless a tool returned it. Quote cell addresses and file names when you cite evidence.
- When asked to draft Items for Discussion or similar text, draft it as bullets the engineer can paste, then run the style check tool on it.
Keep answers short and concrete."""


@dataclass
class ChatTurn:
    role: str
    text: str
    tool_calls: list = field(default_factory=list)   # [(name, input, result)]


def _tool_defs() -> list[dict]:
    return [
        {"name": "run_qa_checks",
         "description": "Run the deterministic QA checks on an evaluation workbook and, optionally, "
                        "its deliverable PDFs. Returns findings and what was verified.",
         "input_schema": {"type": "object", "properties": {
             "workbook": {"type": "string", "description": "Path to the evaluation workbook (.xlsx)"},
             "reference": {"type": "string", "description": "Optional original/template workbook for the drawings gate"},
             "complete_pdf": {"type": "string"}, "web_pdf": {"type": "string"}},
             "required": ["workbook"], "additionalProperties": False}, "strict": True},
        {"name": "query_aadt_stations",
         "description": "NCDOT AADT stations near a point (lon, lat) from the 2025 station layer; "
                        "returns station id, location and yearly AADTs.",
         "input_schema": {"type": "object", "properties": {
             "lon": {"type": "number"}, "lat": {"type": "number"},
             "radius_m": {"type": "number", "description": "search radius in metres, default 2400"}},
             "required": ["lon", "lat"], "additionalProperties": False}, "strict": True},
        {"name": "read_cells",
         "description": "Read cached values of a cell range from a workbook sheet, e.g. 'Evaluation Set-up' K9:R35.",
         "input_schema": {"type": "object", "properties": {
             "workbook": {"type": "string"}, "sheet": {"type": "string"},
             "cell_range": {"type": "string"}},
             "required": ["workbook", "sheet", "cell_range"], "additionalProperties": False}, "strict": True},
        {"name": "style_check",
         "description": "Check draft report text against the docs/05 style rules (dashes, placeholders).",
         "input_schema": {"type": "object", "properties": {"text": {"type": "string"}},
                          "required": ["text"], "additionalProperties": False}, "strict": True},
    ]


def _run_tool(name: str, inp: dict, allowed_dirs: list[str] | None) -> str:
    def _check_path(p: str) -> str:
        p = os.path.abspath(p)
        if allowed_dirs and not any(p.startswith(os.path.abspath(d)) for d in allowed_dirs):
            raise PermissionError(f"{p} is outside the allowed folders")
        if not os.path.exists(p):
            raise FileNotFoundError(p)
        return p

    if name == "run_qa_checks":
        from .qa_checks import format_report, run_package_checks
        rep = run_package_checks(_check_path(inp["workbook"]),
                                 _check_path(inp["reference"]) if inp.get("reference") else None,
                                 _check_path(inp["complete_pdf"]) if inp.get("complete_pdf") else None,
                                 _check_path(inp["web_pdf"]) if inp.get("web_pdf") else None)
        return format_report(rep)
    if name == "query_aadt_stations":
        from .aadt_arcgis import query_stations
        stations = query_stations(point=(float(inp["lon"]), float(inp["lat"])),
                                  radius_meters=float(inp.get("radius_m") or 2400))
        return json.dumps([{"station_id": s.station_id, "route": s.route, "location": s.location,
                            "years": {str(k): v for k, v in sorted(s.years.items())}} for s in stations])
    if name == "read_cells":
        import openpyxl
        wb = openpyxl.load_workbook(_check_path(inp["workbook"]), data_only=True, read_only=True)
        ws = wb[inp["sheet"]]
        rows = []
        for row in ws[inp["cell_range"]]:
            rows.append({c.coordinate: c.value for c in row if c.value is not None})
        return json.dumps(rows, default=str)
    if name == "style_check":
        from .qa_checks import DASHES
        text = inp["text"]
        problems = [f"{n} at position {text.index(ch)}" for ch, n in DASHES.items() if ch in text]
        return "OK: no em or en dashes." if not problems else "Style problems: " + "; ".join(problems)
    raise ValueError(f"unknown tool {name}")


class Assistant:
    """Multi-turn assistant with a manual tool loop (keeps every turn's tool
    calls so the UI can show them)."""

    def __init__(self, client=None, model: str = DEFAULT_MODEL, allowed_dirs: list[str] | None = None,
                 effort: str = "high", use_fallbacks: bool = True):
        self.client = client
        self.model = model
        self.allowed_dirs = allowed_dirs
        self.effort = effort
        self.use_fallbacks = use_fallbacks
        self.messages: list[dict] = []
        self.turns: list[ChatTurn] = []

    @staticmethod
    def available() -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def _client(self):
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic()
        return self.client

    def _create(self, **kw):
        client = self._client()
        if self.use_fallbacks:
            try:
                return client.beta.messages.create(betas=[_FALLBACK_BETA], fallbacks="default", **kw)
            except Exception as exc:  # noqa: BLE001 - unsupported beta on this account/platform
                if "fallback" not in str(exc).lower() and "beta" not in str(exc).lower():
                    raise
                self.use_fallbacks = False
        return client.messages.create(**kw)

    def send(self, user_text: str, max_tool_rounds: int = 8) -> ChatTurn:
        self.messages.append({"role": "user", "content": user_text})
        self.turns.append(ChatTurn("user", user_text))
        calls = []
        text = ""
        for _ in range(max_tool_rounds + 1):
            resp = self._create(model=self.model, max_tokens=16000, system=SYSTEM_PROMPT,
                                thinking={"type": "adaptive"}, output_config={"effort": self.effort},
                                tools=_tool_defs(), messages=self.messages)
            if resp.stop_reason == "refusal":
                text = "The model declined this request" + (
                    f" ({resp.stop_details.category})." if getattr(resp, "stop_details", None) else ".")
                self.messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
                break
            self.messages.append({"role": "assistant", "content": resp.content})
            text = "".join(b.text for b in resp.content if b.type == "text")
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not tool_uses:
                break
            results = []
            for tu in tool_uses:
                try:
                    out = _run_tool(tu.name, dict(tu.input), self.allowed_dirs)
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
                    calls.append((tu.name, dict(tu.input), out))
                except Exception as exc:  # noqa: BLE001 - reported back to the model
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": f"Error: {exc}", "is_error": True})
                    calls.append((tu.name, dict(tu.input), f"Error: {exc}"))
            self.messages.append({"role": "user", "content": results})
        turn = ChatTurn("assistant", text, calls)
        self.turns.append(turn)
        return turn
