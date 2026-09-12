"""chat: tool loop with a fake client (no network, no key)."""
import json
from types import SimpleNamespace

from safety_eval.chat import Assistant, _run_tool, _tool_defs


class _Block(SimpleNamespace):
    pass


class _FakeClient:
    """First call asks for the style_check tool, second call answers."""

    def __init__(self):
        self.calls = []
        self.messages = self
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._beta_create))

    def _beta_create(self, **kw):
        raise RuntimeError("beta server-side-fallback not available on this account")

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[
                _Block(type="text", text="Checking the draft."),
                _Block(type="tool_use", id="tu1", name="style_check",
                       input={"text": "Before crashes fell – after they rose."})])
        return SimpleNamespace(stop_reason="end_turn",
                               content=[_Block(type="text", text="The draft has an en dash; replace it with a comma.")])


def test_tool_loop_runs_tools_and_records_them():
    client = _FakeClient()
    asst = Assistant(client=client, use_fallbacks=True)
    turn = asst.send("Check this draft")
    assert turn.role == "assistant" and "en dash" in turn.text
    assert turn.tool_calls[0][0] == "style_check" and "en dash" in turn.tool_calls[0][2]
    assert asst.use_fallbacks is False            # beta refused, fell back to messages.create
    assert len(client.calls) == 2
    assert client.calls[0]["thinking"] == {"type": "adaptive"}
    assert client.calls[0]["model"] == "claude-opus-5"
    # tool results went back as a user message with the tool_use id
    last_user = [m for m in client.calls[1]["messages"] if m["role"] == "user"][-1]
    assert last_user["content"][0]["tool_use_id"] == "tu1"


def test_tool_definitions_are_strict():
    for t in _tool_defs():
        assert t["strict"] is True
        assert t["input_schema"]["additionalProperties"] is False


def test_style_and_read_cells_tools(tmp_path):
    assert _run_tool("style_check", {"text": "plain text"}, None).startswith("OK")
    assert "em dash" in _run_tool("style_check", {"text": "a — b"}, None)
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "S"
    wb.active["A1"] = 5
    p = tmp_path / "w.xlsx"
    wb.save(p)
    rows = json.loads(_run_tool("read_cells", {"workbook": str(p), "sheet": "S", "cell_range": "A1:B2"}, [str(tmp_path)]))
    assert rows[0] == {"A1": 5}
    import pytest
    with pytest.raises(PermissionError):
        _run_tool("read_cells", {"workbook": str(p), "sheet": "S", "cell_range": "A1"}, ["/nonexistent"])


def test_available_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert Assistant.available() is False
