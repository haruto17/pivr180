# AGENTS.md

## Code Review Rules

When reviewing pull requests, make sure to check each of the following items. If there are any violations, point them out in a review comment following the specified format.  
For each issue, describe a concrete scenario (input, state, or sequence of events) in which the problem occurs. Do not report speculative issues without a plausible failure scenario.

### Review procedure

1. Skip the PR if there are no new commits since your last "Review completed by Codex" comment.
2. Read the replies to your previous review comments. Do not report the same issue again if it was fixed, or if the reply gives a valid reason for not fixing it.
3. Post each issue as a review comment on the relevant line, following the format below.
4. When the review is complete, always post a PR comment in the following format, whether or not issues were found:

```
Review completed by Codex
commit: <SHA of the reviewed head commit>
result: <result>
critical: <count>, error: <count>, warning: <count>, nit: <count>
deferred warnings: <links to follow-up issues, or "None">
```

Do not include deferred warnings in the `warning` count.

A `warning` is deferred only if the reply to its review comment states the reason for deferring and links to a follow-up issue that exists. Otherwise, count it as an unresolved `warning`.

Set `result` as follows:

- If there are no `critical`, `error`, or unresolved `warning` issues (only `nit` issues or deferred warnings remain, or none at all): `LGTM by Codex`
- Otherwise: `Changes requested`

Do not write "LGTM by Codex" anywhere in the comment unless the result is LGTM.

### Review comment format

```
summary: <summary>
level: <level>
location: <file_path>:<line_number>
issue:
<issue>
```

Example:
````
summary: Potential AttributeError when user is not found
level: error
location: app/services/user_service.py:4
issue:
If the user does not exist in the database, `user` will be `None`, raising an `AttributeError` when accessing `user.name`.  

Please add error handling for cases where the user is not found (e.g., raise a 404 error or return `None`).

```python
if not user:
    raise UserNotFoundError(f"User with ID {user_id} not found")
```
````

**level convention**

Use exactly one of the following values for `level`.

- `critical`: Blocks merge. Issues that can cause severe or irreversible damage, such as security vulnerabilities, leaked secrets, data loss, or data corruption.
- `error`: Blocks merge. Violations of MUST rules, bugs, specification violations, unmet acceptance criteria, or missing error handling that can cause incorrect behavior or crashes.
- `warning`: Should be fixed before merge. May be deferred only if the reason is stated and a follow-up task is created. Includes violations of SHOULD rules, likely future bugs, and performance concerns without a confirmed regression.
- `nit`: Optional. Readability, naming, formatting, or stylistic improvements that do not affect behavior.

If unsure between two levels, choose based on the impact of the concrete failure scenario, not on how likely the issue seems.

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

### Correctness
- Logic MUST behave correctly for edge cases, including `null`/`None`, empty collections, empty strings, zero, negative values, and boundary values (e.g., off-by-one errors).
- Conditional branches MUST cover all expected cases. Check for inverted conditions, missing `else`/default branches, and unreachable code.
- Type mismatches, implicit type conversions, and floating-point comparisons MUST be handled correctly.
- Date/time handling MUST account for time zones, daylight saving time, and locale differences where relevant.

### Error Handling
- Exceptions MUST NOT be silently swallowed (e.g., empty `catch`/`except` blocks, or catching overly broad exceptions without re-raising or logging).
- Failures from external dependencies (APIs, databases, file I/O) MUST be handled, including timeouts and unexpected responses.
- Error messages and logs MUST provide enough context for debugging without exposing sensitive information.

### Concurrency & State
- Shared mutable state MUST be protected against race conditions.
- Asynchronous code MUST be awaited or handled correctly. Check for missing `await`, unhandled promise rejections, and fire-and-forget calls.
- Operations that may be retried or executed multiple times SHOULD be idempotent.

### Data Integrity & Resources
- Operations that update multiple records MUST use transactions or otherwise prevent partial updates.
- External input MUST be validated before use.
- Resources (files, connections, streams, event listeners, subscriptions) MUST be properly released, including on error paths.

### Compatibility
- Changes to public APIs, function signatures, data schemas, or config formats MUST NOT break existing callers unless intended. If breaking, all call sites MUST be updated.
- Database migrations MUST be safe to apply to existing data and SHOULD be reversible.

### Testing
- New logic and bug fixes MUST include tests covering the main path and relevant edge cases.
- Bug fixes SHOULD include a regression test that fails without the fix.
- Tests MUST contain meaningful assertions and MUST NOT depend on execution order, current time, or external services without mocking.