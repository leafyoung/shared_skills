# Batch Processing Code Recipes

Detailed implementation sketches for the patterns described in `SKILL.md`. These are starting points, not copy-paste solutions — adapt to your item types, prompts, and verification logic.

## Minimal Skeleton

The complete architecture in one file organized as flat sections:

```typescript
// === Config ===
const CONCURRENCY = 8;
const STALL_TIMEOUT_MS = 60_000;
const RATE_LIMIT_PATTERNS = [/429/, /403/, /rate limit/i, /quota exceeded/i];

// === CLI args ===
const opts = parseArgs({ /* ... */ });

// === Type config ===
interface ItemConfig {
  collect: () => Promise<string[]>;
  buildPrompt: (path: string) => string;
  verify: (pre: FileSnapshot, post: FileSnapshot, path: string) => Outcome;
}

// === Logging ===
function log(msg: string) { process.stdout.write(msg + '\n'); }

// === File helpers ===
async function md5sum(path: string): Promise<string> { /* ... */ }

interface FileSnapshot {
  path: string;
  md5: string;
}

async function snapshotFile(path: string): Promise<FileSnapshot> {
  return { path, md5: await md5sum(path) };
}

// === Done tracking ===
const doneSet = await loadDoneSet(doneFile);

async function loadDoneSet(doneFile: string): Promise<Set<string>> {
  try {
    const content = await fs.readFile(doneFile, 'utf-8');
    return new Set(content.split('\n').filter(Boolean));
  } catch {
    return new Set();
  }
}

async function markDone(path: string) {
  await fs.appendFile(doneFile, path + '\n');
}

// === Rate-limit detection ===
function isRateLimitError(err: unknown): boolean {
  const msg = String(err);
  return RATE_LIMIT_PATTERNS.some(p => p.test(msg));
}

// === Session helpers ===
async function createSession(): Promise<AgentSession> {
  const authStorage = AuthStorage.create();
  const modelRegistry = ModelRegistry.create(authStorage);

  const loader = new DefaultResourceLoader({ noExtensions: true });
  await loader.reload();

  const { session } = await createAgentSession({
    model: getModel('anthropic', 'claude-sonnet-4-5'),
    thinkingLevel: 'off',
    authStorage,
    modelRegistry,
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(),
  });
  return session;
}

function attachSubscriptionLogger(
  session: AgentSession,
  onStall: () => void,
): { subscriptionError: { value: unknown | null }; clearTimer: () => void } {
  const subscriptionError = { value: null as unknown | null };
  let lastActivity = Date.now();
  let stallTimer: NodeJS.Timeout | null = null;

  function resetStallTimer() {
    lastActivity = Date.now();
    if (stallTimer) clearTimeout(stallTimer);
    stallTimer = setTimeout(() => {
      onStall();
    }, STALL_TIMEOUT_MS);
  }
  resetStallTimer();

  session.subscribe((event) => {
    resetStallTimer();
    switch (event.type) {
      case 'auto_retry_end':
        if (event.exhausted) subscriptionError.value = new Error('Auto-retry exhausted');
        break;
      case 'tool_execution_start':
        log(`  Tool: ${event.toolName}`);
        break;
      case 'tool_execution_end':
        if (event.isError) log(`  Tool error: ${(event.error || '').toString().slice(0, 300)}`);
        break;
      case 'message_end':
        if (event.role === 'assistant') {
          const text = event.message?.content?.filter((c: any) => c.type === 'text').map((c: any) => c.text).join('') || '';
          const hasToolCalls = event.message?.content?.some((c: any) => c.type === 'tool_use');
          if (!text && !hasToolCalls) {
            subscriptionError.value = new Error('Empty assistant response');
          }
        }
        break;
    }
  });

  return {
    subscriptionError,
    clearTimer: () => { if (stallTimer) clearTimeout(stallTimer); },
  };
}

// === Verification ===
async function verifyAndMarkDone(
  pre: FileSnapshot,
  path: string,
): Promise<'done' | 'requeue'> {
  const postMd5 = await md5sum(path);
  if (postMd5 !== pre.md5) {
    await markDone(path);
    return 'done';
  }
  // File unchanged — decide based on item type whether to retry
  return 'requeue';
}

// === Worker ===
interface PostProcessJob {
  session: AgentSession;
  pre: FileSnapshot;
  path: string;
  subscriptionError: { value: unknown | null };
}

async function runWorker(
  queue: string[],
  sequentialChain: Promise<void>,
  aborted: { value: boolean },
  counters: { completed: number; failed: number },
  fileCounter: { value: number },
): Promise<void> {
  while (!aborted.value && queue.length > 0) {
    const path = queue.shift()!;
    fileCounter.value++;
    const num = fileCounter.value;
    log(`[${num}] Processing: ${path}`);

    const pre = await snapshotFile(path);

    let stallAborted = false;
    const session = await createSession();
    const { subscriptionError, clearTimer } = attachSubscriptionLogger(session, () => {
      stallAborted = true;
      session.dispose();
    });

    try {
      await session.prompt(buildPrompt(path));

      // Check for stall after prompt resolves
      if (stallAborted) {
        clearTimer();
        if (!aborted.value) queue.push(path);
        session.dispose();
        continue;
      }

      clearTimer();

      // Chain post-processing (do NOT await)
      const job: PostProcessJob = { session, pre, path, subscriptionError };
      sequentialChain = sequentialChain.then(() => postProcess(job, aborted, counters, queue));
    } catch (err) {
      clearTimer();
      if (stallAborted) {
        if (!aborted.value) queue.push(path);
        continue;
      }
      session.dispose();
      if (isRateLimitError(err)) {
        aborted.value = true;
        log(`FATAL: Rate limit — ${String(err).slice(0, 200)}`);
        process.exit(1);
      }
      counters.failed++;
      log(`[${num}] Failed: ${String(err).slice(0, 300)}`);
    }
  }
}

// === Post-processing ===
async function postProcess(
  job: PostProcessJob,
  aborted: { value: boolean },
  counters: { completed: number; failed: number },
  queue: string[],
): Promise<void> {
  const { session, pre, path, subscriptionError } = job;
  try {
    if (subscriptionError.value) {
      throw subscriptionError.value;
    }
    const outcome = await verifyAndMarkDone(pre, path);
    if (outcome === 'requeue' && !aborted.value) {
      queue.push(path);
      log(`Re-queued: ${path}`);
    } else {
      counters.completed++;
      log(`Done: ${path}`);
    }
  } catch (err) {
    counters.failed++;
    log(`Post-process failed: ${String(err).slice(0, 300)}`);
  } finally {
    session.dispose();
  }
}

// === Main ===
async function main() {
  const aborted = { value: false };
  const counters = { completed: 0, failed: 0 };
  const fileCounter = { value: 0 };

  const queue = (await collectFiles()).filter(p => !doneSet.has(p));
  log(`Files to process: ${queue.length}`);

  let sigintCount = 0;
  process.on('SIGINT', () => {
    sigintCount++;
    if (sigintCount >= 2) {
      log('Second SIGINT — forcing exit');
      process.exit(1);
    }
    aborted.value = true;
    log('SIGINT received. Finishing current items... (Ctrl+C again to force exit)');
  });

  let sequentialChain: Promise<void> = Promise.resolve();

  do {
    const workers = Array.from({ length: CONCURRENCY }, () =>
      runWorker(queue, sequentialChain, aborted, counters, fileCounter)
    );
    await Promise.all(workers);
    await sequentialChain;
  } while (queue.length > 0 && !aborted.value);

  log(`Completed: ${counters.completed}, Failed: ${counters.failed}`);
}

main().catch(err => {
  console.error('Batch failed:', err);
  process.exit(1);
});
```

