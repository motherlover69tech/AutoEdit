# AUTOEDIT Kanban Slicer + Qwen Worker System — Handoff

> Written 2026-08-17 after a session that fixed the auto-slicer loop end-to-end and
> then hit the Qwen worker's fundamental reliability ceiling. **Pick up here when
> resuming AUTOEDIT agent work, or when swapping the Programmer/Tester model to
> DeepSeek V4 Flash.**

---

## 0. TL;DR

- The **auto-slicer now works end-to-end**: stalled card → blocked → WIP snapshot → reset → re-sliced as tiny cards → re-dispatched. It is model-independent and lives in the coordinator (paid `cx/gpt-5.6-sol`), so it keeps working regardless of the worker model.
- The **Qwen3.8-27b worker is the weak link**: it stalls on the 100k context ceiling, runs away in hidden reasoning, and **ignores "tests-only / don't touch src/"** — it implemented the whole consent gate instead of writing a RED test. Switching to **DeepSeek V4 Flash** is a reasonable move; §5 covers exactly what changes.
- The dispatcher's block/requeue semantics (§2) are subtle and were the main time sink this session — they are model-independent and documented precisely below.

---

## 1. Current board state (exact IDs)

Board DB (gateway = sandbox, same file):
- gateway: `/opt/data/kanban/boards/autoedit-agents/kanban.db`
- sandbox: `/home/hermeswebui/.hermes/kanban/boards/autoedit-agents/kanban.db`

F-AVSE-003 (visual consent-binding) cards:

| Card | Status | Meaning |
|---|---|---|
| `t_3a29fd29` | archived | original 11-condition RED card (too big → sliced) |
| `t_e666e0ba` | **blocked** | "missing media only" slice; worker went off-scope, WIP snapshotted at `38bd5d4` for direct review |
| `t_91e8e037` | todo | extra media (RED) — parent `t_e666e0ba` |
| `t_01335cca` | todo | unrelated media (RED) |
| `t_f1d6db33` | todo | forged media (RED) |
| `t_2c676767` | todo | reordered media (RED) |
| `t_4c8c157d` | todo | mismatched media (RED) |
| `t_d86f85b7` | todo | inactive consent (RED) |
| `t_b5fde438` | todo | withdrawn consent (RED) |
| `t_f9e9f683` | todo | expired/stale-retention consent (RED) |
| `t_9655edc5` | todo | model_processing_allowed=false (RED) |
| `t_83016744` | todo | derivative_allowed=false (RED) |
| `t_30090b6d` | todo | bounded_derived_evidence missing (RED) |

The 11 `todo` cards form a **parent-linked chain** (each `task_links` child depends on the previous card), so `recompute_ready` promotes them one-at-a-time as each parent completes — they share one worktree and must not run concurrently.

### Worktree + snapshots (`/workspace/AUTOEDIT/.worktrees/t_b0c0bd87`)

- Clean base: `f3d6314`
- `f65d8b1` — WIP snapshot of the original `t_3a29fd29` worker (558-line partial `test_visual_consent_binding.py`).
- `38bd5d4` — WIP snapshot of the off-scope `t_e666e0ba` worker: `+123` lines `src/autoedit/ai/golden_fixture.py` (the `consent_gate()` function + `ConsentGateBlocked` exception) and `+216` lines `tests/test_golden_fixture_contracts.py` (5 tests). **Reviewed: logic correct, field names valid, but `consent_gate()` is NOT wired into the L0 runner — dead code.** See §6 for the remaining GREEN work.

---

## 2. Dispatcher semantics (model-independent — read before touching cards)

The kanban dispatcher runs inside the coordinator gateway (`dispatch_in_gateway: true`). Key behaviours discovered this session:

1. **`recompute_ready` auto-unblocks blocked cards.** On every tick it promotes `todo`/`blocked` cards whose parents are all `done`/`archived` — **unless** the card has a *sticky block* OR `consecutive_failures >= failure_limit`. So a card you block by hand can silently bounce back to `ready` and get re-claimed.

2. **`failure_limit` is cached at dispatcher startup.** Editing `config.yaml` does nothing until the dispatcher restarts:
   ```sh
   docker exec hermes-gateway /command/s6-svc -t /run/service/gateway-coordinator
   ```
   Config key: `kanban.failure_limit` in `/opt/data/profiles/coordinator/config.yaml` (currently `1`).

