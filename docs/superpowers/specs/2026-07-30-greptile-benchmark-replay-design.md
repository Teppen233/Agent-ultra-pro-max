# Greptile Benchmark Replay Design

## Goal

Show the ten completed Greptile benchmark reviews in the existing Benchmark page. The page groups two cases under each of five repositories, and every completed case links to the existing Review view for full event replay.

## Scope

- Use the ten successful runs recorded in `benchmark/results/backend-runs.json`.
- Replace the current five-repository capacity presentation with a ten-case evaluation presentation.
- Group cases by repository while keeping each case independently selectable.
- Preserve the existing finding summary and detail panel for the selected run.
- Open `/review/:runId` for full replay; no event or report data is duplicated.
- Keep the existing loading skeleton, empty guidance, retry action, and toast-based errors.

The failed Grafana attempt remains available in the run history for audit purposes but is not one of the ten benchmark cases. The successful retry is used instead.

## Backend Design

The backend treats `benchmark/results/backend-runs.json` as the curated Greptile run manifest. Each self-contained manifest item includes its repository and pull-request URL. A small loader validates every item and resolves its run directory.

`GET /api/benchmark/entries` returns the ten manifest runs in manifest order using the existing `BenchmarkCollection` shape. Its capacity is ten and its count is the number of valid manifest cases. Missing run directories are retained as non-ready entries only when enough metadata exists to identify the case; malformed manifest records are skipped rather than breaking the entire page.

`GET /api/benchmark/entries/:runId` only resolves IDs exposed by the collection and returns the existing run detail payload. Review event replay continues to use the existing `/api/runs/:runId` and `/api/replay/:runId` endpoints.

The existing opt-in store remains available as a fallback when no Greptile manifest exists, so development and current opt-in tests continue to work.

## Frontend Design

The left browser panel displays five repository groups. Each group contains two case rows showing the persisted run name, PR number, and completion status. Selecting a row loads the existing Benchmark detail panel without navigation.

The detail header displays the case name and repository identity. Its primary link is labeled "回放完整审计" and routes to `/review/:runId`, where the existing replay controls, workflow graph, findings, diff, and report remain available.

The page header displays `10 / 10` as evaluation progress and labels the metric "评测任务", avoiding the old implication that ten entries represent ten distinct repositories.

## Data Flow

1. The Benchmark page requests `/api/benchmark/entries`.
2. The backend reads and validates the Greptile run manifest and run metadata.
3. The page groups returned entries by repository and selects the first ready case.
4. Selecting a case requests `/api/benchmark/entries/:runId` for its saved events and findings.
5. Clicking "回放完整审计" opens `/review/:runId`; the Review view loads the same run and replays its saved events.

## Failure Handling

- Collection request failure keeps the existing retry state and error toast.
- Detail request failure keeps the selected row and shows a toast without displaying stale detail from another run.
- A missing or incomplete case is shown with a non-ready status and cannot open a misleading result.
- An absent manifest falls back to the existing saved Benchmark collection.

## Verification

- Backend tests cover manifest loading, ten-case collection output, fallback behavior, and detail access restrictions.
- Benchmark view tests cover five repository groups, two cases per group, names, selection, and the replay route.
- Existing server tests, TypeScript checking, ESLint, and frontend unit tests must continue to pass.
