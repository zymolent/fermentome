"""Run one tier over the frozen set. write=False and enqueue is never called.

Equivalent to `fermdb extract run --dry-run --no-enqueue`: `extract_publication(write=False)`
is exactly what --dry-run sets, and `curate.enqueue_extraction` is never reached.

The only departure from the stock CLI is the agent-sdk runner's `max_turns`, which the repo pins
at 1. On the real 42k-character payload schema that returns
`Reached maximum number of turns (1)` every time; raising it is what makes the capable arm run
at all. Nothing else is patched.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"D:\project\yeast-alcohol-db\src")

SCRATCH = Path(
    r"C:\Users\kangk\AppData\Local\Temp\claude\d--project-yeast-alcohol-db"
    r"\aa10009e-5f06-4ad6-a7a6-916cbbe63a58\scratchpad"
)

from fermdb.config import Settings  # noqa: E402
from fermdb.db import open_db  # noqa: E402
from fermdb.extract.harness import (  # noqa: E402
    DEFAULT_EXTRACTION_SECTIONS,
    extract_publication,
    load_source_text,
)
from fermdb.llm import providers as P  # noqa: E402


# ---- the one patch: max_turns -----------------------------------------------------------
_orig = P.claude_agent_sdk_runner


def _patched_runner(request):  # type: ignore[no-untyped-def]
    import asyncio

    import claude_agent_sdk as sdk

    P.subscription_credential()
    kw = {
        "system_prompt": (
            "You are an extraction backend. Reply with a single JSON object and nothing else."
        ),
        "allowed_tools": [],
        "disallowed_tools": [
            "Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep",
            "WebFetch", "WebSearch", "Agent", "Task", "Skill", "TodoWrite",
        ],
        "permission_mode": "dontAsk",
        "model": request.model,
        "max_turns": 8,
        "setting_sources": [],
        "env": {P.API_KEY_VAR: "", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "0"},
    }
    if request.schema is not None:
        kw["output_format"] = {"type": "json_schema", "schema": dict(request.schema)}

    async def _collect():
        texts, structured, result_text, usage, finish = [], None, "", None, None
        async for m in sdk.query(prompt=request.prompt, options=sdk.ClaudeAgentOptions(**kw)):
            if isinstance(m, sdk.AssistantMessage):
                for b in m.content:
                    if isinstance(b, sdk.TextBlock):
                        texts.append(str(b.text))
            elif isinstance(m, sdk.ResultMessage):
                finish = str(m.subtype)
                structured = getattr(m, "structured_output", None)
                raw = m.result
                result_text = raw if isinstance(raw, str) else json.dumps(raw)
                usage = getattr(m, "usage", None)
        text = json.dumps(structured) if isinstance(structured, dict) else (result_text or "\n".join(texts))
        return P.AgentReply(
            text=text,
            input_tokens=P._usage_count(usage, "input_tokens"),
            output_tokens=P._usage_count(usage, "output_tokens"),
            finish_reason=finish,
            model_version=request.model,
        )

    try:
        return asyncio.run(asyncio.wait_for(_collect(), request.timeout_s))
    except Exception as exc:
        raise P.ProviderUnavailableError(f"agent-sdk failed: {type(exc).__name__}: {exc}") from exc


P.claude_agent_sdk_runner = _patched_runner


def main() -> int:
    tier = sys.argv[1]  # "local" | "capable"
    n = int(sys.argv[2])
    max_chars = int(sys.argv[3])

    frozen = json.loads((SCRATCH / "frozen20.json").read_text(encoding="utf-8"))[:n]
    out_dir = SCRATCH / f"out_{tier}"
    out_dir.mkdir(exist_ok=True)

    settings = Settings.load()
    conn = open_db(settings.db_file)
    config = P.LlmConfig.load(settings)
    provider = (
        P.AgentSdkProvider(timeout_s=config.timeout_s)
        if tier == "capable"
        else P.build_provider(config)
    )

    for item in frozen:
        pid = item["publication_id"]
        dest = out_dir / (pid.replace(":", "_").replace("/", "_") + ".json")
        if dest.exists():
            print(f"[{tier}] {item['rank']:2d} cached {pid}", flush=True)
            continue
        t0 = time.monotonic()
        rec: dict = {"rank": item["rank"], "stratum": item["stratum"], "publication_id": pid}
        try:
            source_text, origin = load_source_text(conn, settings, publication_id=pid)
            outcome = extract_publication(
                conn,
                publication_id=pid,
                source_text=source_text,
                provider=provider,
                config=config,
                settings=settings,
                sections=DEFAULT_EXTRACTION_SECTIONS,
                cache=None,
                run_id=None,
                write=False,  # <- --dry-run; enqueue is never called anywhere in this file
                max_excerpt_chars=max_chars,
            )
            rec.update(
                status="ok",
                seconds=round(time.monotonic() - t0, 1),
                counts=outcome.counts_by_kind,
                record_count=outcome.record_count,
                excerpt_chars=outcome.excerpt.chars,
                document_chars=outcome.excerpt.document_chars,
                payload=outcome.payload,
                records=[[k, i, r] for k, i, r in outcome.records],
                notes=[[nn.record_path, nn.code, nn.message] for nn in outcome.notes],
                failed_attempts=[list(a) for a in outcome.failed_attempts],
                model=outcome.stats.model_version,
            )
        except Exception as exc:
            rec.update(
                status="error",
                seconds=round(time.monotonic() - t0, 1),
                error=f"{type(exc).__name__}: {exc}"[:600],
            )
        dest.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
        print(
            f"[{tier}] {item['rank']:2d} {rec['status']:5s} {rec.get('seconds')}s "
            f"{rec.get('counts', rec.get('error', ''))}",
            flush=True,
        )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
