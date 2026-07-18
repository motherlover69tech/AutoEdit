# AI-GPU-1 GPU/Dots acceptance runbook and evidence contract

**First step of every future execution: read-only discovery. No live activity is
permitted before that discovery is complete and Peter has explicitly authorized
the exact host, fixture, time window, live actions, and cleanup resources.**

**Status:** `DESIGN_APPROVED` operational design; current implementation is not
approved by this document and must be independently reviewed against every rule
below.

**Scope:** `OPS-AIGPU1-001..008`, `SEC-AIGPU1-002/003`, and
`TEST-AIGPU1-005/007/008`.

**Canonical machine contract:**
`docs/plans/ai-gpu-1-redacted-evidence.schema.json` version `1.0.0`.
The implementation schema under `scripts/` must be generated from, reference,
or be proven semantically identical to that contract. A smaller permissive
schema is noncompliant.

This card and runbook authorize no deployment, container start, model load,
Dots request, Ollama unload, GPU job, Unraid mutation, production-data change,
or live health check. Preparation, code acceptance, mock validation, a previous
approval, and successful read-only discovery are **not** authorization. Do not
execute the live workflow from this Designer task.

## 1. Facts, assumptions, unknowns, and Peter decisions

### 1.1 Verified facts

- AUTOEDIT production is on Peter's Unraid host, behind Nginx Proxy Manager,
  host-networked on port 8010, with central MySQL. `/mnt/user/appdata/autoedit`
  and `ingest.peteflix.uk` are production.
- The base Compose file pins `WHISPER_BACKEND=mock` and
  `DIARIZE_BACKEND=mock`. They must remain mock during and after this gate.
- The opt-in worker design uses loopback port 8011, read-only `/data`, a
  persistent model cache, a readiness health check, and one queued GPU job.
- The target configuration is V100, `large-v3`, FP16, English, alignment,
  batch 4, constrained two-speaker diarization, and one worker job at a time.
- Program audio remains the master clock; proxies remain silent; source media is
  never played in the browser. Automatic energy-envelope cross-correlation is
  the sync mechanism. No manual sync nudge is an acceptance remedy.
- VAAPI `h264_vaapi` remains the active proxy path. This work does not replace it
  with QSV while MFX session `-9` remains unresolved.
- The existing `scripts/ai_gpu_acceptance.py`, its schema, runbook, and tests
  were inspected. They do not yet constitute this complete operational design.

### 1.2 Assumptions that discovery must verify

- The selected GPU is the intended V100 and Dots shares it.
- Dots has a health/readiness seam and can run the approved quality workload.
- Ollama can be unloaded in the authorized window without harming another
  approved workload.
- The consent-controlled fixture and private input-hash binding already passed
  the upstream fixture gate.
- Packages A-C have passed compliance, and the selected cut/artifacts have a
  known last-known-good state.

A false assumption produces `unavailable` or `fail`; it never causes an
automatic service start, alternate fixture, lowered threshold, or production
default change.

### 1.3 Unknowns discovered read-only and kept redacted

- Current CPU, RAM, GPU inventory and GPU process owners.
- Docker/Compose topology, container states/restarts, network bindings, ports,
  reverse-proxy relationship, mounts, appdata/cache placement, ownership and
  permissions, health checks, persistence, backup, and rollback state.
- Current Dots image/configuration/state and Ollama loaded-model state.
- Effective app backend values and the merged base + GPU Compose structure.
- Exact approved cleanup resources and whether Dots is intended to remain
  resident after the run.

### 1.4 Decisions only Peter can make

Peter must provide one current, bounded authorization decision that identifies
opaque references for:

1. the target host and exact consent-cleared fixture;
2. the UTC start/end window;
3. whether the acceptance worker may be explicitly started;
4. whether Dots may be loaded/exercised;
5. whether Ollama may be unloaded;
6. whether Whisper jobs may be submitted;
7. every resource the cleanup path may stop/remove/unload; and
8. any service that is intentionally allowed to remain resident.