## Prompt Construction Recipe

Prompts are arrays of strings joined with `\n`. Each item carries its own context:

```typescript
function buildPrompt(filePath: string): string {
  const idDir = path.join(path.dirname(filePath), '../..'); // adjust per layout

  return [
    `/skill:my-domain-skill Correct @${filePath}`,
    ``,
    `Task instructions:`,
    `- Detect and fix specific error patterns`,
    `- Preserve all formatting not needing correction`,
    ``,
    `CRITICAL PARALLEL SAFETY:`,
    `- Multiple sessions run concurrently, each processing a different ID.`,
    `- Create ALL utility scripts inside: ${idDir}`,
    `- Remove ALL utility scripts from ${idDir} after completing the task.`,
    `- NEVER modify files belonging to another ID.`,
    ``,
    `OVERWRITE the target file with corrections. Write the complete corrected file.`,
  ].join('\n');
}
```

### Per-type prompt configuration

When handling multiple item types, use a type config record:

```typescript
interface TypeConfig {
  skill: string;          // e.g., '/skill:my-skill'
  collect: () => Promise<string[]>;
  buildPrompt: (path: string) => string;
  doneFile: string;
  idDir: (path: string) => string;  // maps file path → isolated directory
}

const TYPE_CONFIGS: Record<string, TypeConfig> = {
  srt: {
    skill: '/skill:transcribe-skill Correct @${path}',
    collect: () => glob('data/**/*.srt'),
    buildPrompt: (p) => buildPrompt(p, join(dirname(p), '.')),
    doneFile: 'done_srt.txt',
    idDir: (p) => join(dirname(p), '.'),
  },
  meta: {
    skill: '/skill:meta-review Review @${path}',
    collect: () => glob('data/**/*.meta.txt'),
    buildPrompt: (p) => buildPrompt(p, join(dirname(p), '..')),
    doneFile: 'done_meta.txt',
    idDir: (p) => join(dirname(p), '..'),
  },
};
```

