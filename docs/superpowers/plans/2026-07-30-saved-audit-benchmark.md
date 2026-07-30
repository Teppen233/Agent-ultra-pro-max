# Saved Audit Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users opt a normal GitHub PR audit into a persistent five-repository Benchmark collection and inspect that run's existing findings without rerunning it.

**Architecture:** A focused backend store owns an atomic JSON index and enforces capacity plus repository uniqueness. The review endpoint reserves an entry before launching work, promotes it on success, and removes it on failure; read APIs combine index metadata with existing run artifacts. The Vue frontend adds an opt-in checkbox and replaces the harness demo dashboard with a saved-run selector and finding browser.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, Vue 3, TypeScript strict mode, Pinia, Naive UI, lucide-vue-next, Vitest, CSS design tokens.

## Global Constraints

- Benchmark contains at most five entries and at most one PR per repository.
- Selecting an entry displays the original audit result and never starts a new audit.
- Existing `/api/benchmark/latest` harness behavior remains compatible.
- Local diff-only submissions cannot opt into Benchmark.
- Do not expose or commit `.env`; do not add `runs/`, `repos/`, or `rushgogogo/`.
- Preserve unrelated `presentation-assets/` and `reviewcrew-ai-code-review-story.html` files.
- Target Windows desktop and keep narrower layouts usable.
- Follow existing Vue, Pinia, and Naive UI patterns; do not add another state or component library.
- Use CSS design tokens, no inline styles, no raw hex colors, and no TypeScript `any`.
- Use skeletons for loading, toasts for errors, guided empty states, and hover/active feedback.
- Run Python through `/Users/xuansama/miniforge3/envs/common/bin/python`.
- Do not restart the running backend while active reviews still depend on it.

---

## File Structure

- Create `reviewcrew/server/benchmark.py` for typed entries, atomic persistence, limits, transitions, and stale cleanup.
- Modify `reviewcrew/server/app.py` for request opt-in, lifecycle integration, and collection APIs.
- Create `tests/test_benchmark_store.py` and extend `tests/test_server.py`.
- Modify `web/src/types.ts` and `web/src/stores/review.ts` for typed capacity and request state.
- Modify `web/src/components/ReviewForm.vue` and `web/src/views/ReviewView.vue` for opt-in UI.
- Replace `web/src/views/BenchmarkView.vue` with the saved-result browser.
- Extend store/form tests and create `web/src/views/BenchmarkView.test.ts`.

---

### Task 1: Persistent Benchmark Index

**Files:**
- Create: `reviewcrew/server/benchmark.py`
- Create: `tests/test_benchmark_store.py`

**Interfaces:**
- Consumes: `github_repository(value: str) -> tuple[str, str] | None`.
- Produces: `BenchmarkEntry`, `BenchmarkConflict`, `BenchmarkInputError`, `BenchmarkStore(index_path: Path, runs_dir: Path, capacity: int = 5)`, and its `list_entries`, `get`, `reserve`, `mark_running`, `mark_ready`, and `remove` methods.

- [ ] **Step 1: Write failing identity, persistence, uniqueness, and capacity tests**

```python
def test_store_reserves_and_reloads_entry(tmp_path: Path) -> None:
    store = BenchmarkStore(tmp_path / "selected.json", tmp_path / "runs")
    entry = store.reserve("run-1", "https://github.com/Owner/Repo/pull/42")
    assert (entry.repository, entry.repository_name, entry.pr_number) == ("owner/repo", "repo", 42)
    assert BenchmarkStore(store.index_path, tmp_path / "runs").list_entries(set())[0].run_id == "run-1"

def test_store_rejects_duplicate_and_sixth_repository(tmp_path: Path) -> None:
    store = BenchmarkStore(tmp_path / "selected.json", tmp_path / "runs")
    store.reserve("run-1", "https://github.com/acme/repo-1/pull/1")
    with pytest.raises(BenchmarkConflict, match="已存在"):
        store.reserve("duplicate", "https://github.com/acme/repo-1/pull/2")
    for index in range(2, 6):
        store.reserve(f"run-{index}", f"https://github.com/acme/repo-{index}/pull/{index}")
    with pytest.raises(BenchmarkConflict, match="已满"):
        store.reserve("run-6", "https://github.com/acme/repo-6/pull/6")
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_benchmark_store.py -q`

