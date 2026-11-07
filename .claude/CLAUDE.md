# CLAUDE.md

## Milestone

See [milestone.md](../docs/milestone.md)

## Workflow

See [workflow.md](../docs/workflow.md)

## Team

Work in teams. Each team handles exactly one task, and up to 4 teams may work in parallel.

Each team consists of two members:

- **Implementer**: implements, self-reviews, creates the PR, applies fixes, and merges
- **Reviewer**: monitors the PR on GitHub and reports to the Implementer

### Flow

1. Implementer: implement → self-review → push → create PR
2. Once the PR is created, Codex review runs automatically on GitHub
3. Reviewer: check the PR every 10 minutes for Codex review comments and approval status
4. If review comments are found, Reviewer reports them to Implementer
   - Implementer: fix → self-review → push, then return to step 3
5. If the PR is approved, Reviewer reports it to Implementer
   - Implementer: merge the PR
6. After the merge, the team disbands

### Rules

- Each team works on its own branch in a separate git worktree
- Do not push after each commit; push only once all implementation (or all fixes for a review round) is complete
- Repeat the review → fix cycle until the PR is approved
- If the branch falls behind main after another team merges, merge main into the branch (do not rebase, since force-pushing is not allowed)
- If a review comment requires the owner's decision (e.g. spec changes, scope changes, design decisions that would need an ADR), stop, mention the owner with "@haruto17" in a PR comment, and wait for the owner's instructions
- If no Codex review appears after 1 hour, stop, mention the owner with "@haruto17" in a PR comment, and wait for the owner's instructions

## ADR

When creating an ADR, use the following template: [adr_template.md](../docs/adr/adr_template.md)

## Notes

- Implementation must be carried out using sub-agents
- Avoid unnecessary refactors
- Code should describe the How, test code the What, and code comments the Why Not; comments should generally contain nothing else
- Split commits into small, meaningful units
- Run tests and lint before every push; do not push if they fail
- Do not force-push or rewrite history after the PR is created
- Reply to each review comment with how it was addressed, or why it was not
- End every PR comment with "Generated with Claude Code"