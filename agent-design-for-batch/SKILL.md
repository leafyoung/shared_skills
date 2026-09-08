---
name: agent-design-for-batch
description: This skill should be used when the user asks to "write a batch script with the pi SDK", "design a pi agent pipeline", "run parallel pi sessions", "batch process files with pi", "architect a pi agent workflow", "handle stall detection in pi sessions", "implement graceful shutdown for pi", "design a parallel prompt architecture", "use pi SDK for bulk processing", "create a pi agent worker pool", "structure pi agent code", or mentions pi agent patterns, parallel pi agents, pi SDK batch processing, or pi agent architecture. Use this skill whenever designing or implementing code that creates and manages multiple pi AgentSession instances programmatically, including batch processing, worker pools, and automated pipelines.
version: 0.2.0
---

# Agent Design for Batch Processing

Architectural patterns for building robust, production-grade batch processing systems with the Pi agent SDK (`@mariozechner/pi-coding-agent`). These patterns generalize battle-tested code from multi-file automated correction pipelines processing thousands of files.

## Overview

When building a batch processing system with Pi's SDK, follow the **Parallel Prompt-1 + Sequential Post-Processing** architecture. This pattern maximizes throughput by running expensive LLM calls in parallel while serializing any shared-state mutations.

```
┌───────────────────────────────────────────────────────┐
│                  Shared work queue                     │
│              [A, B, C, D, E, F, G, ...]               │
└───────┬───────┬───────┬───────────┬───────────────────┘
        │       │       │           │
   Worker 1  Worker 2  Worker 3  Worker N   ← parallel (--concurrency N)
   (session  (session  (session  (session    ← Ctrl+C: flag aborted=true
    A)        B)        C)        D)         ← stops workers from dequeuing
        │       │       │           │               new items; in-progress
        └───────┴───────┴───────────┘   ← each chains into →  sessions finish
                     │
          sequentialPostChain            ← serialized (one at a time)
          ├─ Optional secondary prompt (shared-state edits)
          ├─ Verification
          └─ Mark complete
```

## When to Use This Pattern

Apply this architecture when the batch script must:

