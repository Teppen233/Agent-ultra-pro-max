# ReviewCrew Benchmark Iteration Log

## Status

- Date: 2026-07-29
- Model configuration: `deepseek-v4-pro` through an OpenAI-compatible endpoint
- Licensed dataset entries: 0
- Formal baseline: not run
- Freeze status: not eligible

No hit-rate, false-positive, or latency figure is recorded because `benchmark/dataset.yaml` has no authorized entries. The built-in Replay and fake runner are contract checks, not evaluation evidence.

## Harness Validation

### Iteration H0

Change: implemented deterministic fake runner, JSONL result writer, summary generator, line-overlap judge and dependency-injected semantic matcher.

Decision: keep. This establishes a testable harness without inventing benchmark records.

### Iteration H1

Change: connected `--runner real` to the production Orchestrator and added a structured LLM semantic judge for cases without line overlap.

Decision: keep. Formal execution remains pending an authorized manifest, cloneable forks and model budget.

### Iteration H2

Change: added `reviewcrew.tools.analyze_miss` to classify verifier rejection, possible judge error, missing evidence and prompt blind spots from `events.jsonl`.

Decision: keep. Unit coverage verifies verifier-rejection attribution.

## Formal Baseline Template

Fill this section only after a complete `--full --runner real` run.

```text
Date:
Result directory:
Dataset revision:
Model:
Hit rate:
Average findings:
Average duration:
Weakest category:
Miss attribution summary:
Decision:
```

## Iteration Rule

For each real iteration:

1. Link the exact result directory and dataset revision.
2. Attribute every miss using run events plus manual review.
3. Change one variable only.
4. Run quick evaluation and compare with the preceding baseline.
5. Keep the change only when evidence improves; then confirm with full evaluation.
6. Freeze only after two consecutive full runs meet all targets.