An environment boolean by itself is not sufficient authorization. The harness
must validate a scoped authorization record and persist only its opaque decision
reference. Any missing, expired, mismatched, or out-of-scope decision is
`unauthorized`; no live operation is attempted.

## 2. State and exit semantics

Every check, phase, output, requirement, and overall result uses exactly one:

| State | Meaning | Live-run consequence |
|---|---|---|
| `pass` | The check ran against the intended evidence and met its rule. | Continue if dependencies pass. |
| `fail` | The check ran and breached its rule. | Stop submissions, authorized cleanup/rollback, nonzero. |
| `skipped` | The check was deliberately not executed. | A mandatory check cannot pass; nonzero. |
| `unavailable` | An allowed observation/dependency/tool/data source was absent or unusable. | Do not improvise or start it; nonzero. |
| `unauthorized` | Permission was absent, expired, mismatched, or out of scope. | Do not attempt the action; nonzero. |

For a live run, every scoped requirement and mandatory check must be `pass`.
Any other state makes `overall.acceptance_pass=false`. Discovery-only and mock
commands may exit zero when their own bounded purpose succeeds, but must record
`acceptance_eligible=false` and `acceptance_pass=false`; they are never live
acceptance evidence.

Required exit classes:

| Code | Class | Use |
|---:|---|---|
| 0 | `success` | Successful discovery/mock purpose, or fully passing authorized live run. |
| 2 | `validation_failure` | Evidence, phase, output, health, or threshold failure. |
| 3 | `unavailable` | Required dependency/observation unavailable. |
| 4 | `unauthorized` | Live mode requested without matching current authorization. |
| 5 | `adapter_error` | Timeout, malformed tool response, subprocess/HTTP failure. |
| 6 | `redaction_failure` | Potential secret/private payload cannot be safely retained/emitted. |
| 7 | `cleanup_or_rollback_failure` | Authorized cleanup/recovery did not complete or mock/health was not restored. |

The process must emit a sanitized diagnostic and exit nonzero for every live
mandatory failure. Catching an exception and returning zero is noncompliant.

## 3. Required harness modes and deny-by-default interface

The implementation must have separate, explicit modes:

- `plan`: local parsing/schema/config validation only; no external command.
- `discover`: allowlisted read-only inspection only.
- `validate`: validate an existing redacted evidence instance; no live action.
- `mock`: deterministic injected adapters/fake clocks only; network and external
  commands denied.
- `execute`: authorized live workflow only.

No mode is implied. No arguments print usage and exit nonzero. `execute` must
refuse unless it receives the same-host discovery bundle, the scoped current
authorization record, the immutable candidate identifiers, and the private
fixture binding. `execute` must present the exact planned actions before the
first live action.

There is no `ensure running`, auto-heal, fallback, retry-with-different-settings,
or implicit startup behavior. A stopped/absent worker or Dots service remains
stopped/absent during discovery. Starting the opt-in worker is a distinct,
logged, explicitly authorized operation. Health/readiness probes never start a
service. Rendering Compose never runs `up`, `run`, `start`, `restart`, `create`,
`pull`, or `build`.

## 4. Phase 0 — mandatory read-only discovery (`OPS-AIGPU1-001`)

Discovery completes before authorization-gated live activity. The adapter uses
an exact allowlist of non-mutating operations and records a sanitized command
result for each. It must inspect:

1. GPU product, compute capability, total/used/free MiB, and current per-process
   GPU ownership; CPU count; total/available RAM.
2. Docker and Compose topology, service state, health, restart counts, images,
   network mode, bindings, ports, and health-check definitions.
3. NPM/public relationship without changing proxy configuration.
4. Media, appdata, evidence, and model-cache mount purposes; read/write mode;
   persistence; owner/group/mode suitability. Exact private paths are not put in
   redacted evidence.
5. Current app health and effective values of only `WHISPER_BACKEND` and
   `DIARIZE_BACKEND`; never dump the environment.