Expected: collection fails because `reviewcrew.server.benchmark` does not exist.

- [ ] **Step 3: Implement typed entries and atomic persistence**

```python
class BenchmarkEntry(BaseModel):
    run_id: str
    repository: str
    repository_name: str
    pr_url: str
    pr_number: int
    status: Literal["reserved", "running", "ready"] = "reserved"
    created_at: float
    completed_at: float | None = None

class BenchmarkStore:
    def reserve(self, run_id: str, pr_url: str) -> BenchmarkEntry:
        identity = parse_pull_request(pr_url)
        with self._lock:
            entries = self._read()
            if any(item.repository == identity.repository for item in entries):
                raise BenchmarkConflict(f"仓库 {identity.repository} 已存在于 Benchmark。")
            if len(entries) >= self.capacity:
                raise BenchmarkConflict("Benchmark 已满，最多只能添加 5 个仓库。")
            entry = BenchmarkEntry(run_id=run_id, **identity.model_dump(), created_at=time.time())
            self._write([*entries, entry])
            return entry
```

Use a module-level path-keyed `threading.RLock`. Validate all JSON with Pydantic, and write through `NamedTemporaryFile` followed by `Path.replace`. Invalid PR input raises `BenchmarkInputError`; malformed JSON raises a readable store error and is never overwritten.

- [ ] **Step 4: Add transition, removal, corrupt-index, and stale-reservation coverage**

```python
store.reserve("run-1", PR_URL)
assert store.mark_running("run-1").status == "running"
assert store.mark_ready("run-1").completed_at is not None
store.remove("run-1")
assert store.list_entries(set()) == []
```

`list_entries(active_run_ids)` keeps ready entries, keeps active non-ready entries, promotes entries with `report.md`, and removes inactive non-ready entries with no report. `get` returns only an indexed entry.

- [ ] **Step 5: Run tests and commit**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_benchmark_store.py -q`

Expected: all store tests pass.

```bash
git add reviewcrew/server/benchmark.py tests/test_benchmark_store.py
git commit -m "feat: add persistent benchmark collection"
```

---

### Task 2: Review Lifecycle And Benchmark APIs

**Files:**
- Modify: `reviewcrew/server/app.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: Task 1's store and errors.
- Produces: `ReviewRequest.add_to_benchmark: bool`, `GET /api/benchmark/entries`, and `GET /api/benchmark/entries/{run_id}`.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_benchmark_entries_start_empty(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs", tmp_path / "benchmark"))
    assert client.get("/api/benchmark/entries").json() == {
        "capacity": 5, "count": 0, "entries": []
    }

def test_benchmark_opt_in_rejects_non_github_input(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / "runs", tmp_path / "benchmark")).post(
        "/api/review",
        json={"pr_url": "/tmp/change.diff", "repo_path": "/tmp/repo", "add_to_benchmark": True},
    )
    assert response.status_code == 422
    assert "GitHub PR" in response.json()["detail"]
```

Also test `409` for duplicate/full collections and prove the omitted flag retains the existing `202` contract.

- [ ] **Step 2: Run server tests and verify the new cases fail**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_server.py -q`

- [ ] **Step 3: Reserve before launching the review task**

```python
class ReviewRequest(BaseModel):
    pr_url: str = Field(min_length=1)
    repo_path: str | None = None
    add_to_benchmark: bool = False

if request.add_to_benchmark:
    try:
        benchmark_store.reserve(run_id, request.pr_url)
    except BenchmarkConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except BenchmarkInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
```