3. **Per-card `max_retries` overrides the cached limit** and is read from the DB (immediate, no restart). Setting `max_retries=1` on a card is the fast way to make it block after one failure when the dispatcher hasn't been restarted.

4. **A raw SQL `status='blocked'` is not sticky** — `_has_sticky_block()` requires a `blocked` event row in `task_events`. The proper way is `hermes kanban block <id> --reason ...` (emits the event), or accept the circuit-breaker path (step 1's `consecutive_failures >= failure_limit`).

5. **A manual block MUST clear `claim_lock` and `claim_expires`** — otherwise `reconcile_orphans` treats it as "broken claim bookkeeping" and re-claims it. Correct SQL block:
   ```sql
   UPDATE tasks SET status='blocked', claim_lock=NULL, claim_expires=NULL,
     worker_pid=NULL, current_run_id=NULL, last_heartbeat_at=NULL,
     block_kind=NULL, block_recurrences=0, max_retries=1
   WHERE id='<id>';
   ```

6. **Workers are children of the coordinator gateway** but in their own process group — a `s6-svc -t gateway-coordinator` restart leaves running workers alive (they orphan to init). Kill a worker with `kill -9 <pid>` inside `hermes-gateway`.

---

## 3. The auto-slicer (works, model-independent)

- Cron job **`dbbec1c817a0`** ("AUTOEDIT stalled-card auto-slicer"), every **15m**, model **`cx/gpt-5.6-sol`** via 9Router, workdir `/workspace/AUTOEDIT`, toolsets terminal+file, delivers to Discord `1503163927578677281`.
- **Stall signature**: acts only on `status='blocked'` cards whose `last_failure_error` contains one of `elapsed` / `budget exhausted` / `response truncated` / `exited cleanly` / `protocol violation` / `context` / `iteration`.
- **Procedure**: snapshot WIP (`git add -A && git commit`) → `git reset --hard <base>` → create ONE tiny `ready` slice (one consent condition / rule / function) → **create a continuation card** (`todo`, parent-linked) listing the REMAINING conditions so nothing is lost → archive the original.
- Fixed this session: (a) slice finer — "one condition per card" instead of RED/GREEN; (b) add the continuation-card step so the remainder isn't dropped; (c) `max_retries=1` on created slices.
- Manual run: `cronjob(action='run', job_id='dbbec1c817a0')`; result re-enters the conversation.

Companion crons:
- `9f2cbee99761` — Qwen worker stall monitor, every 10m, alert-only (never mutates).
- `3d4dafa1eb69` — whole-pipeline coordinator watchdog, every 30m.

---

## 4. The Qwen worker — problems found and mitigations

Worker profiles run **`custom:llamacpp` / `Qwen3.8-27b`** on Tower's V100 (`http://192.168.50.50:8361/v1`, 2 slots × 100k ctx, auth key in the `local-server-ai` skill). Full stack detail lives in the `local-server-ai` skill.

Observed failure modes:

| Problem | Symptom | Mitigation |
|---|---|---|
| 100k context ceiling | worker compacts at ~75k, hits 120-turn budget | small cards + `max_turns=120` |
| Runaway hidden reasoning | slot shows open `<think>` + `n_predict=-1`, no tool calls | `reasoning_effort: none` + `model.max_tokens: 4096` |
| **Off-scope behaviour** | ignored "tests-only / don't touch src/", implemented `consent_gate()` | (unmitigated — this is the reason to switch models) |
| Tool-call 500s | Qwen emits `{...}{...}` concatenated JSON args | shim `:11435` drops tools+retries once |
| Slot switching | context in slot 0, generation in slot 1, 0 cache hit | symptom of the above, not separately fixed |

Config that matters (`/opt/data/profiles/autoeditprogrammer/config.yaml` and `autoedittester`):
- `model.max_tokens: 4096` (REQUIRED — Hermes custom-provider defaults to 65536 otherwise, enabling hidden reasoning).
- `reasoning_effort: none` (sends a closed `<think></think>` prefix).
- `context_length: 100000`.

**Conclusion:** Qwen3.8-27b with reasoning off cannot reliably follow "test-first, don't implement". The RED/GREEN discipline depends on the worker obeying the card; it doesn't.

---

## 5. Switching to DeepSeek V4 Flash — what to change

DeepSeek is already used elsewhere on this box (Petespods roundup, `deepseek-v4-flash`, key in coordinator `.env`). Proposed swap:

### Config changes (per worker profile)
- `provider`: `custom:llamacpp` → DeepSeek (native `deepseek` provider or a `custom:` provider pointing at DeepSeek's API; key already available in coordinator `.env`).
- `model`: `Qwen3.8-27b` → `deepseek-v4-flash`.
- `context_length`: `100000` → whatever DeepSeek V4 Flash supports (≥128k expected) — more headroom means fewer stalls.
- `reasoning_effort`: **decide deliberately.** DeepSeek V4 Flash is reasoning-capable; reasoning ON likely makes it *follow instructions better* (fixing the off-scope problem) but burns tokens/latency. Start with a low effort or `none` and observe; the off-scope failure is the thing to re-test first.
- `model.max_tokens`: keep an explicit cap (e.g. 4096–8192) — do NOT rely on defaults.

### What gets better
- **Instruction-following** (the #1 open risk): DeepSeek should obey "tests-only / don't implement", making RED/GREEN slicing viable again.
- **No llama.cpp issues**: no slot switching, no KV-cache ceiling, no local V100 VRAM contention, no `{...}{...}` tool-call 500s.
- **Tool-calling reliability**: better than Qwen; the `:11435` shim hardening becomes irrelevant for these workers.

### What stays the same (model-independent)
- The **dispatcher semantics** (§2) — nothing changes.
- The **auto-slicer** (§3) — keep it as a backstop; it may fire far less often.
- The **root-owned git-file trap** (§7).
- The **card granularity rule** — still keep cards small (one rule/condition), for cost and reliability even if the model is better.

### Things to re-evaluate after the swap
- `failure_limit`: with a more reliable model, `1` may be too aggressive (blocks on one transient failure). Consider `2`.
- The per-card `max_retries=1` workaround: no longer needed once the dispatcher runs with the intended `failure_limit` (restart after any change).
- Whether to keep `reasoning_effort=none` or let DeepSeek reason (trade token cost vs. correctness).

---

## 6. Open items / next steps

1. **Wire `consent_gate()` into the L0 runner** (GREEN): the reviewed impl (`38bd5d4`) is correct but uncalled. Call it before `extract_timestamped_frames` / `QwenVisualClient.assess` in the `scripts/evaluate_visual_speaker_evidence.py` path.
2. **Complete test coverage**: the 5 existing tests cover synthetic/missing/withdrawn/unconfigured/valid. The 11 chained RED cards cover the remaining denials — trim to the ~7 conditions still lacking tests (forged/reordered/mismatched media, inactive/expired consent, `model_processing=false`, `derivative=false`, missing `bounded_derived_evidence`) and either run them or fold them into the wiring card's tests.
3. **Decide the model** (DeepSeek V4 Flash) and re-run the "one tiny card" experiment to confirm instruction-following before scaling out.

---

## 7. Runbook: quick commands

```sh
# Restart the dispatcher (pick up config changes)
docker exec hermes-gateway /command/s6-svc -t /run/service/gateway-coordinator

# Fix root-owned git files (ops.py docker exec runs as ROOT)
docker exec hermes-gateway sh -c 'find /workspace/AUTOEDIT/.git -user root -exec chown hermes:users {} +'

# Run git as the worker user (not root)
docker exec -u 10000:100 -e HOME=/opt/data/profiles/autoeditprogrammer hermes-gateway git -C /workspace/AUTOEDIT/.worktrees/t_b0c0bd87 status --short

# Live llama.cpp slot state (key in local-server-ai skill)
curl -s -H "Authorization: Bearer <key>" http://192.168.50.50:8361/slots

# Properly block a card (emits the sticky 'blocked' event)
docker exec -u 10000:100 -e HOME=/opt/data/profiles/coordinator hermes-gateway hermes -p coordinator kanban block <id> --reason "..."
```