- Process many independent items where each item gets its own Pi `AgentSession`
- Run expensive LLM calls (prompt 1) in parallel for throughput
- Perform post-processing that touches shared state (files, counters, logs)
- Handle stalls gracefully (re-queue, don't fail)
- Support graceful shutdown (finish in-flight work, don't orphan state)

## Core Architectural Layers

### 1. Shared work queue

A plain array that workers consume from the front. Re-queued items (stall abort, retry) are pushed to the back.

Since Node.js runs a single-threaded event loop, array mutations between `await` boundaries are safe — no mutex, no lock, no atomics needed.

```typescript
const queue: string[] = [...items];
// Workers: queue.shift()
// Re-queue: queue.push(item)
```

### 2. Parallel workers

Each worker is a `while (!aborted.value)` loop that:

1. Pops an item from the queue
2. Creates a fresh ephemeral `AgentSession` (one per item)
3. Runs the primary prompt (the expensive LLM call)
4. Chains the result into the sequential post-processing chain — **without awaiting it**
5. Immediately returns to step 1 for the next item

The key insight: workers never `await` the post-processing chain. They attach to it with `.then()` and move on.

### 3. Sequential post-processing chain

A promise chain that guarantees only one post-processing callback runs at a time:

```typescript
let sequentialChain: Promise<void> = Promise.resolve();

// Each worker does:
sequentialChain = sequentialChain.then(async () => {
  // runs sequentially, one after another
});
```

This serializes operations that mutate shared state:

- Secondary prompts that edit shared specification files
- Progress tracking / completion markers
- Cross-item verification steps

### 4. Re-queue drain loop

After all workers drain the queue, a `do-while` loop processes any re-queued items:

```typescript
do {
  const workers = Array.from({ length: concurrency }, () => runWorker());
  await Promise.all(workers);
  await sequentialChain;
} while (queue.length > 0 && !aborted.value);
```

## Parallel Safety

### Isolation through directory/per-item scoping

Each session must operate on its own isolated scope. The primary way to achieve this is directory isolation: each item gets its own directory, and the prompt instructs the agent to create temporary helper scripts inside that directory and remove them after the task.

For a flat-file use case without per-item directories, isolate by filename prefix or use the session's own temp directory.

### No shared log file

Log to stdout only. Concurrent writers appending to the same file can interleave within write buffer flushes. The caller can redirect stdout to a per-run log:

```bash
bun run batch.ts 2>&1 | tee batch_run_$(date +%Y%m%d).log
```

### Prompt-level parallel safety instructions

Every prompt sent to a session must include explicit parallel-safety instructions telling the agent:

1. Where temporary helper scripts must be created (the item's isolated scope)
2. That temporary helper scripts must be removed after completing the task
3. That the agent must never modify files belonging to other items

## Stall Handling

Define a stall timeout (e.g., 60 seconds of inactivity). Attach a subscription listener that resets a timer on every event. If the timer fires:

1. Set a `stallAborted` flag for the current session
2. Call `session.dispose()`, which causes the pending `prompt()` to reject
3. Re-queue the item (unless shutting down)

The stalled item gets a fresh session when re-dequeued. There is no limit on stall retries — it retries until success, manual interrupt, or graceful shutdown.

## Graceful Shutdown (SIGINT)

Support two-level graceful shutdown:

- **First SIGINT**: Set `aborted.value = true`. Workers finish their current item and stop dequeuing new ones. Sequential chain runs to completion. In-progress sessions are not killed.
- **Second SIGINT**: Force `process.exit(1)` immediately.

Files that were never dequeued remain untouched — they will be picked up on the next batch run.

## Session Lifecycle

Each item gets a fresh ephemeral session:

```
createSession() → attachSubscriptionLogger() → prompt(1)
    → [chain: postProcess() → verify() → markDone() → dispose()]
    │
    └── stall timer (inactivity → dispose() → requeue)
```

Crucially: sessions are created per-item, not reused across items. This avoids context pollution and ensures clean state for each prompt.

## Extension Loading

Batch runs are headless and parallel. Most extensions provide interactive features (TUI widgets, keybindings) that are irrelevant. Disable extension discovery by default:

```typescript
const loader = new DefaultResourceLoader({ noExtensions: true });
await loader.reload();
```

If specific extensions are needed (e.g., a custom tool), pass them via `additionalExtensionPaths` combined with `noExtensions: true` so only the listed extensions load.

## Code Organization

### Explicit state types

Pass state explicitly rather than capturing in closures. Use wrapper objects for shared mutable state so changes are visible across workers:

```typescript
const aborted = { value: false };
const counters = { completed: 0, failed: 0 };
const retryCounts = new Map<string, number>();
```

### Flat function structure

Organize the script into flat sections with no deep nesting:

```
Config          — constants, model selection, extensions
CLI args        — typed opts object from parseArgs()
Type config     — per-item-type configuration record
Logging         — stdout-only log function
Queue helpers   — item collection, completion tracking
Session helpers — session creation, subscription attachment
Verification    — post-processing validation, re-queue logic
Worker          — per-item prompt loop
Main            — orchestration: queue setup, worker pool, drain loop
```

### Prompt construction

Build prompts from arrays of strings joined with newlines:

```typescript
const prompt = [
  `/skill:my-skill Process @${filePath}`,
  `Task-specific instructions for this item type.`,
  `CRITICAL PARALLEL SAFETY: Create all utility scripts inside ${idDir}.`,
  `CRITICAL PARALLEL SAFETY: Remove all utility scripts after completing the task.`,
  `CRITICAL: Do not modify files belonging to other items.`,
  `Overwrite the target file with corrections. Preserve all formatting not needing correction.`
].join("\n");
```

### Subscription event logging

Attach a subscription to each session that logs events and resets the stall timer:

| Event                                         | Action                                           |
| --------------------------------------------- | ------------------------------------------------ |
| `auto_retry_start` / `auto_retry_end`         | Track SDK retries; on exhaustion, set error flag |
| `tool_execution_start` / `tool_execution_end` | Log truncated args/errors/results                |
| `message_end` (assistant)                     | If empty with no tool calls AND auto-retries occurred → set error flag |
| Any event                                     | Reset `lastActivity` timestamp                   |

### ⚠️ Multi-turn false-positive trap

When a single session runs multiple prompts (e.g., validation → prompt 1 → transcript), the SDK emits `message_end` events between turns that can have empty content with no tool calls. **These are normal bookkeeping events, not errors.**

A naive subscription logger flags *every* empty `message_end` as a 403/429 error. If an earlier turn's bookkeeping event sets the error flag, a later prompt that completed successfully (e.g., after 212 seconds) will trigger a false-positive fatal exit.

**Fix**: Only flag empty `message_end` as an error when auto-retries also occurred — that combination reliably indicates an API quota error. Isolated empty responses without retries are SDK bookkeeping.

**Fix**: Use duration-aware triage when checking the subscription error after a prompt resolves. If `prompt()` resolved without throwing and the prompt took a healthy amount of time (≥30 seconds), the session genuinely succeeded — log a warning instead of fatal-exiting. Real 403/429 errors fail in seconds, not minutes.

See **`references/batch-patterns.md` → Subscription error triage** for the complete pattern.

### Error triage in catch blocks

Order matters in catch blocks:

1. Clear stall timer (if alive)
2. Check `stallAborted` → re-queue, continue
3. Dispose session
4. Check rate-limit patterns → fatal exit
5. Otherwise → increment failed counter, log

Stall abort is checked before rate-limit because `dispose()` creates an error that might match rate-limit patterns.

### Rate-limit detection

Check error messages against a constant array of patterns: `429`, `403`, `rate limit`, `quota exceeded`, etc. On match, set `aborted = true` and exit — no point continuing.

### Verification and re-queue

After prompt 1 completes, verify the result (e.g., MD5 comparison of the target file). If the file wasn't modified and it needs to be, re-queue for retry up to a max retry count. If it wasn't modified and that's a valid outcome (no correction needed), treat as success.

## Dual-item pattern

When two related items must be processed in a single session (e.g., a metadata file and its companion tags file), use the dual-item pattern:

1. Collect paths where both items exist (skip orphans)
2. Snapshot both items' state before the session
3. Build a combined prompt referencing both items
4. Verify both items independently after the session
5. Mark both items as complete

This avoids coordination complexity between separate sessions for tightly coupled items.

## Logging from Pi's bash tool

Pi's bash tool writes truncated output to temp files (`/tmp/pi-bash-<id>.log`). On systems where `/tmp` is tmpfs with user quotas, long batch runs can exhaust the quota. Set up a systemd timer to clean up:

```
# ~/.config/systemd/user/pi-cleanup-tmp.service
[Service]
Type=oneshot
ExecStart=/usr/bin/find /tmp -maxdepth 1 -name 'pi-bash-*.log' -user %u -mtime +1 -delete

# ~/.config/systemd/user/pi-cleanup-tmp.timer
[Timer]
OnCalendar=daily

[Install]
WantedBy=timers.target
```

Enable with `systemctl --user enable --now pi-cleanup-tmp.timer`.

## Multi-turn session error handling

When a session runs multiple prompts sequentially (validation → correction → post-processing), errors detected via subscription events must be triaged carefully:

1. **Auto-retry correlation**: Only treat empty assistant responses as API errors when `auto_retry_start`/`auto_retry_end` events preceded them. SDK bookkeeping between turns produces empty `message_end` events that are benign.

2. **Duration-aware triage**: After a `prompt()` call resolves successfully, check how long it took. If it ran for a healthy duration (e.g., ≥30 seconds), the prompt almost certainly succeeded — even if a subscription error flag was set by an earlier turn's bookkeeping event. Real quota/rate-limit errors cause fast failures, not minutes-long successful runs.

3. **Reset error flags per prompt**: If the duration check passes, clear the subscription error flag so that downstream post-processing does not re-trigger the fatal exit.

```typescript
subscriptionError = sub.subscriptionError();
if (subscriptionError) {
  if (duration >= PROMPT_MIN_HEALTHY_DURATION_MS) {
    log(`${num} ⚠️ Subscription error detected but prompt ran ${duration}ms — treating as non-fatal`);
    subscriptionError = null; // clear for downstream
  } else {
    // Fast completion + subscription error → genuine API failure
    session.dispose();
    aborted.value = true;
    await fatalRateLimit(subscriptionError, "prompt subscription");
  }
}
```

## Additional Resources

- **`references/batch-patterns.md`** — Detailed code sketches and complete implementation recipes for each pattern layer