## Dual-Item Pattern Recipe

When two tightly-coupled items must be processed together:

```typescript
interface DualSnapshot {
  primary: FileSnapshot;
  secondary: FileSnapshot;
}

function secondaryPath(primary: string): string {
  return primary.replace(/\.primary\.txt$/, '.secondary.txt');
}

function buildDualPrompt(primary: string, secondary: string): string {
  const idDir = path.dirname(primary);
  return [
    `/skill:my-skill Review both @${primary} and @${secondary}`,
    `These files are related — verify consistency between them.`,
    `CRITICAL PARALLEL SAFETY: Create utility scripts inside ${idDir}.`,
    `CRITICAL PARALLEL SAFETY: Remove utility scripts after task.`,
    `OVERWRITE both files with corrections.`,
  ].join('\n');
}

async function collectDualItems(): Promise<string[]> {
  const allPrimary = await glob('data/**/*.primary.txt');
  return allPrimary.filter(p => fs.existsSync(secondaryPath(p)));
}

async function snapshotDual(primary: string): Promise<DualSnapshot> {
  return {
    primary: await snapshotFile(primary),
    secondary: await snapshotFile(secondaryPath(primary)),
  };
}

async function verifyDual(
  snap: DualSnapshot,
  primary: string,
): Promise<'done' | 'requeue' | 'fatal'> {
  const secondary = secondaryPath(primary);
  const primaryChanged = (await md5sum(primary)) !== snap.primary.md5;
  const secondaryChanged = (await md5sum(secondary)) !== snap.secondary.md5;

  if (primaryChanged || secondaryChanged) {
    await markDone(primary);
    await markDone(secondary);
    return 'done';
  }
  return 'requeue';
}
```

The worker for dual items passes `DualSnapshot` through the `PostProcessJob` instead of a single `FileSnapshot`.

## Graceful Shutdown Details

