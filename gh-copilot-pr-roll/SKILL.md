---
name: gh-copilot-pr-roll
description: This skill should be used when the user asks to "roll Copilot review on a PR", "loop Copilot review until clean", "fix Copilot's PR comments and re-review", "iterate with Copilot code review", or gives a goal like "fix all open and previously missed issues on PR N, push, trigger Copilot review, repeat until no issues". Runs the fix → push → request Copilot review → wait → read findings cycle until Copilot reports nothing open; if Copilot is out of quota or otherwise can't run, switches once to a local subagent reviewer (Copilot Chat's review prompt) and loops until it reports no feedback.
---

# gh-copilot-pr-roll

Drive a GitHub PR to a clean Copilot review by repeating one cycle:
**fix → commit/push → confirm commit on PR → request Copilot review → wait → read findings → fix.**
Stop when the newest Copilot review has no Open and no "Previously missed" items.
If Copilot is unavailable (quota, rejected re-request, timeout), the same loop continues in **local mode** (see below) with a subagent as the reviewer.

Needs `gh` authenticated with access to the repo. Set `R=owner/repo`, `N=pr-number`.

## The cycle

### 1. Read the latest findings
Copilot's review body (user `copilot-pull-request-reviewer[bot]`) has sections **Open**, **Resolved since last review**, and **Previously missed** (issues in code that did not change — easy to overlook, fix them too). Inline detail is in line comments.

```bash
SHA=$(git rev-parse HEAD)
# review summary for the latest commit
gh api repos/$R/pulls/$N/reviews --paginate \
  --jq '.[]|select(.user.login=="copilot-pull-request-reviewer[bot]")|select(.commit_id=="'$SHA'")|.body'
# inline comments on that commit (user login is "Copilot")
gh api repos/$R/pulls/$N/comments --paginate \
  --jq '.[]|select(.commit_id|startswith("'${SHA:0:7}'"))|select(.user.login=="Copilot")|{id,path,line,body}'
```

Comment logins differ: reviews are `copilot-pull-request-reviewer[bot]`, inline comments are `Copilot`. Old threads re-appear in the commit-filtered comment list as context; the review body's Open / Previously-missed lists are the authoritative to-do list.

### 2. Fix
- Treat every Open and Previously-missed item as real until disproved; verify against the code before editing.
- Fix at the root: grep every caller / mirrored file (e.g. translated copies, canonical vs derived docs) so one comment is not fixed in only one place. Re-check repo lockstep rules (AGENTS.md / CLAUDE.md).
- A finding that is genuinely wrong: do not silently skip — reply on the thread with evidence.
- Run a minimal check for each logic fix (script, demo, test) before committing.

### 2b. Reply on every non-outdated Copilot thread
Every review thread Copilot opened that is **not outdated** must end with a reply from you after Copilot's last comment — fixed (with the commit sha and what changed), narrowed (what claim you changed instead), or disputed (with evidence). This applies to threads that are already resolved or that you replied to in an earlier round if Copilot has commented since. Outdated threads (the code they point at changed) need no reply. Threads Copilot leaves "Open" despite a fix get the same treatment: reply, don't skip.

