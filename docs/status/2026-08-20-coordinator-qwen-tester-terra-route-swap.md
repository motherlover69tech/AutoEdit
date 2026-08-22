# AUTOEDIT role-route swap: Coordinator → Qwen, Tester → Terra

> **SUPERSEDED 2026-08-22 (Peter-directed):** the Coordinator moved again — `autoeditcoordinator` now runs `custom:9Router / free_wCallback` (200,000 context, 32,768 max output, `medium`, no fallback) and no longer consumes a local-Qwen slot. See `2026-08-22-coordinator-freewcallback-route-swap.md`. The Tester→Terra half of this record remains accurate.

**Effective:** 2026-08-20
**Scope:** the active state-machine Coordinator (`autoeditcoordinator`) and independent Tester (`autoedittester`) only.

## Decision

Peter reassigned the two primary routes:

| Role | Primary route | Context / output | Reasoning | Fallbacks |
|---|---|---:|---|---|
| State-machine Coordinator (`ce71851cfdb7`) | `custom:llamacpp / Qwen3.8-27b` | 162,000 / 32,768 | `medium` | none |
| Independent Tester | `custom:9Router / cx/gpt-5.6-terra` | 400,000 / 65,536 | `medium` | `cx/gpt-5.6-sol`, then `ds/deepseek-v4-pro` on private 9Router |

Private `custom:9Router` is permitted. Public `openrouter.ai` remains forbidden.

Coordinator, Programmer, and Publisher now share the two local-Qwen-slot budget; Tester does not consume a llama.cpp slot. The Qwen dispatch rule remains unchanged: dispatch while zero or one slot is busy; queue only when both 162,048-token physical slots are busy.

## What changed

- `autoeditcoordinator` profile main and delegation routes now pin to local Qwen; no fallback route remains.
- The coordinator cron record `ce71851cfdb7` now explicitly pins Qwen/llamacpp, `medium` reasoning, no fallbacks, and names the swapped Tester route in its runtime prompt.
- `autoedittester` main, delegation, standard auxiliary, and legacy auxiliary-model pins now target Terra/9Router; `auxiliary.free_only` is disabled.
- Tester `SOUL.md` now requires the Terra route and rejects a mismatched route with `BLOCKED_PROVIDER_POLICY`.
- Tester’s browser, computer-use, vision, skills, toolsets, CDP/browser configuration, and operational permissions were not changed.
- Current operating references updated: `docs/COORDINATOR_OPERATING_RULES.md`, `docs/status/AUTOEDIT_PROGRESS_REPORTING.md`, `AI_HANDOFF.md`, `jobs/BACKLOG.md`, and active routing/monitor skills.

Historical route notes remain audit evidence; they are superseded for live operations by this note and `docs/COORDINATOR_OPERATING_RULES.md`.

## Verification

The coordinator scheduler was paused while the paired configuration transaction was made, then read back before resumption.

Gateway-runtime fresh-completion proof, executed as UID 10000 with each named profile home:

```text
autoeditcoordinator → COORDINATOR_QWEN_ROUTE_OK
autoedittester      → TESTER_TERRA_ROUTE_OK
```

Both profiles' YAML parsed and the intended provider/model/context/output/delegation/auxiliary assertions passed. A structural comparison against pre-swap backups confirmed that non-routing config—toolsets, platform toolsets, browser/CDP configuration, skills, permissions, and provider catalogs—remained unchanged.

## Boundary

This is a routing change only. It does not authorize a product edit, worker dispatch, merge, deploy, production change, WhisperX action, or Dots action.
