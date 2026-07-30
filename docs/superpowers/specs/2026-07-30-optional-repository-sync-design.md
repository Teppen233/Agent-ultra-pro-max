# Optional Repository Sync Design

## Goal

Allow the review form to accept an optional local repository path. When the path is omitted for a GitHub pull request, ReviewCrew prepares a cached checkout automatically. When a path is supplied, ReviewCrew safely updates that repository before starting the review.

## Request Contract

`POST /api/review` keeps `pr_url` required and changes `repo_path` to an optional string. An omitted or blank path is valid only for a canonical GitHub pull request URL. Local diff paths and unsupported URLs still require an explicit local repository path because the repository cannot be derived safely.

## Repository Resolution

Repository preparation is owned by the backend and runs before the orchestrator inside the existing background task.

- A supplied path must exist, be a Git worktree, have a clean status, and match the GitHub repository named by the PR URL when one is present.
- A clean supplied repository is updated with `git pull --ff-only`. ReviewCrew never stashes, resets, switches branches, or overwrites local changes.
- An omitted path derives `owner/repository` from the GitHub PR URL and uses `repos/<owner>__<repository>` as a deterministic cache directory.
- A missing cache directory is cloned from `https://github.com/<owner>/<repository>.git`.
- An existing cache directory is validated like a supplied repository and updated with `git pull --ff-only`.
- Clone and pull commands use argument arrays without a shell, have bounded timeouts, and return sanitized errors that do not include credential-bearing remote URLs.

The existing `repos/` ignore rule prevents cached repositories from entering source control.

## Runtime And Errors

The API creates and returns a run ID immediately. Repository preparation then happens in the existing background task before `Orchestrator.review`. Failures use the existing run error event path, so the SSE client receives an actionable toast without adding a second preparation API or frontend polling state.

Only one preparation operation may target a cached repository at a time within the server process. This prevents simultaneous review requests from cloning or pulling the same directory concurrently.

## Frontend

The repository input remains a normal text input but is labelled and presented as optional. The submit button requires only a non-empty review source. The frontend sends `repo_path: null` for a blank value and keeps sending the trimmed path when supplied.

The placeholder communicates the behavior without adding a permanent explanatory panel: a GitHub PR can be cloned automatically, while a local diff requires a path. Existing loading and toast behavior remains unchanged.

## Validation

Backend tests cover omitted paths, deterministic clone targets, existing cache updates, supplied repository updates, dirty worktrees, non-Git directories, mismatched origins, unsupported review sources, fast-forward failures, command timeouts, and sanitized errors. Tests mock Git subprocess execution and do not access the network.

Frontend tests cover blank path submission and trimmed explicit paths. TypeScript, ESLint, Vitest, pytest, and the production frontend build must pass.

## Out Of Scope

ReviewCrew does not manage credentials, authenticate to private repositories, select or switch branches, modify dirty worktrees, delete cached clones, or support arbitrary Git hosting providers in this change.
