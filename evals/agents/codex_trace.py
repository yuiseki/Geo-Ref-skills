"""Where the input tokens of a Codex run go, from the session file the bench copies into the run.

Every model call reads the whole conversation again, so a run's input is the sum, over its calls, of
the context each one reads. This splits that sum:

  fixed  the first call's context (system prompt, task prompt, AGENTS.md) read again by every call
  poll   the calls that only read the output of an empty write_stdin, that is, a look at a command
         still running (Codex hands a command back after its yield_time_ms)
  doc    what reading a .md (SKILL.md, AGENTS.md) added to the context, times the calls that read it again
  src    the same for reading source code (.py) with cat, sed or head

fixed and poll overlap (a poll reads the fixed part too); doc and src do not overlap with each other.

    python3 evals/agents/codex_trace.py tmp/agent-bench/runs/codex/skills/L6*
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

POLL = re.compile(r'write_stdin\(\{[^}]*chars:\s*""')
DOC = re.compile(r"(cat|sed|head|less|rg|grep)[^|;]*\.md\b")
SRC = re.compile(r"(cat|sed -n|head)[^|;]*\.py\b")


def _time(e):
    t = e.get("timestamp")
    return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None


def breakdown(path):
    ctx, kinds, started, longest = [], [], {}, 0.0
    kind = None
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        p = e.get("payload", {}) if isinstance(e, dict) else {}
        if p.get("type") == "custom_tool_call":
            call = str(p.get("input"))
            kind = "poll" if POLL.search(call) else "doc" if DOC.search(call) else "src" if SRC.search(call) else "other"
            started[p.get("call_id")] = _time(e)
        elif p.get("type") == "custom_tool_call_output":
            t0, t1 = started.pop(p.get("call_id"), None), _time(e)
            if t0 and t1:
                longest = max(longest, (t1 - t0).total_seconds())
        elif p.get("type") == "token_count" and p.get("info"):
            ctx.append(p["info"]["last_token_usage"]["input_tokens"])
            kinds.append(kind)  # what the call before this model call was
            kind = None
    n = len(ctx)
    out = {"calls": n, "total": sum(ctx), "fixed": ctx[0] * n if n else 0, "poll": 0, "polls": 0,
           "doc": 0, "src": 0, "longest_s": longest}
    for i in range(1, n):
        if kinds[i] == "poll":
            out["poll"] += ctx[i]
            out["polls"] += 1
        elif kinds[i] in ("doc", "src"):
            out[kinds[i]] += (ctx[i] - ctx[i - 1]) * (n - i)
    return out


def shares(rows):
    total = sum(r["total"] for r in rows)
    return {k: sum(r[k] for r in rows) / total for k in ("fixed", "poll", "doc", "src")}


def main(dirs):
    groups = {}
    print("run\tcalls\ttotal\tfixed\tpoll\tpolls\tdoc\tsrc\tlongest_s")
    for d in map(Path, dirs):
        f = d / "codex-session.jsonl"
        if not f.exists():
            continue
        b = breakdown(f)
        groups.setdefault(d.parent.parent.name + "/" + d.parent.name, []).append(b)
        print("\t".join(str(v) for v in ["/".join(d.parts[-3:]), *(round(x) if isinstance(x, float) else x for x in b.values())]))
    for g, rows in groups.items():
        print(g, len(rows), "runs, share of input:", " ".join(f"{k} {v:.2f}" for k, v in shares(rows).items()))


if __name__ == "__main__":
    main(sys.argv[1:])
