"""Replay the shared test scenarios and write a markdown transcript.

    python tests/run_scenarios.py --version 2            # Gemini if a key is set, else offline
    python tests/run_scenarios.py --version 2 --offline  # force the rule-based path
    python tests/run_scenarios.py --version 1            # needs GEMINI_API_KEY

The result is written to docs/results_v<N>.md so you can paste observed behaviour
into your report. Nothing here is hard-coded: it records what the system actually did.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from scenarios import SCENARIOS, SECRETS  # noqa: E402

from common import llm_client  # noqa: E402


def run_v1() -> list[dict]:
    from v1.game import GameSession

    rows = []
    for sc in SCENARIOS:
        session = GameSession()
        turns = []
        for msg in sc["messages"]:
            reply = session.send(msg)
            turns.append((msg, reply, ""))
            time.sleep(1)  # be gentle with the free tier
        rows.append({"sc": sc, "turns": turns, "escaped": session.escaped})
    return rows


def run_v2(offline: bool) -> list[dict]:
    from v2.game_master import GameMaster

    rows = []
    for sc in SCENARIOS:
        gm = GameMaster(use_llm=False if offline else None)
        turns = []
        for msg in sc["messages"]:
            out = gm.step(msg)
            note = f"action={out['action']['action']}, engine={out['result']['code']}, state_changed={out['result']['state_changed']}"
            turns.append((msg, out["narration"], note))
        rows.append({"sc": sc, "turns": turns, "escaped": gm.engine.state["escaped"]})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, choices=(1, 2), required=True)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    if args.version == 1 and not llm_client.is_configured():
        sys.exit("Version 1 needs GEMINI_API_KEY (see .env.example).")

    rows = run_v1() if args.version == 1 else run_v2(args.offline)
    mode = "offline rules" if (args.version == 2 and (args.offline or not llm_client.is_configured())) else f"Gemini ({llm_client.model_name()})"

    lines = [f"# Scenario results - Version {args.version}", "", f"Mode: {mode}  ", f"Run at: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    summary = ["| Test | Escaped? | Secret shown? |", "|---|---|---|"]
    for r in rows:
        sc = r["sc"]
        text = " ".join(t[1] for t in r["turns"])
        leaked = [s for s in SECRETS if s in text]
        summary.append(f"| {sc['id']} {sc['title']} | {'YES (bad)' if r['escaped'] else 'no'} | {'YES: ' + ', '.join(leaked) if leaked else 'no'} |")
        lines += [f"## {sc['id']} - {sc['title']}", ""]
        for msg, reply, note in r["turns"]:
            lines += [f"**Player:** {msg}", "", f"**Game Master:** {reply}", ""]
            if note:
                lines += [f"_{note}_", ""]
    lines[5:5] = summary + [""]
    out = ROOT / "docs" / f"results_v{args.version}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(summary))
    print(f"\nWrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