6. Dots state/config/health/readiness and Ollama loaded-model count.
7. Persistent-data, backup, last-known-good, and rollback readiness without
   reading or mutating production payloads.

If any discovery tool is missing, times out, returns malformed data, requires a
mutating fallback, or cannot be redacted, mark the observation `unavailable` or
`fail` and stop. Do not start a container to make discovery pass.

## 5. Phase 0b — redacted merged Compose validation (`OPS-AIGPU1-002`, `SEC-AIGPU1-003`)

Render base + GPU Compose in memory using the already approved secret source.
Never print or persist the raw interpolated render. Parse it, retain an
allowlisted structural projection, replace secret-bearing values, scan the
projection, and hash the canonical redacted representation.

All checks must pass:

- app uses host networking;
- worker publishes only to loopback and is not reachable through LAN/NPM;
- worker media mount is read-only and path-confined;
- model cache is persistent;
- readiness health check exists;
- queue concurrency is exactly one;
- app's effective Whisper and diarization backends are both `mock`;
- no worker exposure or production default changes are introduced; and
- the render operation started no container and performed no build/pull/create.

Missing deployment secrets make this check `unavailable`; they are not requested
in chat, copied into a command, or replaced with placeholders that claim a pass.

## 6. Clock and sampler contract (`OPS-AIGPU1-003`)

Start one sampler before the baseline marker and keep it running continuously
through cleanup verification. Use monotonic nanoseconds as authority for order,
duration, phase containment, overlap, and gaps. Record UTC RFC3339 wall time for
audit reconciliation.

Each scheduled tick and sample records:

- strict sequence number;
- scheduled and observed monotonic nanoseconds;
- UTC wall timestamp;
- phase and activity tags;
- device total, used, and free MiB;
- every GPU process's positive PID, allowlisted process basename, role, and
  per-process used MiB; and
- app/worker/Dots/Ollama health, readiness where applicable, and restart count.

The configured nominal interval is 1-250 ms: it is a no-more-than-250-ms
nominal interval. Scheduled tick spacing must be no more than 250 ms. Observed
monotonic times and sequences strictly increase; no
gap may exceed 500 ms. Samples reconcile `total=used+free`, and total memory is
constant. Missing or malformed process arrays fail; unknown GPU process
ownership fails.

Wall/monotonic elapsed time across run anchors and phase markers may differ by
at most 500 ms. A backward wall clock or larger difference invalidates the run.
Wall time never determines overlap or duration.

## 7. Required phases and markers (`OPS-AIGPU1-003/004`)

Every phase appears exactly once, in this order, with start/end events on both
clocks. Markers cannot overlap, invert, duplicate, or lie outside sample cover.

| Seq | Phase | Entry and required activity | Exit/minimum | Failure outcome |
|---:|---|---|---|---|
| 0 | `baseline` | Ollama unloaded; no acceptance worker/model load; capture idle process/container state. | At least 10,000 ms. Compute preflight idle used-VRAM median. | Stop before live actions; measurement invalid. |
| 1 | `dots_resident` | Explicitly authorized Dots load/readiness; Dots resident and idle; Ollama still unloaded. | At least 10,000 ms after readiness is stable. | Fail Dots state/readiness; authorized cleanup. |
| 2 | `whisper_cold` | Dots stays resident. Explicit worker start if authorized, cold model readiness, then one full ASR + alignment + constrained diarization job. Tag model-load/readiness/ASR/alignment/diarization samples. | Cold job reaches terminal state and output validation completes. | Fail cold/output/health; no active phases. |
| 3 | `co_resident_idle` | Dots and worker/model are ready and idle; no unloading or configuration change. | Positive stable interval; no invented fixed duration. | Fail readiness/residency. |
| 4 | `active_overlap_1` | One Dots inference and one full Whisper analysis run under fixed settings. | Actual inference overlap at least 5,000 ms; both outputs validate. | Fail; do not increase model/batch. |
| 5 | `active_overlap_2` | Repeat once without configuration/image/model change. | Actual inference overlap at least 5,000 ms; both outputs validate. | Fail repeatability/coexistence. |
| 6 | `post_workload` | Begins only after both final workloads finish; continue sampling and health/Ollama checks. | At least 30,000 ms before cleanup. | Measurement invalid. |
| 7 | `cleanup_verify` | Only preauthorized temporary/opt-in cleanup; app/mock/health and idle-memory verification. | All cleanup checks terminal. | Rollback/cleanup failure; exit 7. |

