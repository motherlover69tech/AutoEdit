# AUTOEDIT Kanban Qwen3.8 Routing — 2026-08-15

## Decision

Peter ended the Claude/Codex subscription-backed worker routes and authorized the following local route for three AUTOEDIT Kanban profiles:

| Profile | Provider | Model | Hermes context | Reasoning |
| --- | --- | --- | ---: | --- |
| `autoeditprogrammer` | `custom:ollama` | `autoedit-qwen3.8:64k` | 65,536 | `xhigh` |
| `autoedittester` | `custom:ollama` | `autoedit-qwen3.8:64k` | 65,536 | `xhigh` |
| `autoeditpublisher` | `custom:ollama` | `autoedit-qwen3.8:64k` | 65,536 | `medium` |

`autoeditdesigner` is unchanged and remains on its separately authorized route.

`xhigh` is the canonical Hermes value. The initial `extra_high` spelling was invalid and
silently resolved to the default `medium`; the Programmer and Tester profiles and this
record were corrected after that was observed in a live Qwen3.8 worker log. A worker
already running before the correction keeps its startup reasoning configuration; the
next fresh Programmer/Tester run must report non-null `xhigh` reasoning configuration.

Public OpenRouter remains forbidden for every AUTOEDIT worker surface. The three changed profiles have no fallback providers. Their main, auxiliary, and dormant delegation routes are aligned to the same local Qwen alias so context compression or future delegation cannot silently return to Codex/9Router/cloud billing.

## Why a dedicated 64K alias

The installed base model `hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M` advertises a native 262,144-token maximum, but Ollama's OpenAI-compatible endpoint cannot raise `num_ctx` per request. Declaring a large context only in Hermes would therefore be misleading.

A dedicated Ollama alias was created server-side:

```text
autoedit-qwen3.8:64k
FROM hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M
PARAMETER num_ctx 65536
```

64K is the initial operational budget: large enough for repository context and long Kanban tool traces while leaving materially more V100 headroom than 100K/262K. Increase it only after a separate active-context and VRAM measurement.

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

The alias occupies approximately 19.5 GB VRAM when loaded. Programmer, Tester, and Publisher may share that single resident Ollama model, but AUTOEDIT GPU work remains sequential with WhisperX and Dots TTS. Do not count a route smoke as valid if Ollama CPU-offloads or overlaps an acceptance workload that requires isolated V100 measurement.

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

1. Read the live profile config and confirm `custom:ollama / autoedit-qwen3.8:64k / 65536`.
2. Confirm the local Ollama endpoint is reachable.
3. Run a fresh one-shot completion/tool smoke through the named profile.
4. Inspect `/api/ps` and require `context_length: 65536` with full GPU residency.
5. Only then create/dispatch implementation, independent-test, or publish work.

Historical documents and Kanban comments that name Codex, Luna, or the prior Tester 9Router route are audit history. This document and the live profile configs are the current routing authority.