### Two-level SIGINT

```typescript
let sigintCount = 0;
process.on('SIGINT', () => {
  sigintCount++;
  if (sigintCount >= 2) {
    log('Second SIGINT — forcing immediate shutdown');
    process.exit(1);
  }
  aborted.value = true;
  log(
    'SIGINT received. No new tasks will be started. ' +
    'Waiting for current tasks to finish... ' +
    '(Press Ctrl+C again to force exit)'
  );
});
```

### Behavior per layer

| Layer | Action on first Ctrl+C |
|-------|----------------------|
| Worker `while` loop | Exits immediately — no new item dequeued |
| Worker mid-prompt | Finishes current prompt, chains post-processing, then exits |
| Post-processing chain | Runs to completion for all chained jobs |
| Stall detected mid-shutdown | Item is **discarded** (not re-queued) |
| Unchanged item retry | Item is **discarded** — verify checks `!aborted.value` before re-queue |
| Main `do...while` | Exits because `!aborted.value` is false |

### Effect on done-file tracking

Items that were still processing when Ctrl+C arrived:
- If a session completed prompt 1 **before** the interrupt, the item was corrected on disk, and post-processing marks it done.
- If a session was still running when Ctrl+C arrived, it finishes prompt 1, and post-processing marks it done.
- Items that were **never dequeued** remain unmarked — processed on the next batch run.

## Session Creation with Extension Control

### No extensions (default for batch)

```typescript
const loader = new DefaultResourceLoader({ noExtensions: true });
await loader.reload();
```

### Specific extensions only

```typescript
const ENABLED_EXTENSIONS: string[] = [
  '/path/to/custom-tool-extension.ts',
];

const loader = new DefaultResourceLoader({
  noExtensions: true,
  additionalExtensionPaths: ENABLED_EXTENSIONS,
});
await loader.reload();
```

When `additionalExtensionPaths` is non-empty and `noExtensions: true`, only those paths load — nothing from global or project settings.

## Subscription Logger Recipe

```typescript
function attachSubscriptionLogger(
  session: AgentSession,
  onStall: () => void,
): {
  subscriptionError: { value: unknown | null };
  clearTimer: () => void;
  activityTimestamp: { value: number };
} {
  const subscriptionError = { value: null as unknown | null };
  const activityTimestamp = { value: Date.now() };
  let stallTimer: NodeJS.Timeout | null = null;

  function resetTimer() {
    activityTimestamp.value = Date.now();
    if (stallTimer) clearTimeout(stallTimer);
    stallTimer = setTimeout(onStall, STALL_TIMEOUT_MS);
  }
  resetTimer();

  session.subscribe((event) => {
    resetTimer();

    switch (event.type) {
      case 'auto_retry_start':
        log(`  [retry] Attempt ${event.attempt}/${event.maxAttempts}`);
        break;
      case 'auto_retry_end':
        if (event.exhausted) {
          subscriptionError.value = new Error(
            `Auto-retry exhausted after ${event.attempts} attempts`
          );
        }
        break;

      case 'tool_execution_start':
        log(`  Tool: ${event.toolName}(${JSON.stringify(event.args || {}).slice(0, 200)})`);
        break;
      case 'tool_execution_end':
        if (event.isError) {
          log(`  Tool error: ${String(event.error || '').slice(0, 300)}`);
        }
        break;

      case 'message_end':
        if (event.role === 'assistant') {
          const text = extractText(event.message);
          const toolCalls = extractToolCalls(event.message);
          if (!text && toolCalls.length === 0) {
            subscriptionError.value = new Error('Empty assistant message');
          } else if (text) {
            log(`  Response: ${text.slice(0, 200)}${text.length > 200 ? '...' : ''}`);
          }
          if (toolCalls.length > 0) {
            log(`  Tool calls: ${toolCalls.join(', ')}`);
          }
        }
        break;

      case 'turn_end':
        log(`  Turn complete (${event.toolResults?.length || 0} tool results)`);
        break;
      case 'agent_end':
        log(`  Agent finished (${event.messages?.length || 0} new messages)`);
        break;
    }
  });

  return {
    subscriptionError,
    clearTimer: () => { if (stallTimer) clearTimeout(stallTimer); },
    activityTimestamp,
  };
}

function extractText(msg: any): string {
  return (msg?.content || [])
    .filter((c: any) => c.type === 'text')
    .map((c: any) => c.text)
    .join('');
}

function extractToolCalls(msg: any): string[] {
  return (msg?.content || [])
    .filter((c: any) => c.type === 'tool_use')
    .map((c: any) => c.name);
}
```