Create one store in `create_app`. Mark running after task creation, mark ready after `Orchestrator.review` completes and a report exists, and remove the reservation in the exception path before recording the run error.

- [ ] **Step 4: Add collection and selected-detail endpoints**

```python
@application.get("/api/benchmark/entries")
async def benchmark_entries() -> dict[str, object]:
    entries = benchmark_store.list_entries(application.state.active_run_ids)
    return {"capacity": benchmark_store.capacity, "count": len(entries), "entries": dump(entries)}
```

Extract existing run-detail construction to a local helper shared by `/api/runs/{run_id}` and `/api/benchmark/entries/{run_id}`. The selected endpoint returns `{ "entry": ..., "run": ... }`; unknown entries and missing artifacts return `404`.

- [ ] **Step 5: Test success promotion and failure cleanup**

Use the existing monkeypatch pattern for `prepare_repository` and `Orchestrator.review`. The success fake writes a report event plus `report.md` and must yield `ready`; the failure fake raises during preparation and must leave the collection empty while retaining the failed run.

- [ ] **Step 6: Run API/store tests and commit**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_server.py tests/test_benchmark_store.py -q`

```bash
git add reviewcrew/server/app.py tests/test_server.py
git commit -m "feat: connect audits to benchmark collection"
```

---

### Task 3: Audit Form Opt-In And Capacity State

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/stores/review.ts`
- Modify: `web/src/stores/review.test.ts`
- Modify: `web/src/components/ReviewForm.vue`
- Modify: `web/src/components/ReviewForm.test.ts`
- Modify: `web/src/views/ReviewView.vue`

**Interfaces:**
- Consumes: Task 2's list API and request flag.
- Produces: `BenchmarkEntrySummary`, `BenchmarkCollection`, `loadBenchmarkCapacity()`, and `startReview(prUrl, repoPath, addToBenchmark)`.

- [ ] **Step 1: Add failing store tests for capacity and payload**

```typescript
expect(JSON.parse(String(request?.body))).toEqual({
  pr_url: 'https://github.com/owner/repo/pull/42',
  repo_path: null,
  add_to_benchmark: true,
})
await store.loadBenchmarkCapacity()
expect([store.benchmarkCount, store.benchmarkCapacity]).toEqual([4, 5])
```

- [ ] **Step 2: Add strict contracts and store actions**

```typescript
export interface BenchmarkEntrySummary {
  run_id: string
  repository: string
  repository_name: string
  pr_url: string
  pr_number: number
  status: 'reserved' | 'running' | 'ready'
  created_at: number
  completed_at: number | null
}

export interface BenchmarkCollection {
  capacity: number
  count: number
  entries: BenchmarkEntrySummary[]
}
```

Initialize capacity to `5`, include `add_to_benchmark` in every review request, and refresh capacity after an opted-in request is accepted without resetting the active review state.

- [ ] **Step 3: Add failing form tests for checked emission and full capacity**

```typescript
const wrapper = mount(ReviewForm, {
  props: { loading: false, benchmarkCount: 4, benchmarkCapacity: 5 },
})
await wrapper.get('[aria-label="加入 Benchmark"]').setValue(true)
await wrapper.get('form').trigger('submit')
expect(wrapper.emitted('submit')?.[0]).toEqual([PR_URL, '', true])
```

Add a `5 / 5` test that asserts disabled state and full-capacity guidance.

- [ ] **Step 4: Implement form UI and connect the review view**

Use `NCheckbox` and `NTooltip`, emit `submit: [prUrl: string, repoPath: string, addToBenchmark: boolean]`, reset after accepted submission, and disable opt-in for local diff input or full capacity. Load capacity on review mount and forward the third submit argument to the store. Use the existing toast path for backend conflicts.

- [ ] **Step 5: Run focused tests and commit**

Run from `web`: `npm test -- --run src/components/ReviewForm.test.ts src/stores/review.test.ts`