If overlap is too short, the run fails. A later authorized run may use a longer
consent-cleared excerpt or schedule starts differently; it must not raise batch,
change model precision, unload intended Dots residency, or reinterpret phase
duration as inference overlap.

## 8. Fixed workloads and successful-output validation

### 8.1 Dots

Use the current Peter-approved quality configuration with a non-sensitive
600-character input, 12 steps, and guidance 1.3. Do not retain the text. Record
the quality-config opaque reference and character count. +3 dB and MP3
post-processing are reported separately and excluded from GPU residency/load.

Both active Dots runs must produce non-empty output, positive duration, and pass
a playable media probe. An HTTP success, job ID, or file existence alone is not
successful output. Raw audio, exact output path, prompt text, and runtime IDs do
not enter the redacted record.

### 8.2 WhisperX

Use the reviewed immutable image and exact private input-hash binding with
`large-v3`, FP16, English, alignment on, batch 4, diarization on, speaker bounds
2..2, and queue concurrency one. The cold run and both overlap runs must each:

- reach `done` without queue overflow;
- prove the private input hash is unchanged without exposing it;
- contain non-empty aligned words with ordered, bounded integer-ms times; and
- contain valid two-speaker turns.

Raw worker payloads, word text, transcript excerpts, media hashes, and exact
paths stay private and are absent from the redacted evidence instance.

### 8.3 Overlap calculation

For each active phase:

`overlap_ms = min(dots_end, whisper_end) - max(dots_start, whisper_start)`

Use actual inference start/end events on the monotonic clock. Both overlaps must
be at least 5,000 ms. Readiness, queue wait, encoding, and post-processing do not
count as inference overlap.

## 9. Health, restart, readiness, and incident rules (`OPS-AIGPU1-006`)

Capture checks at every phase boundary and in sample-aligned observations. A
live pass requires:

- app and Dots health never lost;
- worker readiness present when applicable and never lost after attained;
- zero unexpected restart delta for app, worker, Dots, and Ollama;
- Ollama loaded-model count zero before, throughout, and after measurement;
- no CUDA OOM, CPU offload, model eviction/reload under pressure, queue overflow,
  malformed backend response, or unknown process; and
- all five required outputs validate: three Whisper and two Dots.

Unknown/missing health is `unavailable`, not healthy. Log-string absence alone
does not prove no OOM/offload/eviction; use service/job status plus sanitized
incident parsing. Any incident fails the run and invokes bounded rollback.

## 10. VRAM and process-accounting verdict (`OPS-AIGPU1-005`)

Compute the global peak over all samples, thereby covering Dots residency, cold
model load, ASR, alignment, diarization, both active overlaps, and any unexpected
post/cleanup peak.

`required_headroom_mib = max(2048, ceil(total_mib * 0.10))`

The report records device total, peak used, minimum free, threshold, peak phase,
peak sample sequence/timestamp, and contributing PIDs/names/per-process MiB.
`minimum_free_mib` must be at least the threshold. Every peak process must be
attributed to the preflight allowlist; unknown consumers invalidate the run.
Do not subtract process sums from total VRAM to manufacture headroom.

## 11. Cleanup and rollback (`OPS-AIGPU1-007/008`)

Cleanup may change only the resource references listed in Peter's authorization.
It must never stop/recreate/prune the production app, central MySQL, NPM, or an
unapproved Dots/Ollama service; modify production data; rewrite AUTOEDIT
artifacts/cuts; or edit Unraid Docker templates.

