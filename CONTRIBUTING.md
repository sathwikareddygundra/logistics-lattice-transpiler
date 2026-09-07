# Contributing

## Branch naming

All work happens on short-lived feature branches off `main`, named:

    feature/T-<task-number>-<short-slug>

Example: `feature/T-4-provision-compute`

Branches are merged into `main` via pull request — never pushed to directly.

## Pull request template

Every PR description should cover, in one short paragraph:

- **What changed** — a plain-language summary of the change.
- **Which task ID** — e.g. "Implements T-4."
- **How it was tested** — what you ran to confirm it works (unit tests, manual check, etc.).
