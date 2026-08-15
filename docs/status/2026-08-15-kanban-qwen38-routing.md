# AUTOEDIT Kanban Qwen3.8 Routing — 2026-08-15

## Decision

Peter ended the Claude/Codex subscription-backed worker routes and authorized the following local route for three AUTOEDIT Kanban profiles:

| Profile | Provider | Model | Hermes context | Reasoning |
| --- | --- | --- | ---: | --- |
| `autoeditprogrammer` | `custom:ollama` | `autoedit-qwen3.8:100k` | 100,000 | `low` |
| `autoedittester` | `custom:ollama` | `autoedit-qwen3.8:100k` | 100,000 | `low` |
| `autoeditpublisher` | `custom:ollama` | `autoedit-qwen3.8:64k` | 65,536 | `low` |

`autoeditdesigner` is unchanged and remains on its separately authorized route.

The initial `extra_high` spelling was invalid in Hermes and silently resolved to
`medium`; changing it to Hermes `xhigh` then produced Ollama HTTP 400 because Ollama
0.31.2 accepts only `high|medium|low|max|none` on its OpenAI-compatible endpoint. The
installed Qwen3.8 template maps an accepted `high` request internally to its own `xhigh`
instruction with an effectively unbounded reasoning budget. A fresh `high` Kanban run
then produced more than 11,000 reasoning tokens across long turns and wrote none of its
five required RED tests, so `high` is technically valid but operationally unsuitable for
bounded workers. The first cold required-tool smokes took 116 seconds at `medium` and 23 seconds at
`low`, while short warm-cache tool probes returned correct calls in 6–8 seconds at both
levels. Full Kanban work then showed that both `medium` and `high` could spend multiple
turns in read-only analysis. After the 100K context change, a fresh `medium` exact-token
Programmer smoke produced no output after four minutes at 96% GPU and was terminated.
The installed Qwen template is explicit: `medium` is accepted but receives no brevity
instruction; `low` injects “Keep your thinking brief and focused, moving directly to the
conclusion.” Programmer and Tester therefore use explicit `low` for actionability as
well as bounded execution; Publisher remains `low`. Do not set `high`/`xhigh`/`max`
without a separate reviewed comparison. Already-running workers retain startup settings.

Public OpenRouter remains forbidden for every AUTOEDIT worker surface. The three changed profiles have no fallback providers. Their main, auxiliary, and dormant delegation routes are aligned to the same local Qwen alias so context compression or future delegation cannot silently return to Codex/9Router/cloud billing.

## Dedicated 64K and 100K aliases

The installed base model `hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M` advertises a native 262,144-token maximum, but Ollama's OpenAI-compatible endpoint cannot raise `num_ctx` per request. Declaring a large context only in Hermes would therefore be misleading.

A dedicated Ollama alias was created server-side:

```text
autoedit-qwen3.8:64k
FROM hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M
PARAMETER num_ctx 65536
```

The original 64K alias is retained for rollback and for the bounded audiovisual product
inference path. A second Kanban-only alias was created after live measurement:

```text
autoedit-qwen3.8:100k
FROM hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M
PARAMETER num_ctx 100000
```

A plain 100K request completed in 9.67 seconds. `/api/ps` reported
`context_length: 100000`, `size_vram: 20879276768`, and `nvidia-smi` reported 21,168
MiB used / 11,327 MiB free with `ollama ps` showing `100% GPU`. This is approved for
Programmer and Tester while Dots processing is disabled. Publisher stays on 64K.

## Runtime evidence

A live Ollama tool-call smoke against `autoedit-qwen3.8:64k` returned the requested `record_verdict` function call with the required arguments. Immediately afterwards `/api/ps` reported:

```text
model: autoedit-qwen3.8:64k
context_length: 65536
size_vram: 19499088608 bytes
quantization: Q4_K_M
```

This proves both tool calling and the active backend context, rather than merely confirming YAML/model metadata.

## GPU scheduling rule

The 64K alias occupies approximately 19.5 GB VRAM; the 100K alias occupied 20.88 GB
(`nvidia-smi`: 21,168 MiB including runtime overhead), leaving 11,327 MiB free. AUTOEDIT
GPU work remains sequential with WhisperX and Dots TTS. Do not count a route smoke as
valid if Ollama CPU-offloads or overlaps an acceptance workload that requires isolated
V100 measurement. Reassess this route before re-enabling Dots processing.

## Config authority and rollback

Both `hermes-gateway` and `hermes-webui` mount the same host tree:

```text
/mnt/user/appdata/hermes -> /opt/data                         # gateway
/mnt/user/appdata/hermes -> /home/hermeswebui/.hermes        # WebUI
```

Therefore the authoritative files are:

```text
/mnt/user/appdata/hermes/profiles/autoeditprogrammer/config.yaml
/mnt/user/appdata/hermes/profiles/autoedittester/config.yaml
/mnt/user/appdata/hermes/profiles/autoeditpublisher/config.yaml
```

Pre-change configs were backed up under:

```text
/home/hermeswebui/.hermes/backups/autoedit-qwen38-route-20260815T003506Z/
```

No gateway or WebUI restart is required for newly spawned Kanban workers because each worker starts a fresh profile process. Existing already-running worker sessions retain their startup route and must not be treated as Qwen-routed evidence.

## Worker preflight

Before dispatching substantive work after this change:

1. Read the live profile config and confirm the role-specific alias/context from the table above.
2. Confirm the local Ollama endpoint is reachable.
3. Run a fresh one-shot completion/tool smoke through the named profile.
4. Inspect `/api/ps` and require the declared active context with full GPU residency.
5. Only then create/dispatch implementation, independent-test, or publish work.

Historical documents and Kanban comments that name Codex, Luna, or the prior Tester 9Router route are audit history. This document and the live profile configs are the current routing authority.