Calculate:

- `baseline_idle_median_used_mib` from the complete baseline;
- `post_cleanup_idle_median_used_mib` from stable cleanup verification; and
- `raw_drift_mib = post - baseline`.

Pass when raw drift is no more than 512 MiB. An intentionally resident-service
exception is allowed only if it was named before live activity, remains healthy,
and its explained MiB is independently measured; adjusted drift must still be
no more than 512 MiB. An after-the-fact explanation is a failure.

After cleanup, verify app health and read only the two effective backend keys;
both must equal `mock`. Verify the prior selected artifact and cut remain
unchanged. A failed run stops further submissions, stops/removes only authorized
temporary resources, leaves or restores mock selection, preserves evidence, and
reports every failed requirement. A retry must be a new run and never changes
production defaults.

If cleanup, app recovery, mock recheck, or preservation cannot be proven, exit
with `cleanup_or_rollback_failure`; never report the earlier workload as accepted.

## 12. Redaction and evidence retention (`SEC-AIGPU1-002`)

The schema describes a redacted **private audit record**, not a public artifact.
It retains required ephemeral PIDs/process basenames and aggregate infrastructure
facts but excludes content and secrets. The evidence instance remains under the
ignored consent-controlled root with restrictive permissions. Only a further
reduced aggregate summary may enter Git or durable Kanban text.

Never persist or emit:

- credentials, HF/Dots/host tokens, API keys, passwords, cookies,
  authorization headers, secret values, private keys, or raw env dumps;
- raw media/audio, Dots input text, transcript/word text, names, screenshots or
  recordings containing private media;
- exact private paths, private media/source hashes, raw HTTP bodies, raw worker
  payloads, or container runtime IDs; or
- unredacted stdout/stderr or a raw interpolated Compose render.

Deep redaction runs before every file write, stdout/stderr emission, exception,
command record, and summary. Redact by key and value patterns; credentialed URLs
must be replaced, not partially masked. Use opaque run/project/fixture/output and
service references. Record redaction policy version, transformations, scanner
version, files scanned, zero findings, and `raw_sensitive_payloads_present=false`.

Commands are stored as redacted argv tokens with operation ID, phase,
read-only/authorization flags, times, exit/timeout, result digest, and redaction
status. Raw command output is not retained. A redaction uncertainty is exit 6,
not a best-effort warning.

## 13. Evidence bundle and schema validation (`TEST-AIGPU1-007`)

Private ignored run layout:

```text
<consent-controlled-root>/ai-gpu-1-acceptance/<opaque-run-id>/
  discovery.private.json
  compose-render.redacted.yaml
  gpu-samples.private.ndjson
  workload-events.private.ndjson
  service-observations.private.ndjson
  redacted-evidence.json
  redaction-scan.json
  sanitized-diagnostics/
```

Only `redacted-evidence.json` conforms to the canonical tracked schema. It binds:

- source commit, worker image digest, model/runtime versions, canonical redacted
  Compose-render digest;
- opaque project, fixture, and run IDs; FPS rational; automatic sync offsets;
- private input-hash match boolean without the hash;
- phases, samples, processes, service checks, workloads, outputs, overlaps, VRAM,
  cleanup, rollback, commands/results, tests, requirement results, and Peter's
  opaque authorization decision; and
- redaction metadata and a digest of the redacted summary.

Schema validity is necessary but not sufficient. The harness must execute every
`x-autoedit-semantic-rules` rule and populate every requirement result with
validation-rule IDs and JSON Pointer evidence references. `additionalProperties`
remain closed so arbitrary raw payloads cannot hide in the record.

## 14. Offline test contract (`TEST-AIGPU1-005/008`)

Tests use injected adapters, fake monotonic/wall clocks, fake subprocesses, and
local fixtures only. Network sockets and unmocked external commands are denied.
No test inspects or contacts live Docker, GPU, Dots, Ollama, Unraid, NPM, MySQL,
production, or external networks.

