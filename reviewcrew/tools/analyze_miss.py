from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from reviewcrew.server.replay import load_events_jsonl

Attribution = Literal["context_missing", "prompt_blind", "verifier_reject", "judge_error"]


class MissAnalysis(BaseModel):
    run_id: str
    expected_bug: str
    attribution: Attribution
    explanation: str


def analyze_miss(run_id: str, expected_bug: str, runs_dir: Path = Path("runs")) -> MissAnalysis:
    events = load_events_jsonl(runs_dir / run_id / "events.jsonl")
    findings = [event.finding for event in events if event.finding is not None]
    verdicts = {event.verdict.finding_id: event.verdict for event in events if event.verdict}

    rejected = [
        finding
        for finding in findings
        if verdicts.get(finding.id) and verdicts[finding.id].verdict == "reject"
    ]
    kept = [
        finding
        for finding in findings
        if verdicts.get(finding.id) and verdicts[finding.id].verdict == "keep"
    ]
    tool_events = [event for event in events if event.type == "tool"]

    if rejected:
        attribution: Attribution = "verifier_reject"
        explanation = f"{len(rejected)} candidate finding(s) were rejected by the verifier."
    elif kept:
        attribution = "judge_error"
        explanation = f"{len(kept)} verified finding(s) exist; inspect benchmark matching rules."
    elif not tool_events:
        attribution = "context_missing"
        explanation = "No evidence-gathering tool calls were recorded for the run."
    else:
        attribution = "prompt_blind"
        explanation = (
            "Agents gathered evidence but emitted no candidate matching the expected defect."
        )

    return MissAnalysis(
        run_id=run_id,
        expected_bug=expected_bug,
        attribution=attribution,
        explanation=explanation,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attribute a missed benchmark case from run events."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-bug", required=True)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    print(analyze_miss(args.run_id, args.expected_bug, args.runs_dir).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
