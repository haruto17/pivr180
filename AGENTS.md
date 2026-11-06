# AGENTS.md

## Code Review Rules

When reviewing a pull request, verify each of the following. Flag any violation as a review comment.

### Requirements
- All acceptance criteria defined in the issue or ticket MUST be satisfied.
- The change MUST NOT include modifications outside the stated scope. Unrelated refactors, formatting changes, or feature additions should be split into a separate PR.

### Code Quality
- Debug code (e.g., `print` statements, temporary logging) MUST NOT remain.
- Unnecessary comments (commented-out code, outdated TODOs, self-evident explanations) MUST be removed.

### Performance
- The change MUST NOT introduce performance regressions (e.g., unnecessary re-renders, redundant computations, blocking operations on the main thread, or added network/database calls).

### Security
- Sensitive information MUST NOT be committed, including `.env` files, API keys, tokens, credentials, or secrets.
- Any newly added sensitive file patterns should be added to `.gitignore`.