A positive fixture must pass schema and semantic validation, produce a redacted
record, exit zero for its mock purpose, and still state
`acceptance_eligible=false`/`acceptance_pass=false`.

Negative tests must assert state, sanitized failure code/diagnostic, and nonzero
exit for at least:

1. nominal interval 251 ms; gap >500 ms; duplicate/non-monotonic sample;
2. missing, reordered, duplicated, inverted, overlapping, or out-of-coverage
   phase; baseline/resident <10 s; post <30 s;
3. absent/malformed PID, name, per-process MiB, service observation, or unknown
   GPU process;
4. irreconcilable/backward clocks;
5. app, worker readiness, Dots health/readiness, restart, Ollama-loaded, OOM,
   offload, eviction, queue-overflow, and model-reload failures;
6. malformed/unsuccessful Dots or Whisper output, wrong input hash, unavailable
   worker, and overlap <5 s in either active phase;
7. insufficient VRAM headroom and inconsistent device total/free arithmetic;
8. cleanup drift >512 MiB, unapproved cleanup action, failed app health, failed
   mock-backend recheck, and artifact/cut preservation failure;
9. timeout, nonzero command, malformed adapter/backend data, and any caught
   mandatory failure that would otherwise exit zero;
10. missing/expired/wrong-scope Peter authorization and attempted mutating
    discovery/implicit startup;
11. secret-like keys/values in input, output, command argv, exceptions, URLs,
    Compose render, and nested structures; and
12. upstream fail-closed references for malformed worker output, wrong hash,
    persistence failure, stale mapping, unresolved identity, and missing wide
    camera, plus Package-D Dots and VRAM failures.

The suite must fail if any fake attempts an unapproved external operation.

## 15. Requirement-to-evidence and pass/fail matrix

| Requirement | Required fields/evidence | Pass rule | Failure outcome |
|---|---|---|---|
| `OPS-AIGPU1-001` | `discovery.*`, `authorization.*`, discovery command records | All nine discovery categories pass read-only before live action; explicit current Peter scope then passes. | `unavailable`/`unauthorized`; no live action; nonzero if execute requested. |
| `OPS-AIGPU1-002` | `compose.*`, redacted render digest | Host app, loopback worker, RO media, persistent cache, readiness, concurrency 1, mocks; render-only/no start. | Stop before workloads; nonzero. |
| `OPS-AIGPU1-003` | `measurement.configuration/clocks/phases/samples/interval_statistics` | Nominal <=250 ms, max gap <=500 ms, required 10 s/30 s coverage, exact phase order, clock reconciliation, PID/name/MiB plus service state. | Measurement invalid; rollback; nonzero. |
| `OPS-AIGPU1-004` | phases, workload intervals/outputs/overlaps, Ollama checks | Dots resident + cold Whisper; two >=5 s active overlaps; fixed config; Ollama zero models. | Coexistence fail; do not tune settings; rollback. |
| `OPS-AIGPU1-005` | `measurement.vram_summary`, peak sample/process rows | Global maximum and contributors reported; free >= `max(2048, ceil(total*0.10))`; no unknown process. | Capacity/ownership fail; nonzero. |
| `OPS-AIGPU1-006` | `services.*`, `workloads.*` | No listed incident/restart/health loss; 3 Whisper + 2 Dots outputs validate. | Workload fail; preserve prior state; rollback. |
| `OPS-AIGPU1-007` | `cleanup_and_rollback.*`, cleanup samples | Only authorized resources touched; adjusted drift <=512 MiB; app healthy; both backends mock. | Cleanup/rollback exit 7. |
| `OPS-AIGPU1-008` | rollback record, requirement results, run exit | Every failure stops submissions, preserves artifacts/cuts, leaves/restores mock, reports failed gates, exits nonzero. | Acceptance cannot pass even if prior workload succeeded. |
| `SEC-AIGPU1-002` | `redaction.*`, commands, sanitized diagnostics | Approved secret source only; zero prohibited data/findings; no raw output retained. | Redaction exit 6; do not retain unsafe evidence. |
| `SEC-AIGPU1-003` | Compose/network/mount checks | Worker loopback-only, absent from LAN/NPM, RO confined media; never exposed for testing. | Security fail before workloads; nonzero. |
| `TEST-AIGPU1-005` | samples/phases/process/services/outputs/overlaps/VRAM | All continuity, phase, coexistence, output, health, restart, Ollama, and headroom validators pass. | Test/live gate fail. |
| `TEST-AIGPU1-007` | candidate/project/commands/requirement refs/redaction | Exact candidate/config/opaque IDs/FPS/offsets/commands/results/Peter decision, no private content. | Evidence incomplete or unsafe; no pass. |
| `TEST-AIGPU1-008` | `tests.results`, rollback/failure records | Every named failure is deterministic, fail-closed, sanitized, and nonzero without live access. | Implementation changes required. |