## Catch-Block Error Triage Order

Order matters — stall abort must be checked before rate-limit because `dispose()` creates an error string that might coincidentally match rate-limit patterns:

```typescript
try {
  await session.prompt(promptText);
  // ... success path
} catch (err) {
  // 1. Clear stall timer (if still alive)
  clearTimer();

  // 2. Stall abort — re-queue, do NOT count as failure
  if (stallAborted) {
    if (!aborted.value) {
      log(`Re-queuing ${path} after stall`);
      queue.push(path);
    } else {
      log(`Discarding ${path} — shutting down`);
    }
    session.dispose();
    continue;
  }

  // 3. Dispose session
  session.dispose();

  // 4. Rate-limit — fatal, stop everything
  if (isRateLimitError(err)) {
    aborted.value = true;
    log(`FATAL: Rate limit detected: ${String(err).slice(0, 300)}`);
    process.exit(1);
  }

  // 5. Genuine failure — count and move on
  counters.failed++;
  log(`[${num}] Failed: ${String(err).slice(0, 300)}`);
}
```

## Verification with Retry Limits

```typescript
const MAX_UNCHANGED_RETRIES = 3;

async function verifyAndMarkDoneWithRetry(
  pre: FileSnapshot,
  path: string,
  retryCounts: Map<string, number>,
  aborted: { value: boolean },
): Promise<'done' | 'requeue' | 'fatal'> {
  const postMd5 = await md5sum(path);

  // File modified — success
  if (postMd5 !== pre.md5) {
    await markDone(path);
    return 'done';
  }

  // File unchanged — decide based on context
  if (isRetryableType(path)) {
    const count = (retryCounts.get(path) || 0) + 1;
    retryCounts.set(path, count);

    if (count > MAX_UNCHANGED_RETRIES) {
      return 'fatal';
    }

    if (aborted.value) {
      log(`Discarding ${path} — shutting down`);
      return 'done'; // treat as done to avoid re-queue during shutdown
    }

    return 'requeue';
  }

  // No changes needed — valid success
  await markDone(path);
  return 'done';
}
```

## Log Message Truncation Helper

```typescript
function truncate(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + '... [truncated]';
}

function logTruncated(label: string, content: unknown, maxLen: number = 200): void {
  const str = typeof content === 'string' ? content : JSON.stringify(content);
  log(`  ${label}: ${truncate(str, maxLen)}`);
}
```

## Timing Diagram

```
Time ──────────────────────────────────────────────►

Worker 1:  [prompt 1 on A ────────] chain → postProcess(A)
           ↳ picks B ─────────────────────────────────────────

Worker 2:  [prompt 1 on C ───────────────────] chain → postProcess(C)
           ↳ picks D ─────────────────────────────────────────

Seq chain:                        postProcess(A)   postProcess(C)  ...

Worker 3:  [prompt 1 on E ──────────────────────────] chain → postProcess(E)
```

Key properties:
- **No worker barrier** — post-processing starts as soon as the first worker finishes prompt 1
- **Other workers keep running** — not blocked by the sequential chain
- **Sequential chain preserves FIFO order** — callbacks execute in the order they were chained, matching prompt 1 completion order
