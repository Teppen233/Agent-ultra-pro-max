# Greptile Benchmark Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display the ten completed Greptile runs as five two-case repository groups in the Benchmark page and open each saved run in the existing replay view.

**Architecture:** Make `backend-runs.json` a self-contained curated manifest with run, repository, and PR identity. A focused backend loader converts valid manifest rows into the existing Benchmark entry contract and falls back to the opt-in store when the manifest is absent. The Vue page groups those entries and routes completed cases to the existing Review replay view.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, Vue 3, TypeScript strict mode, Naive UI, Vitest.

## Global Constraints

- Use exactly the ten successful runs in `benchmark/results/backend-runs.json`.
- Group two cases under each of five repositories.
- Do not duplicate events, reports, or replay logic.
- Keep existing loading, empty, retry, and toast error states.
- Preserve the existing opt-in Benchmark collection as the no-manifest fallback.
- Run Python commands with `/Users/xuansama/miniforge3/envs/common/bin/python`.

---

### Task 1: Self-Contained Greptile Manifest and Backend Collection

**Files:**
- Create: `reviewcrew/server/greptile_benchmark.py`
- Modify: `benchmark/run_backend.py`
- Modify: `benchmark/results/backend-runs.json`
- Modify: `reviewcrew/server/benchmark.py`
- Modify: `reviewcrew/server/app.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: manifest rows with `run_id`, `name`, `status`, `repo`, and `pr_url`.
- Produces: `load_greptile_entries(manifest_path: Path, runs_dir: Path, active_run_ids: set[str]) -> list[BenchmarkEntry]`.

- [x] **Step 1: Write failing API tests**

Create two completed run directories and a two-row manifest, then assert `/api/benchmark/entries` returns capacity `10`, the names and PR identities in manifest order, and `/api/benchmark/entries/{run_id}` returns the saved run. Also assert an ID outside the manifest returns `404`.

- [x] **Step 2: Verify the focused tests fail**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_server.py -k greptile -q`

Expected: failure because the server still reads only `selected.json`.

- [x] **Step 3: Implement manifest validation and fallback selection**

Define a Pydantic manifest row model and use the existing GitHub PR parser to construct `BenchmarkEntry` values. Add optional `name` to `BenchmarkEntry`, calculate ready/running/reserved state from run artifacts, return curated entries when the manifest exists, and otherwise call `BenchmarkStore.list_entries()`.

- [x] **Step 4: Make future runner output self-contained**

Return the following fields from `benchmark/run_backend.py::execute` and its existing-run path:

```python
{
    "run_id": run_id,
    "name": name,
    "status": status,
    "repo": entry.repo,
    "pr_url": entry.pr_url,
}
```

Update the current ten-row manifest with the matching `repo` and `pr_url` values.

- [x] **Step 5: Run backend tests**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_server.py -q`

Expected: all server tests pass, including the existing empty-store fallback tests.

### Task 2: Five-Repository Benchmark Browser

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/views/BenchmarkView.vue`
- Test: `web/src/views/BenchmarkView.test.ts`

**Interfaces:**
- Consumes: `BenchmarkEntrySummary.name?: string | null` from `/api/benchmark/entries`.
- Produces: repository groups containing ordered `BenchmarkEntrySummary[]` and replay links to `/review/:runId`.

- [x] **Step 1: Write failing component test**

Build ten fixture entries across five repositories and assert the rendered page contains five `.repository-group` elements, ten `.repository-item` buttons, `10 / 10`, `评测任务`, the persisted case names, and `/review/{run_id}` on the selected case replay link.

- [x] **Step 2: Verify the component test fails**

Run: `npm test -- --run web/src/views/BenchmarkView.test.ts`

Working directory: `web`

Expected: failure because entries are currently rendered as a flat repository list and the copy still says `仓库名额`.

- [x] **Step 3: Implement grouped rendering**

Add a computed map that preserves API order:

```ts
const repositoryGroups = computed(() => {
  const groups = new Map<string, BenchmarkEntrySummary[]>()
  for (const entry of entries.value) {
    groups.set(entry.repository, [...(groups.get(entry.repository) ?? []), entry])
  }
  return [...groups.entries()].map(([repository, cases]) => ({ repository, cases }))
})
```

Render a repository heading followed by its two case buttons. Use the saved case name as the primary row label, show repository and PR context as secondary text, change the counter label to `评测任务`, and label the existing route link `回放完整审计`.

- [x] **Step 4: Preserve responsive behavior**

Keep the existing two-column desktop layout and its current mobile breakpoint. Bound group labels and case names with ellipsis so the long Keycloak title cannot resize the sidebar.

- [x] **Step 5: Run frontend checks**

Run from `web`: `npm run typecheck && npm run lint && npm test`

Expected: type checking, ESLint, and all Vitest tests pass.

### Task 3: Live Integration Verification

**Files:**
- Verify: `benchmark/results/backend-runs.json`
- Verify: `runs/<run_id>/events.jsonl`

**Interfaces:**
- Consumes: the running backend at `http://127.0.0.1:8000`.
- Produces: a working ten-case Benchmark API and replay navigation for every ready run.

- [x] **Step 1: Run repository-wide focused checks**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest -q`

Run: `git diff --check`

Expected: all tests pass and no whitespace errors are reported.

- [x] **Step 2: Restart the backend with the new loader**

Start: `/Users/xuansama/miniforge3/envs/common/bin/python -m uvicorn reviewcrew.server.app:app --host 127.0.0.1 --port 8000`

Expected: `/api/health` returns `{ "status": "ok" }`.

- [x] **Step 3: Verify the live collection**

Request `/api/benchmark/entries` and assert `capacity == 10`, `count == 10`, five unique repositories exist, every repository has two entries, and every entry is `ready`.

- [x] **Step 4: Verify replay data**

For each returned `run_id`, request `/api/runs/{run_id}` and assert at least one report event exists. Open the Benchmark page and confirm selecting a case updates the detail panel and `回放完整审计` opens its saved run.
