# Saved Audit Benchmark Design

## Goal

Turn the Benchmark page into a fixed collection of five completed audit results. Each entry represents one pull request from a distinct repository. Users opt in while starting a normal audit, then inspect the existing result from the Benchmark page without running the audit again.

## Scope

- Add an optional "Add to Benchmark" control to the audit form.
- Persist a lightweight index that references existing run artifacts.
- Limit the collection to five entries and one entry per repository.
- Show reserved, running, completed, and failed state transitions correctly.
- Replace the current demo and harness-oriented Benchmark UI with a selector and saved result view.
- Reuse the original run's events and findings as the only result source.

The feature does not run comparative evaluation, calculate ground-truth hit rates, copy run artifacts, or modify the benchmark harness output format.

## Data Model

The server stores a JSON index below the benchmark data directory. The index contains no report or event copies. Each entry has:

- `run_id`: reference to the original run directory.
- `repository`: canonical GitHub `owner/repository` identifier.
- `repository_name`: repository segment used as the primary display name.
- `pr_url` and `pr_number`: source pull request identity.
- `status`: `reserved`, `running`, or `ready`.
- `created_at` and optional `completed_at` timestamps.

The server derives repository and PR identity from the submitted GitHub pull request URL. Local diff-only reviews cannot be added because they do not provide the required repository and PR identity.

The index is updated through one server-owned helper protected by an asynchronous lock. Writes use a temporary file followed by replacement so readers never observe partial JSON. The backend is the authority for the five-entry limit and repository uniqueness.

## Audit Submission Flow

The review request gains an `add_to_benchmark` boolean, defaulting to `false` for compatibility.

When it is false, review submission behaves exactly as it does today. When it is true, the server validates the PR URL, locks the index, and rejects the request with a clear conflict response if:

- five entries are already reserved or ready, or
- the same repository already has an entry.

Otherwise, the server creates the run ID and reserves the Benchmark entry before returning the accepted response. This prevents concurrent submissions from claiming the fifth slot twice.

The reservation remains visible as an in-progress item while the audit runs. Successful report completion marks it `ready`. Any repository preparation or audit failure removes the reservation, immediately returning the capacity to the collection.

## API Design

- `GET /api/benchmark/entries` returns capacity, count, and the ordered entry summaries.
- `GET /api/benchmark/entries/{run_id}` returns the selected entry plus the original run detail needed by the page.
- `POST /api/review` accepts `add_to_benchmark` and returns the existing `run_id` response.

The existing `/api/benchmark/latest` harness endpoint remains available for compatibility, but the application page no longer depends on it.

API errors use actionable Chinese messages for a full collection, a duplicate repository, an unsupported input, a missing run, and a corrupt index. A corrupt index is not silently overwritten.

## Audit Form UI

The form loads Benchmark capacity with the review screen and presents a compact checkbox labeled "加入 Benchmark" with a `count / 5` indicator. The checkbox has hover and active feedback and an explanatory tooltip.

At capacity, the checkbox is disabled and its label states that all five positions are occupied. Starting a Benchmark audit refreshes the capacity after acceptance. Backend conflict responses are shown with the existing toast error path, covering stale tabs and concurrent submissions.

The new control wraps cleanly below the inputs at narrower Windows viewport widths without shrinking the primary fields below their usable size.

## Benchmark Page UI

The page becomes a saved audit browser instead of a harness scorecard:

- The header shows collection occupancy and purpose.
- A repository selector lists up to five entries. Each option uses `repository_name` as its title and `PR #number` as supporting text.
- Reserved or running entries remain selectable and show a skeleton/progress state.
- A ready entry shows duration, total findings, kept findings, rejected findings, and severity distribution derived from the original events.
- The main list reuses the existing Finding presentation and preserves its expandable reasoning, location, trigger path, and recommendation.
- A clear action opens `/review/{run_id}` for the complete workflow and replay.
- An empty collection displays guidance to enable "加入 Benchmark" on the audit form.

The existing demo rows, hit-rate target, heatmap, and harness claims are removed because they imply comparison against ground truth, which is outside this feature.

## State And Failure Handling

- Loading collection and entry data uses skeletons.
- Fetch or validation failures use toasts and retain the last valid UI state where possible.
- If an indexed run directory is missing, the entry is shown as unavailable rather than crashing the page.
- A failed opted-in audit is removed from the collection. Its original run remains available in review history as a failed run.
- Refreshing or restarting the server preserves ready and active entries. On startup/read, a non-ready entry whose run is no longer active and has no report is treated as stale and removed.

## Testing

Backend tests cover normal reservation, default opt-out behavior, five-entry rejection, duplicate-repository rejection, concurrent capacity enforcement, successful transition, failure cleanup, persistence, and missing/corrupt index behavior.

Frontend tests cover request payloads, capacity-disabled controls, the opt-in submission event, empty/loading/error states, repository selection, running entries, ready result rendering, and the link to the original review.

The completed change must pass Python tests, frontend unit tests, TypeScript strict checking, and ESLint. Browser verification should cover the Benchmark empty state, a running selected entry, a completed selected entry, a full collection, and responsive Windows desktop widths.