## 16. Observability, UI/accessibility, and responsive behavior

This package adds no product UI and does not change player/media behavior.
Operational output must work in terminals and automation: JSON is authoritative;
human text is concise, does not rely on color, names the state/failure code and
next safe action, and remains usable with wrapping at narrow widths. No spinner,
animation, or interactive prompt may conceal authorization or failure. A later
dashboard view is a non-goal and may not weaken the machine contract.

## 17. Implementation package, ownership, and dependencies

One Programmer worktree owns only:

- `scripts/ai_gpu_acceptance.py` or a narrowly split `scripts/ai_gpu_acceptance/`
  package;
- `scripts/ai_gpu_acceptance_evidence.schema.json`, derived from or proving
  semantic identity with the canonical plan schema;
- `tests/test_ai_gpu_harness.py` plus bounded fixtures; and
- the minimum runbook linkage needed to name the implemented CLI.

It does not own Compose defaults, deployment scripts, app backends, Dots service
configuration, production data, or Unraid templates. Dependencies are: upstream
Packages A-C compliance, then exhaustive offline Tester tests, then independent
Designer compliance, then a separately authorized Tester live task. A Programmer
cannot approve their own harness.

## 18. Deployment, rollback, risks, and non-goals

### Deployment

No deployment is authorized. Future live execution is an acceptance activity,
not backend promotion. Production remains mock-backed before, during, and after.
A later per-project rollout needs a separate explicit design/deployment task.

### Risks

- Sub-250-ms collection can lose samples under load; scheduled-tick and gap
  evidence prevents a false pass.
- Cold model load may be the peak; it is explicitly tagged and included.
- GPU process attribution may be incomplete; unknown consumers fail rather than
  being ignored.
- Wall time can step under NTP; monotonic time is authoritative and reconciliation
  makes the run invalid rather than silently reordering it.
- Compose and service commands can leak secrets/private paths; in-memory parsing,
  deep redaction, closed schema, and fail-on-uncertainty reduce this risk.
- Cleanup can harm unrelated services; exact authorization allowlists and no
  generic prune/ensure-running behavior are mandatory.

### Non-goals

- No live run, deployment, production mutation, container startup, Dots/GPU use,
  Ollama unload, or Unraid change in this Designer task.
- No production backend promotion, global Whisper authority, or replacement of
  the broader three-interview benchmark.
- No manual audio sync remedy, source playback, proxy audio, QSV change, central
  MySQL/NPM change, Dots quality change, batch increase, or model precision change.
- No raw private evidence in Git/Kanban and no claim that mock validation is
  authorization or live acceptance.

## Verdict

`DESIGN_APPROVED`

The runbook and canonical schema are sufficient for a bounded Programmer to
implement and for an independent reviewer to audit every scoped requirement.
Live execution remains blocked until the implementation passes offline tests and
independent compliance and Peter supplies a current, exact authorization.
