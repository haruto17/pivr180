# CLAUDE.md

## Milestone

See [milestone.md](../docs/milestone.md)

## Workflow

See [workflow.md](../docs/workflow.md)

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