Find the ones that still need a reply (non-outdated, last comment is Copilot's, or no reply covers the current fix):
```bash
gh api graphql -f query='query{repository(owner:"OWNER",name:"REPO"){pullRequest(number:N){reviewThreads(first:100){nodes{id isOutdated isResolved path line comments(first:50){nodes{databaseId author{login} createdAt body}}}}}}}' \
 | python3 -c "
import json,sys
for t in json.load(sys.stdin)['data']['repository']['pullRequest']['reviewThreads']['nodes']:
    if t['isOutdated']: continue
    cs=t['comments']['nodes']
    if cs[-1]['author']['login'].startswith('copilot') or cs[-1]['author']['login']=='Copilot':
        print(cs[0]['databaseId'], t['path'], t['line'], cs[0]['body'][:100])
"
```
(Also eyeball non-outdated threads whose last reply predates your latest fix commit.) Then reply by the first comment's `databaseId`:
```bash
gh api -X POST repos/$R/pulls/$N/comments/<databaseId>/replies -f body='Fixed in <sha> -- <what changed>'
```
Use `(first:100)` and paginate if the PR has >100 threads. "Previously missed" items often have no thread (body-only) — cover those in the PR description or commit messages. Replying is an outward-facing post: do it when the user has asked for it or the goal covers it, keep each reply factual, and never claim a fix you have not verified.

### 3. Commit and push
```bash
git commit -am "<what and why>"   # honor attribution rules in the session
git push
SHA=$(git rev-parse HEAD)
until [ "$(gh pr view $N --repo $R --json headRefOid -q .headRefOid)" = "$SHA" ]; do sleep 5; done
```
Wait until the PR head equals the pushed SHA before requesting a review — otherwise Copilot reviews a stale commit.

### 4. Request the Copilot review (skip entirely in local mode)
```bash
gh pr edit $N --repo $R --add-reviewer @copilot
```
(The REST `requested_reviewers` call with the bot login silently returns nothing; use the command above.) `reviewRequests` stays empty while Copilot is working, so it is not a progress signal.

### 5. Wait without polling in the foreground
Use a Monitor (or a background `until` loop) that exits when a Copilot review exists **for this exact SHA**. Match loosely — a strict jq on `[bot]` quoting missed a landed review once:

```bash
until gh api repos/$R/pulls/$N/reviews --paginate \
      --jq '.[]|"\(.user.login) \(.commit_id)"' | grep -q "^copilot.* $SHA"; do sleep 30; done
echo "copilot reviewed $SHA"
```
Typical latency is 5–15 min. Foreground `sleep` is blocked in Claude Code; re-arm the monitor on its 30-minute expiry if needed. Never push another commit mid-wait without re-requesting the review for the new SHA.

### 5b. One-time availability check
Do this **once per run**, right after the first request in step 4 — never again. Copilot is unavailable if any of: the PR timeline shows no new `review_requested` event ~2 min after the request; a Copilot comment/review mentions quota, limit, or "unable to review"; the request command errors. Also treat the step-5 wait expiring (~30 min with no review for `$SHA`) as unavailable. On any hit set `LOCAL=1` for the rest of the run: do not request, wait for, or re-check Copilot again (no retry, no "maybe quota reset"). If the check passes, proceed with step 5 as normal.

### 6. Loop or finish
Back to step 1 on the new review. Done when the latest review for the current HEAD lists no Open and no Previously-missed items (a "Resolved" section alone is fine). Report: commits pushed, findings fixed per round, and anything disputed.

## Local mode (Copilot unavailable)
Replaces steps 4–5 (and the review-reading in step 1) with a subagent review of the local change. Everything else — fix at root, minimal check, commit/push, step 2b replies on existing threads — is unchanged.

1. Build the input: `git diff $(gh pr view $N --repo $R --json baseRefName -q .baseRefName)...HEAD` (add `git show <path>` context for touched files as needed).
2. Spawn one subagent (Agent tool, general-purpose, fresh each round so it is not anchored by earlier rounds) with the prompt below, the diff, and read access to the repo. If `AGENTS.md` / `CLAUDE.md` has review rules, paste them in place of the `{review rules}` line; otherwise drop that line. The subagent only reviews — it must not edit.
3. Fix every item it reports (verify against code first; dispute a wrong one with evidence rather than skipping silently), run the minimal check, commit, push.
4. Re-run from step 1 on the new diff. **Done when the subagent replies exactly `No feedback to provide.`** If the same finding comes back 3 rounds running after fixes, stop and ask the user.

Prompt (adapted from the open-source Copilot Chat `provideFeedback.tsx` review prompt):
```
You are a world-class software engineer and the author and maintainer of the discussed code. Your feedback perfectly combines detailed feedback and explanation of context.
{review rules from AGENTS.md, if any}
Additional Rules
Think step by step:

1. Examine the provided code and any other context like user question, related errors, project details, class definitions, etc.
2. Provide feedback on the current change on where it can be improved or introduces a problem.
   * 2a. Avoid commenting on correct code.
   * 2b. Avoid commenting on commented out code.
   * 2c. Keep scoping rules in mind.
3. Reply with an enumerated list of feedback with source line number, filepath, kind (bug, performance, consistency, documentation, naming, readability, style, other), severity (low, medium, high), and feedback text.
   * E.g.: 1. Line 357 in src/flow.js, bug, high severity: `i` is not incremented.
   * E.g.: 2. Line 361 in src/arrays.js, documentation, low severity: Function `binarySearch` is not documented.
   * E.g.: 3. Line 176 in src/vs/platform/actionWidget/browser/actionWidget.ts, consistency, medium severity: The color id `'background.actionBar'` is not consistent with the other color ids used. Use `'actionBar.background'` instead.
   * E.g.: 4. Line 410 in src/search.js, documentation, medium severity: Returning `-1` when the target is not found is a common convention, but it should be documented.
   * E.g.: 5. Line 51 in src/account.py, bug, high severity: The deposit method is not thread-safe. You should use a lock to ensure that the balance update is an atomic operation.
   * E.g.: 6. Line 220 in src/account.py, readability, low severity: The withdraw method is very long and combines multiple logical steps, consider splitting it into multiple methods.
4. Try to sort the feedback by file and line number.
5. When there is no feedback to provide, reply with "No feedback to provide."
```

## Gotchas
- **Re-request stalls.** If the PR timeline (`gh api repos/$R/issues/$N/timeline`) shows no new `review_requested` event after your request, Copilot did not accept it. That is the step-5b unavailable signal: switch to local mode immediately — no remove/re-add, no GraphQL retry, no waiting or asking the user.
- If a fix changes a PR's scope (new file, contract change), update the PR description in the same round; Copilot flags undocumented scope.
- macOS `sed -i` needs `-i ''`; a failed `sed` in an `&&` chain silently skips later steps — prefer small Python edits and check `git log` after.
- Requesting review before the push lands on the PR yields a review of the old SHA.
- Review rounds can surface new findings caused by your last fix (e.g. a new flag exposing a sibling code path). Re-read the whole changed surface, not just the quoted line.
- Don't mark threads resolved or reply on behalf of the user unless asked; fixing + pushing is the default scope.