```bash
git add web/src/types.ts web/src/stores/review.ts web/src/stores/review.test.ts web/src/components/ReviewForm.vue web/src/components/ReviewForm.test.ts web/src/views/ReviewView.vue
git commit -m "feat: add benchmark opt-in to review form"
```

---

### Task 4: Saved Audit Benchmark Page

**Files:**
- Replace: `web/src/views/BenchmarkView.vue`
- Create: `web/src/views/BenchmarkView.test.ts`

**Interfaces:**
- Consumes: `BenchmarkCollection`, `BenchmarkEntrySummary`, `RunDetail`, `Finding`, and Task 2's selected-detail API.
- Produces: repository selection, stable loading states, finding metrics/list, and original-review navigation.

- [ ] **Step 1: Write failing empty, ready, and running view tests**

```typescript
it('shows a saved repository and its existing findings', async () => {
  mockFetchCollectionAndDetail({ entries: [ENTRY], run: RUN_DETAIL })
  const wrapper = mount(BenchmarkView, { global: { plugins: [router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('sentry-greptile')
  expect(wrapper.text()).toContain('PR #1')
  expect(wrapper.text()).toContain('越权访问')
  expect(wrapper.get('[aria-label="查看完整审计"]').attributes('href')).toContain(`/review/${ENTRY.run_id}`)
})
```

The empty test asserts opt-in guidance. The running test asserts progress/skeleton state and absence of fake metrics.

- [ ] **Step 2: Implement race-safe collection/detail loading**

Use typed refs for collection loading, detail loading, entries, selected run ID, and selected run. Select the first entry on mount. Increment a request token before each detail fetch so a slow earlier selection cannot overwrite the newest selection.

- [ ] **Step 3: Derive result metrics from original events**

Use the latest report `findings` list when available; otherwise merge finding and verdict events by finding/source ID. Derive total, kept, rejected, severity counts, and elapsed seconds from event timestamps without changing artifacts.

- [ ] **Step 4: Build the saved-audit interface**

Use `NSelect` or a compact repository list, `NTag`, `NSkeleton`, `NEmpty`, and existing `FindingCard`. Option labels lead with `repository_name` and include `PR #number`. Link to `/review/{run_id}` with an `ExternalLink` icon and `aria-label="查看完整审计"`. Remove demo rows, hit-rate targets, heatmap, ECharts imports, and comparison language. Use tokenized styles in a restrained two-column Windows desktop layout that collapses cleanly.

- [ ] **Step 5: Run the view tests and commit**

Run from `web`: `npm test -- --run src/views/BenchmarkView.test.ts`

```bash
git add web/src/views/BenchmarkView.vue web/src/views/BenchmarkView.test.ts
git commit -m "feat: browse saved benchmark audits"
```

---

### Task 5: Full Verification And Windows UI Check

**Files:**
- Modify only previously listed files if verification exposes a defect.

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: verified behavior without generated or secret files staged.

- [ ] **Step 1: Run the complete Python suite**

Run: `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest -q`

- [ ] **Step 2: Run all frontend checks**

Run from `web`:

```bash
npm test
npm run typecheck
npm run lint
npm run build
```

- [ ] **Step 3: Verify Windows desktop layouts**

Use the existing frontend at `http://127.0.0.1:5174`. Do not restart the backend if reviews remain active. Once safe, start it with the existing `.env` and proxy environment without printing secrets.

Check `1440x900` and `1280x720`: no form overlap; clear empty collection; stable running skeleton; unclipped ready metrics/findings; disabled `5 / 5` opt-in; and no stale detail after rapid selection.

- [ ] **Step 4: Inspect repository safety**

```bash
git diff --check
git status --short
git check-ignore -v .env runs repos rushgogogo
```

Expected: secret/generated paths are ignored and unrelated user files remain unstaged. If fixes were required, stage only exact source/test files and commit them as `fix: complete benchmark collection verification`.
