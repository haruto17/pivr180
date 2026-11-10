# workflow.md

1. Preparation
2. Review milestones and select a task
3. Create an issue, a branch, and worktree
4. Implement
5. Self review
6. Create a pull request
7. Fix (if necessary)
8. Merge
9. Clean up and report

### 1. Preparation

1. In the main repository directory, run `git switch main && git pull` to get the latest changes, then make sure the working tree is clean.
2. Run `gh issue list` and `gh pr list` to check whether an issue or PR for the same task already exists.
3. Run `git worktree list` to check which tasks other teams are currently working on.

### 2. Review milestones and select a task

Choose a task using the following criteria, in order of priority:

1. Tasks in the open milestone with the earliest due date
2. Issues labeled `priority:high`
3. Tasks that do not depend on other tasks (not blocked)
4. Issues with lower numbers

### 3. Create an issue, a branch, and worktree

#### 3.1 Create an issue

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

#### 3.2 Claim the issue

Assign the issue to yourself immediately so other teams do not pick the same task:

```
gh issue edit <Issue number> --add-assignee @me
```

#### 3.3 Create a branch and a worktree

Run the following commands to create a branch linked to the issue and a dedicated worktree for it. Do not use `--checkout`, since each team works in its own worktree rather than in the main repository directory.

```
gh issue develop <Issue number> \
  --name <Branch name> \
  --base main
git fetch origin
git worktree add ../worktrees/<Issue number> <Branch name>
```

Do all subsequent work for this task inside `../worktrees/<Issue number>`.

**Branch naming convention**: `<category>/<issue number>-<short description>`

| Category | Purpose |
| --- | --- |
| `feat` | New features |
| `fix` | Bug fixes |
| `refactor` | Code improvements that do not change behavior |
| `test` | Adding or updating tests only |
| `docs` | Documentation |
| `chore` | Configuration, build, etc. |

#### 3.4 Post an implementation plan on the issue

Before you start implementing, read the relevant code. Then run the following command to post your plan as a comment on the issue:

```
gh issue comment <Issue number> \
  --body-file <Plan file>
```

### 4. Implement

- Keep changes to the minimum needed to meet the acceptance criteria. Do not refactor code unrelated to the issue.
- Split commits into small, meaningful units.
- Commit messages must follow the [Conventional Commits](https://raw.githubusercontent.com/conventional-commits/conventionalcommits.org/refs/heads/master/content/v1.0.0/index.md) specification.
- Do not push after each commit. Push only once all implementation is complete.

### 5. Self review

- Are all acceptance criteria met?
- Do all tests and lint pass?
- Is there any leftover debug code (such as `print` statements) or unnecessary comments?
- Are there any changes outside the scope of this issue?

### 6. Create a pull request

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

### 7. Fix (if necessary)

Review the comments on the pull request. If you make changes, reply to the comments with details of the changes.  
To defer a `warning`, create a follow-up issue and reply to the review comment with the reason for deferring and a link to the issue. `critical` and `error` issues cannot be deferred.

### 8. Merge

1. Make sure CI is passing. If it is failing, do not merge; fix it and go back to step 7.
2. Run the following command to merge the PR:

```
gh pr merge <PR number> --merge
```

### 9. Clean up and report

1. From the main repository directory, remove the worktree and the local branch:

```
git worktree remove ../worktrees/<Issue number>
git branch -d <Branch name>
```

2. Report the following:

   - URLs of the issue and pull request
   - A summary of the implementation
   - Any unresolved concerns

## When to stop and ask the owner

If any of the following conditions apply, suspend work and seek the owner’s decision.

- Meeting the acceptance criteria requires changes far beyond the scope of the issue.
- A decision about the architecture or state management approach is needed.
- A review comment requires the owner's decision (e.g. spec changes, scope changes, design decisions that would need an ADR).
- The same error persists after three attempts to fix it.

## Prohibited actions

- Pushing directly to the `main` branch
- Merging a pull request without a valid "LGTM" (posted after the latest push)
- Force-pushing or rewriting history after the PR is created
- Deleting or skipping tests just to make them pass