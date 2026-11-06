# workflow.md

1. Preparation
2. Review milestones and select a task
3. Create an issue and a branch
4. Implement
5. Self review
6. Create a pull request
7. Wrap up and report

## 1. Preparation

1. Run `git switch main && git pull` to get the latest changes, then make sure the working tree is clean.
2. Run `gh issue list` and `gh pr list` to check whether an issue or PR for the same task already exists.

## 2. Review milestones and select a task

Choose a task using the following criteria, in order of priority:

1. Tasks in the open milestone with the earliest due date
2. Issues labeled `priority:high`
3. Tasks that do not depend on other tasks (not blocked)
4. Issues with lower numbers

**Notes**

- If an issue or PR with the same content already exists, use it instead of creating a new one.
- Do not work on an issue that is already assigned to someone else.

## 3. Create an issue and a branch

### 3.1 Create an issue

If you selected an existing issue in step 2, skip this step.

1. Choose an issue template based on the task type:

| Task type | Template |
| --- | --- |
| Bug fix (`fix`) | `../.github/ISSUE_TEMPLATE/bug.md` |
| Everything else (`feat`, `refactor`, `test`, `docs`, `chore`) | `../.github/ISSUE_TEMPLATE/feature.md` |

2. Copy the template to a temporary file, **remove the front matter** (the block between the `---` lines at the top), and fill in every section. Replace the `<!-- -->` comments with actual content. Do not remove any sections; write "なし" if a section does not apply.
3. Run the following command to create the issue:

```
gh issue create \
  --title "<Concise title>" \
  --body-file <Filled-in template file> \
  --milestone "<Milestone name>" \
  --label "<Category label>"
```

### 3.2 Create a branch

Run the following command to create a branch linked to the issue:

```
gh issue develop <Issue number> \
  --name <Branch name> \
  --checkout
```

**Branch naming convention**: `<category>/<issue number>-<short description>`

| Category | Purpose |
| --- | --- |
| `feat` | New features |
| `fix` | Bug fixes |
| `refactor` | Code improvements that do not change behavior |
| `test` | Adding or updating tests only |
| `docs` | Documentation |
| `chore` | Configuration, build, etc. |

### 3.3 Post an implementation plan on the issue

Before you start implementing, read the relevant code. Then run the following command to post your plan as a comment on the issue:

```
gh issue comment <Issue number> \
  --body-file <Plan file>
```

## 4. Implement

- Keep changes to the minimum needed to meet the acceptance criteria. Do not refactor code unrelated to the issue.
- Split commits into small, meaningful units.
- Commit messages must follow the [Conventional Commits](https://raw.githubusercontent.com/conventional-commits/conventionalcommits.org/refs/heads/master/content/v1.0.0/index.md) specification.

## 5. Self review

- Are all acceptance criteria met?
- Is there any leftover debug code (such as `print` statements) or unnecessary comments?
- Are there any changes outside the scope of this issue?

## 6. Create a pull request

1. Copy `.github/pull_request_template.md` to a temporary file and fill in every section:
   - Replace `#<!-- issue Number -->` on the first line with the issue number (e.g. `Closes #42`) so the issue closes automatically when the PR is merged.
   - Under "受け入れ条件の確認", copy the acceptance criteria from the issue and check off the ones that are met.
   - Under "検証", check off each item only after you have actually done it in step 5.
   - Replace the `<!-- -->` comments with actual content. Write "None" if a section does not apply.
2. Run the following commands to create the pull request:

```
git push -u origin HEAD
gh pr create \
  --title "<Title in Conventional Commits format>" \
  --body-file <Filled-in template file> \
  --milestone "<Milestone name>" \
  --label "<Category label>"
```

## 7. Wrap up and report

Report the following:

- URLs of the issue and pull request you created
- A summary of the implementation
- Any unresolved concerns

## When to stop and ask a human

If any of the following happens, stop working and describe the situation in a comment on the issue:

- Meeting the acceptance criteria requires changes far beyond the scope of the issue.
- A decision about the architecture or state management approach is needed.
- The same error persists after three attempts to fix it.

## Prohibited actions

- Pushing directly to the `main` branch
- Merging pull requests
- Deleting or skipping tests just to make them pass