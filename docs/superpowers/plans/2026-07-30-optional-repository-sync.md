# Optional Repository Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local repository path optional for GitHub pull request reviews while safely cloning or fast-forwarding the required repository on the backend.

**Architecture:** Add a focused repository preparation module that parses GitHub PR URLs, validates local worktrees, serializes updates by target path, and runs bounded Git commands. The existing API starts the run immediately and calls this module inside its background task before invoking the orchestrator. The Vue form sends a nullable repository path and relies on existing SSE error toasts.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, subprocess, Vue 3, TypeScript strict, Pinia, Naive UI, pytest, Vitest.

## Global Constraints

- Never stash, reset, switch branches, or overwrite local repository changes.
- Only canonical GitHub pull request URLs may derive an automatic clone target.
- Cache automatic clones below the ignored `repos/` directory.
- Invoke Git without a shell and use bounded timeouts.
- Do not expose credential-bearing remote URLs in user-facing errors.
- Preserve the existing run ID, SSE, replay, and toast contracts.

---

### Task 1: Repository Preparation Service

**Files:**
- Create: `reviewcrew/server/repository.py`
- Create: `tests/test_repository.py`

**Interfaces:**
- Produces: `RepositoryPreparationError`, `github_repository(pr_url: str) -> tuple[str, str] | None`, and `prepare_repository(pr_url: str, repo_path: str | None, repos_dir: Path = Path("repos")) -> Path`.
- Consumes: no application state; all Git operations use `subprocess.run` argument arrays.

- [ ] Add tests that mock `subprocess.run` and assert an omitted path clones `https://github.com/owner/repo.git` into `repos/owner__repo`.
- [ ] Add tests asserting an existing automatic cache and an explicit clean worktree run `git pull --ff-only` from that repository.
- [ ] Add tests asserting local diff input without a path, missing directories, non-Git directories, dirty status, mismatched origin, failed pull, and timed-out Git commands raise `RepositoryPreparationError` with sanitized messages.
- [ ] Implement canonical GitHub PR parsing, deterministic cache paths, per-target process locks, repository and remote validation, clean-status checks, clone, and fast-forward-only pull.
- [ ] Run `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_repository.py -q` and expect all repository tests to pass.

Core signature:

```python
def prepare_repository(
    pr_url: str,
    repo_path: str | None,
    repos_dir: Path = Path("repos"),
) -> Path:
    """Return a validated and updated repository or raise RepositoryPreparationError."""
```

Git commands must follow these shapes:

```python
["git", "clone", "https://github.com/<owner>/<repo>.git", "<target>"]
["git", "-C", "<repo>", "rev-parse", "--is-inside-work-tree"]
["git", "-C", "<repo>", "status", "--porcelain"]
["git", "-C", "<repo>", "remote", "get-url", "origin"]
["git", "-C", "<repo>", "pull", "--ff-only"]
```

### Task 2: API Integration

**Files:**
- Modify: `reviewcrew/server/app.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `prepare_repository(pr_url, repo_path, repos_dir)` from Task 1.
- Produces: `ReviewRequest.repo_path: str | None` and `create_app(..., repos_dir: Path = Path("repos"))`.

- [ ] Add an API test posting only `pr_url` and assert the endpoint returns `202` and the background task receives the prepared path.
- [ ] Add a test posting a blank path and assert it is normalized to automatic preparation.
- [ ] Change `ReviewRequest.repo_path` to optional and remove synchronous path validation from the endpoint.
- [ ] In the existing `execute` background coroutine, call `await asyncio.to_thread(prepare_repository, request.pr_url, request.repo_path, repos_dir)` before `Orchestrator.review`.
- [ ] Keep preparation failures on the existing `record_run_error` path so SSE consumers receive the current stage error event.
- [ ] Run `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest tests/test_server.py -q` and expect all API tests to pass.

Integration shape:

```python
async def execute() -> None:
    try:
        repo = await asyncio.to_thread(
            prepare_repository,
            request.pr_url,
            request.repo_path,
            repos_dir,
        )
        await Orchestrator(runs_dir=runs_dir).review(request.pr_url, repo, run_id=run_id)
    except Exception as error:
        record_run_error(run_id, error)
```

### Task 3: Optional Frontend Path

**Files:**
- Modify: `web/src/components/ReviewForm.vue`
- Create: `web/src/components/ReviewForm.test.ts`
- Modify: `web/src/stores/review.ts`
- Modify: `web/src/views/ReviewView.vue`

**Interfaces:**
- Produces: `submit(prUrl: string, repoPath: string)` where `repoPath` may be empty.
- Produces: `startReview(prUrl: string, repoPath?: string)` sending `{ pr_url, repo_path: string | null }`.

- [ ] Add component tests asserting a GitHub PR URL submits with an empty path and an explicit path is trimmed.
- [ ] Enable submit when the review source is non-empty, regardless of repository path.
- [ ] Change the repository label and placeholder to communicate that it is optional and that local diffs still require it.
- [ ] Trim the path in the store and send `null` when it is blank.
- [ ] Preserve existing loading, disabled, demo, route replacement, and toast behavior.
- [ ] Run `npm run test -- ReviewForm.test.ts && npm run typecheck && npm run lint` from `web/`.

Expected request body:

```ts
body: JSON.stringify({
  pr_url: prUrl,
  repo_path: repoPath?.trim() || null,
})
```

### Task 4: Documentation And Full Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents the optional API field and automatic clone cache behavior.

- [ ] Update Web and API examples to show a GitHub PR request without `repo_path` and a local diff request with it.
- [ ] Document `repos/<owner>__<repo>` caching, clean-worktree requirements, and `git pull --ff-only` behavior.
- [ ] Run `/Users/xuansama/miniforge3/envs/common/bin/python -m pytest` and expect all backend tests to pass.
- [ ] Run `npm run typecheck && npm run lint && npm run test && npm run build` from `web/` and expect all frontend checks to pass.
- [ ] Verify `git diff --check` and scan tracked content for `.env` files and credential patterns before committing.
- [ ] Commit the implementation without adding `repos/`, `runs/`, `.env`, `presentation-assets/`, or `reviewcrew-ai-code-review-story.html`.
