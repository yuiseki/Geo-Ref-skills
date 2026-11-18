# uvx --with pytest python -m pytest agents/test_codex_trace.py
import json
from datetime import datetime, timedelta, timezone

import pytest

import codex_trace

T0 = datetime(2026, 11, 18, tzinfo=timezone.utc)


def _rollout(path, steps):
    """steps: (seconds, tool input, context the next model call reads); one model call before the first tool call."""
    lines, t, total = [], T0, 0

    def count(ctx):
        nonlocal total
        total += ctx
        return {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": ctx}, "total_token_usage": {"input_tokens": total}}}}
    lines.append(count(steps[0][2]))
    for i, (secs, call, ctx) in enumerate(steps[1:], 1):
        lines.append({"timestamp": t.isoformat(), "type": "response_item",
                      "payload": {"type": "custom_tool_call", "call_id": str(i), "input": call}})
        t += timedelta(seconds=secs)
        lines.append({"timestamp": t.isoformat(), "type": "response_item",
                      "payload": {"type": "custom_tool_call_output", "call_id": str(i), "output": "x"}})
        lines.append(count(ctx))
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))


def test_breakdown_splits_the_input_into_fixed_polling_and_reading(tmp_path):
    f = tmp_path / "s.jsonl"
    _rollout(f, [
        (0, "", 100),                                                                   # first call: the fixed part
        (1, 'tools.exec_command({cmd:"cat .agents/skills/a/SKILL.md"})', 150),          # +50 from a SKILL.md
        (2, 'tools.exec_command({cmd:"sed -n 1,99p .agents/skills/a/scripts/b.py"})', 170),  # +20 from source
        (30, 'tools.exec_command({cmd:"python3 b.py"})', 175),
        (30, 'tools.write_stdin({session_id:1,chars:"",yield_time_ms:30000})', 180),   # a poll
    ])
    b = codex_trace.breakdown(f)
    assert b["calls"] == 5 and b["total"] == 100 + 150 + 170 + 175 + 180
    assert b["fixed"] == 500                      # 100 read again by each of the 5 calls
    assert b["poll"] == 180                       # the call that reads the poll's output
    assert b["polls"] == 1
    assert b["doc"] == 50 * 4                     # the 50 is read by the 4 calls from then on
    assert b["src"] == 20 * 3
    assert b["longest_s"] == pytest.approx(30)


def test_shares_add_the_runs_before_dividing():
    rows = [{"total": 100, "fixed": 50, "poll": 0, "doc": 10, "src": 0},
            {"total": 300, "fixed": 50, "poll": 150, "doc": 30, "src": 30}]
    assert codex_trace.shares(rows) == {"fixed": 0.25, "poll": 0.375, "doc": 0.1, "src": 0.075}
