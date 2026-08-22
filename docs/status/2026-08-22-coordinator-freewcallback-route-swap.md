# AUTOEDIT role-route swap: Coordinator → 9Router `free_wCallback`

**Effective:** 2026-08-22 (Peter-directed)
**Scope:** the state-machine Coordinator profile `autoeditcoordinator` and its cron record `ce71851cfdb7` only. Programmer, Publisher (local Qwen), Designer (Sol), Tester (Terra) routes unchanged.

## Decision

Peter moved the AUTOEDIT Coordinator OFF local Qwen onto his private 9Router aggregator's `free_wCallback` model (the same combo model serving the coordinator WebUI session).

| Surface | Before | After |
|---|---|---|
| Profile `model.provider` / `model.default` | `custom:llamacpp` / `Qwen3.8-27b` | `custom:9Router` / `free_wCallback` |
| `model.context_length` / `max_tokens` | 162,000 / 32,768 | 200,000 / 32,768 |
| `agent.reasoning_effort` | `high` | `medium` (aligned with the cron pin and the 2026-08-20 Peter direction) |
| `delegation.model` / `.provider` | Qwen / `custom:llamacpp` | `free_wCallback` / `custom:9Router` |
| `auxiliary_models.*` (14 entries) | `Qwen3.8-27b` | `free_wCallback` (providers stay `main`) |
| 9Router provider catalog | — | `free_wCallback` added (verified present on the router's `/v1/models`) |
| Cron `ce71851cfdb7` fields | `model: Qwen3.8-27b`, `provider: custom:llamacpp` | `model: free_wCallback`, `provider: custom:9Router` |
| Cron prompt RUNTIME mandate | "Coordinator must be custom:llamacpp/Qwen3.8-27b … consumes one of the two local-Qwen slots" | "Coordinator must be custom:9Router/free_wCallback … does NOT consume a local-Qwen slot" |
| Qwen-slot attribution | Coordinator + Programmer + Publisher | Programmer + Publisher only (Coordinator and Tester are off llama.cpp) |

The `llamacpp` provider definition stays in the profile config (Programmer/Publisher still use it). No `auxiliary.free_only` guard exists in this profile; none was needed.

## Live proof (not config claims)

- `docker exec -u 10000:100 -e HOME=/opt/data/profiles/autoeditcoordinator hermes-gateway hermes -p autoeditcoordinator chat -q 'Reply with exactly the single token FREEWCB_OK'` → `FREEWCB_OK`, 4 s wall, exit 0.
- Gateway `agent.log`: `base_url=http://192.168.50.50:20128/v1 model=free_wCallback`, `API call #1 … latency=2.7s`, `finish_reason=stop`.
- Router `/v1/models` lists `free_wCallback` (`owned_by: combo`); 62 models total.

## Slot-limit consequence

The two 162,048-token llama.cpp slots are now shared by **Programmer + Publisher only**. The Coordinator's own ticks no longer occupy a Qwen slot, so Programmer/Publisher dispatch is less contended. The "two concurrent Qwen workers" rule is unchanged.

## Backups

- `~/.hermes/profiles/autoeditcoordinator/config.yaml.bak-before-9router-freewcallback-20260822T041249Z`
- `~/.hermes/profiles/autoeditcoordinator/cron/jobs.json.bak-before-9router-freewcallback-20260822T041249Z`
(gateway sees the same data at `/opt/data/profiles/autoeditcoordinator/…` — same bind mount, md5-verified identical before edit)

## Docs updated in the same pass

`docs/COORDINATOR_OPERATING_RULES.md` (header + slot-limit + model-policy bullets), `AI_HANDOFF.md` §7, `.hermes/AUTOEDIT_AGENT_TEAM.md` (banner note; historical table untouched), this file, the supersession banner on `2026-08-20-coordinator-qwen-tester-terra-route-swap.md`, and the skills `autoedit-agent-team`, `autoedit-ops`, `llm-monitor-ops` (route attributions).
