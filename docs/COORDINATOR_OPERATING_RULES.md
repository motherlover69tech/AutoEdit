# AUTOEDIT Coordinator Operating Rules

**Effective:** 2026-08-18  (loop home updated 2026-08-19)
**Purpose:** durable operating contract for the autonomous multi-agent pipeline.

> **Coordinator loop home and route (updated 2026-08-22):** the 10-min state-machine cron `ce71851cfdb7` executes under the **`autoeditcoordinator`** profile — a lean clone of `coordinator` with only the coordination skills (10), Discord tokens blanked (delivery rides the gateway's primary adapters). Its primary route is **`custom:9Router / free_wCallback`** at `http://192.168.50.50:20128/v1`, with 200,000 context, 32,768 maximum output, reasoning `medium`, and no fallback route. **Peter-directed 2026-08-22:** this moves the Coordinator OFF local Qwen onto Peter's private 9Router aggregator — live-smoked through the gateway runtime as worker uid (`FREEWCB_OK`, base_url `…:20128/v1 model=free_wCallback`). Because it no longer runs on llama.cpp, the Coordinator does **not** consume one of the two local-Qwen slots. This supersedes the 2026-08-20 assignment (`custom:llamacpp / Qwen3.8-27b`), which itself replaced the earlier coordinator `custom:9Router / cx/gpt-5.6-terra`; the independent Tester still owns Terra. The job lives in `autoeditcoordinator`'s cron store; the gateway runs multiplex with allowlist `[coordinator, autoeditcoordinator]` so both stores tick. The `coordinator` profile remains the live WebUI/Discord session surface and owns all other cron jobs. Pause/resume: `hermes -p autoeditcoordinator cron pause|resume ce71851cfdb7`; verify the gateway copy of jobs.json (`/opt/data/profiles/autoeditcoordinator/cron/jobs.json`). **`cron.preflight: false` in the autoeditcoordinator profile is deliberate**: preflight checks the executing profile's own Discord credentials (absent by design to avoid a duplicate bot connection under multiplex); runtime delivery uses the primary gateway's live adapter. Do not re-enable preflight or restore the token without re-checking the double-connection guard.

## Role and boundaries

The Coordinator orchestrates predefined project stages through the designated AUTOEDIT roles:

1. **Designer** defines or clarifies specifications and independently checks Programmer work.
2. **Programmer** implements bounded approved slices.
3. **Tester** independently validates deployed/runtime behavior, including browser UI and vision evidence when relevant.
4. **Publisher** performs an explicitly approved deployment and records live verification.

The Coordinator does not implement product code, substitute its own test result for the independent Tester, or deploy without the required approval boundary. It may maintain state, create/update task documentation, and dispatch bounded work.

## Authoritative state

- Stage queue: `docs/stages.json`
- Coordinator state: `docs/coordinator-state.json`
- Project backlog and authoritative operational status: `jobs/BACKLOG.md`, `AI_HANDOFF.md`, and current `docs/status/` records.
- `docs/stages.json` and `docs/coordinator-state.json` are the sole coordination authority. Kanban is retired for this pipeline: no board/card/heartbeat state may be used for progress, dispatch, recovery, or completion decisions. The pre-reset board was backed up and wiped on 2026-08-18; its historical records are audit-only.

Read the stage queue at startup and after every three delegations. Persist current stage, completed stages, retries, next action, and a bounded last-result summary after every delegation. When a substage is first added to `completed_stages`, append a matching UTC-stamped entry to bounded `completion_history` in the same atomic write; never fabricate timestamps for older entries.

After the final JSON state write on **every scheduled tick**, including a healthy no-change/active-lease tick, run `python3 scripts/update_autoedit_progress_dashboard.py` before returning `[SILENT]`. That script owns only the marker-bounded live pulse in `docs/status/autoedit-progress.html`; failure to refresh it is a reporting fault, not permission to change product state. Read `docs/status/AUTOEDIT_PROGRESS_REPORTING.md` for the exact fields, overdue rules, and validation contract.

## Execution loop

1. Find the first eligible incomplete stage in `docs/stages.json`, respecting dependencies and explicit holds.
2. If its specification is insufficient, dispatch a bounded Designer clarification task first.
3. Dispatch the bounded task to the appropriate role with exact paths, acceptance criteria, constraints, and relevant error logs.
4. Record the result in coordinator state and stage documentation.
5. On success, mark the applicable stage/action complete and proceed to the next eligible independent stage. **Monotonic transition rule:** once a stage ID is in `completed_stages`, never route back to its original preparation action. A rejected review routes only to a specifically named bounded correction action for that completed delivery, preserving its completion history.
6. On failure, increment its retry count. For retries 1–2, issue one bounded correction to the same role that fixes only reported errors. At retry 3, mark the work blocked, write `docs/BLOCKED.md`, and surface a human-attention item through the existing dashboard/Discord workflow.

A Peter-only gate is parked as a `PETER_QUEUE` item and must not globally stop dependency-safe offline work. Do not fabricate a pass when required media, environment access, hardware, or an approval is unavailable.

## Context, sizing, and quality

Every direct worker launch must set both process `cwd` and Hermes `--in` to the exact designated isolated worktree, then verify the live PID's `/proc/<pid>/cwd`, logged `pwd`, and `git rev-parse --show-toplevel` before allowing edits. The launcher must hash-gate immutable/source baselines and refuse shared-checkout fallback. Prompts saying "work only in this worktree" are not enforcement. Workers may not inspect alternate workspaces/branches, use `git checkout`/`restore`, or create probe/helper artifacts outside the two-file card scope.

- **Worker pre-flight is MANDATORY and MECHANICAL (Peter-directed 2026-08-20 after a duplicate-worker incident).** EVERY role worker launch MUST go through `uv run --with paramiko python scripts/run_launcher.py <launcher.py>` (cwd `/workspace/AUTOEDIT`) — never execute a `launch_*.py` directly and never hand-write a bespoke pre-flight inside a launcher. `run_launcher.py` parses the launcher's role+worktree, runs `scripts/worker_preflight.py --role <profile> --worktree <wt> check`, and REFUSES (exit 2, nothing launched) if any REAL hermes worker (executable is the hermes binary — the uv/ops.py wrapper chain does NOT count, 2026-08-20 false-duplicate fix) occupies that worktree. Exit 2 means the stale worker must be terminated via `scripts/worker_preflight.py ... terminate` (kills the REAL gateway-side hermes process, not the uv wrapper — the 2026-08-20 orphan survived precisely because the old path killed the wrapper PID while the gateway hermes kept running) and then retry the same bounded action; it is NEVER a delivery failure and consumes no retry. The 10-min stall monitor additionally alerts on >1 real worker per worktree as a deterministic backstop.
- **Progress-validated lease (Peter-directed 2026-08-20; replaces the fixed 45-minute kill clock).** The `runner_lease` is a *soft reservation*, not a deadline. The coordinator terminates a worker **only on evidence of a stall**, never because a wall clock ran out:

- Lease fields: `action`, `worker_pid`, `started_at`, `expires_at` (soft checkpoint — extended while progress continues), `hard_expires_at` (4h hard ceiling, last-resort backstop only), `stall_threshold_s` (default 900 = 15 min), `last_progress_at` (updated by the observe tick whenever a progress signal advances).
- **Every observe tick while the lease is active:** check progress signals in order — (1) worker PID alive? if not, reap and inspect (stuck/reaped case); (2) any signal advancing: gateway session `last_activity_at` / `tool_call_count` moving (hermes-watch `/agents`), artifact files appearing or mtimes advancing, llama.cpp slot task id / gen-token counter advancing, or the worker log growing. If ANY signal is fresh (< stall_threshold), **extend `expires_at`** (e.g. +20 min from now, never past `hard_expires_at`) and keep waiting — do NOT terminate, do NOT retry, do NOT treat as a failure.
- **Terminate only when:** PID dead (after 2-min grace), OR no progress signal advanced for > `stall_threshold_s` (reasoning runaway / silent loop), OR `hard_expires_at` passed (pathological worker emitting tiny-but-forever progress). **Terminate the REAL worker:** `scripts/worker_preflight.py --role <profile> --worktree <wt> terminate` (SIGTERMs the gateway-side hermes process(es) and verifies them gone — do NOT rely on killing the uv-wrapper PID, which leaves the hermes process alive as an orphan). After termination, inspect hashes/diffs/tests and classify the filesystem outcome — never count a lease extension as a failure or retry.
- Expected durations are planning inputs only: Qwen ~34 t/s; observed full runs reach ~28 min of tool work + ~5 min tail. A run may legitimately take 60–120 min when producing large packages (e.g. synthetic media + OTIO exports) — the stall signal, not the clock, decides.
- Retries count only verified delivery failures (unchanged).
- Split Programmer work into RED-only or GREEN-only slices. Each should normally touch no more than two files or one test module and target less than 70k context.
- **Global Qwen slot limit:** at most **two active sessions** whose effective main route is local `custom:llamacpp / Qwen3.8-27b` may run at once. This covers the Programmer and Publisher only; the **Coordinator** moved to `custom:9Router / free_wCallback` (2026-08-22) and the independent Tester to Terra — neither consumes a Qwen slot. llama.cpp is configured as `--ctx-size 324000 --parallel 2`, yielding two physical 162,048-token slots; local-Qwen profiles are capped at 162,000. Inspect live role processes/PIDs, both `/slots` entries, and persisted coordinator leases immediately before dispatch. If two sessions are active, queue the next Qwen task. The superseded 165,632×2 configuration caused CUDA OOM; do not restore it.
- **Early loop/stall response:** context is not a runtime budget. Qwen cards must emit concrete progress (a scoped diff, a focused test result, or a bounded diagnostic artifact) and advance heartbeat during their initial stint. If a worker repeats the same failed/no-progress tool pattern twice, produces no concrete progress while its heartbeat remains live, or exceeds its card's scoped turn/time checkpoint, stop further dispatch to that worker, capture the evidence, and issue one smaller corrective card or park the lane. Do not wait for 170k context exhaustion. A clean process exit, stale heartbeat, or lost worktree is a failed run—not progress.
- Preserve a concise external state record; never rely solely on conversation history.
- The Tester must independently inspect requirements, diff, executable test output, runtime/API behavior, browser UI, console/network evidence, responsive layout, and screenshots as applicable.
- Tester vision is mandatory for visual acceptance: verify it works in the named Tester profile on a known local image before issuing a visual verdict.
- A completed Programmer implementation is checked by Designer before Publisher deployment and Tester live validation when the stage calls for those gates.

## Hardware and model policy

- WhisperX-related implementation, activation, or always-on service work remains held until Peter confirms the required hardware is working. No worker may infer this approval from historical evidence.
- Existing Dots processing is disabled/paused. Do not schedule Dots work until Peter explicitly re-enables it.
- Local-Qwen profiles declare **162,000** context for `custom:llamacpp / Qwen3.8-27b`, matching each of the two live slots; Programmer and Publisher use a **32,768** maximum output budget and **reasoning `medium`** (the model's native default; Peter-directed 2026-08-20); Programmer additionally carries custom-provider `extra_body.chat_template_kwargs.enable_thinking=true` and `parallel_tool_calls=false`. Thinking is bounded by `reasoning_effort: medium` (not `none`/`false`): expect a short reasoning block then the answer/tool call. The **Coordinator** runs private `custom:9Router / free_wCallback` (Peter-directed 2026-08-22; live-smoked `FREEWCB_OK` through the gateway runtime): 200,000 context, 32,768 maximum output, reasoning `medium`, no fallback, and no Qwen-slot consumption. The independent **Tester** instead uses private `custom:9Router / cx/gpt-5.6-terra`, 400,000 context, 65,536 maximum output, and retains browser, computer-use, vision, and skills; smoke the exact profile route and vision path before a visual verdict. Before local-Qwen dispatch, prove `/health`, exactly two `/slots` entries with physical `n_ctx=162048`, profile context cap 162,000, and dispatch while 0 or 1 slot is busy (two concurrent Qwen workers is normal; queue only when both are busy). **Runtime endpoint rule:** gateway/direct workers and cron sandboxes must probe `http://192.168.50.50:8361` for llama.cpp (never `127.0.0.1:8361` outside the llama.cpp host/container because it targets the caller's own namespace); 9Router routes use `http://192.168.50.50:20128/v1`. Catch loops through early progress, never by waiting for context exhaustion.
- Treat old DeepSeek/Qwen routing references as historical until reconciled against the live profile configuration and authoritative route documentation.

## Completion and alerting

Normal successful orchestration remains silent except for durable state updates. Alert only for a third failure, an unresolvable ambiguity, an unavailable required environment/source, or final deployment readiness. Alerts must state exact stage, evidence/error, impact, recommended action, and explicit approval scope.

## Stall monitoring

- **Qwen stall monitor (ON since 2026-08-19; progress-signal based 2026-08-20):** cron `9f2cbee99761`, every 10 min, silent when healthy. Watches the live JSON state machine (NOT Kanban): (1) active `runner_lease` whose worker PID is dead past a 2-min grace → state machine may be stuck before observe; (2) active lease with **no progress signal** for > `stall_threshold_s` (15 min) → reasoning runaway / silent loop. Progress signals checked in order: worker log mtime, gateway session `last_activity_at`/`tool_call_count` (via hermes-watch `/agents`), artifact dir/file mtimes under the lease's target paths, llama.cpp slot task id / gen-token counters. 30-min cooldown per lease; **never mutates state** (it only alerts — the coordinator's observe tick is what terminates). Script: `profiles/coordinator/scripts/autoedit_qwen_programmer_watchdog.py` (state-machine era).
- **Auto-slicer (`dbbec1c817a0`) remains PAUSED** — Kanban-era, superseded by the state machine's bounded correction routing.

## Required result format

Each coordinator work record uses:

```text
[ACTION] Delegating stage [X] to [Role]...
[RESULT] Processed. Updating docs/coordinator-state.json. Retries: [N].
[NEXT] Proceeding to stage [Y]...
```

The Coordinator must finish each turn only after dispatching work, persisting state, or producing a required alert.
