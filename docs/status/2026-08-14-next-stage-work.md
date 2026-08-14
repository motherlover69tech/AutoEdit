# AUTOEDIT — Redesigned next-stage work: local implementation record

Date: 2026-08-14. This supersedes the parked round-7 pickup state in this file.
Peter explicitly asked the coordinator to redesign and implement W1–W6 directly,
without Kanban workers. No production deployment or live mutation was performed.

## Current gate status

| Gate | Current state |
|---|---|
| GATE-1 word timing | **PASS** from the completed live window. |
| GATE-2 speaker identity | **PASS** from the completed live window. |
| GATE-3 cut review | **OPEN FOR ROLLOUT/RE-REVIEW.** The POSTGAP-R1/R2 redesign passes locally, but the live candidate has not been regenerated or re-reviewed. |
| GATE-4 coexistence | **PASS** from the manual live window. The new read-only D2 observer passes locally; no new live collector run was performed. |

Production remains `WHISPER_BACKEND=mock` / `DIARIZE_BACKEND=mock`. Coordinating
crons remain paused. No deploy, regeneration, or production re-review occurred.

## Completed local redesigns

### W1 — GATE-3 resurrection: implemented and locally PASS

- `POSTGAP-R1`: onset snapping is general. A turn beginning at 1000 ms with an
  aligned word crossing `[900,1100]` projects from 900 ms.
- `POSTGAP-R2`: gap classification is derived from a sorted timeline and is
  independent of caller order.
- Ambiguous post-gap crossing-word cases fail safely to wide.
- Aligned words now travel through the real artifact → API projection path.
- Existing activity/cut/atomicity regressions remain green.

**Still required for live closure:** deploy the reviewed snapshot, regenerate the
candidate from the existing accepted artifact/confirmations, and perform Peter's
GATE-3 editorial re-review. Do not claim GATE-3 PASS before that flow completes.

### W2 — Package A: trust architecture replaced and locally PASS

The rejected self-authenticating proof design was removed. `RunEvidence` is now
portable observation data, not verdict authority. It contains no caller-authored
status, gate result, `construction_proof`, `evidence_digest`, or `artifact_valid`.

The validator now:

- opens a confined regular candidate file under a safe run ID;
- records and independently rechecks exact stored bytes, SHA-256, file identity,
  `mtime_ns`, artifact/run identity, and source offsets;
- recomputes boundary acceptance from current disk bytes and locked truth;
- rejects missing/malformed artifacts, wrong offsets, wrong digest, timestamp
  changes, forged all-PASS fields, path traversal, and symlinked run roots; and
- requires explicit distinct fixture selection and exactly one selected,
  validator-recomputed current run.

### W3 — Package B: complete-set transaction and UI redesign locally PASS

- Added `PUT /projects/{id}/speaker-confirmations/batch`.
- The request must contain every current anonymous voice exactly once.
- Full speaker/camera bijection, evidence, artifact version, and optimistic
  versions are checked before mutation.
- Existing rows require an exact optimistic version; fresh-run rows require no
  stale version.
- The complete current-version set is replaced in one DB transaction.
- One-row swaps now fail closed; the legacy endpoint cannot manufacture the
  other half of a swap.
- Uniqueness is scoped to `(project, source_artifact_version, identity)` so stale
  prior-run confirmations remain immutable audit history without blocking a
  fresh run.
- UI exposes one **Save all confirmed mappings** action, disabled until every
  row is complete, has at least two snippets, is acknowledged, and the whole
  selection is bijective.
- Suggestions are not silently preselected as authority.

Commit `080784f` remains superseded and must not be deployed.

### W4 — Package A Gate-1 direct compliance check: PASS

The obsolete worker checks targeted the abandoned trust-token architecture. The
replacement was checked directly against the redesigned boundary:

- explicit distinct fixture selection;
- validator-owned on-disk artifact authority; and
- exactly one validator-recomputed selected current run.

The direct Package A tests are part of the final green repository snapshot.

### W5 — D2/GATE-4: observer half rebuilt and locally PASS

D2 is no longer an executor capable of manufacturing its own authority.

Implemented:

- file-only `scripts/gate4_observer.py`;
- exact rendered-Compose and candidate metadata binding;
- append-only event chain authenticated with an external HMAC key not stored in
  evidence;
- authentication before semantic interpretation;
- required phase order/coverage and continuous GPU sampling;
- per-process GPU accounting, Dots output-mtime stability, real overlap/output
  observations, health/restart/Ollama checks, and cleanup/preservation checks;
- explicit rejection of caller verdict/all-PASS fields; and
- queue concurrency fixed at exactly one in code and Compose topology.

The legacy offline harness remains a mock/schema regression harness; its live
`--execute` path remains intentionally disabled.

**Boundary not implemented here:** a trusted-host collector that launches the
already-authorized live workload and emits the signed observations. That
collector remains a separate authorization/operations surface. The WebUI
container also lacks Docker Compose, so no real final Compose render was claimed
from this environment. The previous manual GATE-4 PASS remains authoritative.

### W6 — Live-window technical debt: implemented and locally PASS

- **W6.1 MySQL `/cuts`:** exact `(project_id, created_at, id)` index plus
  per-connection `SET SESSION sort_buffer_size=16 MiB`; no shared-server
  `SET GLOBAL` dependency. Compose and `.env.example` expose
  `DB_SORT_BUFFER_SIZE`.
- **W6.2 GPU accounting:** used-column values are cross-checked against
  per-process allocations; discrepancies above 20% are retained as auditable
  anomalies, while headroom uses the per-process sum when available.
- **W6.3 test isolation:** the repository suite pins `OLLAMA_BASE_URL=''` and
  `LLM_MODEL=''`; MySQL helpers do the same. Explicit LLM tests may still opt in.
- **W6.4 Dots completion:** API `completed` alone is insufficient; completion
  requires a post-submit, non-empty output generation stable across two polls.
- **W6.5 diarization continuation:** conservative embedding continuation requires
  minimum similarity, margin, and bounded gap; it refuses relabeling on overlap,
  ambiguity, long gaps, or missing embeddings; preserves provenance; and strips
  private embeddings from returned turns.

## Final local verification

Final snapshot commands were run with isolated temporary prerequisites on PATH:
Node 22.14.0 and static FFmpeg/FFprobe 7.0.2.

- Full pinned suite: **895 passed, 3 skipped**.
  - two skips: `AUTOEDIT_GOLDEN_MEDIA_ROOT` is not configured;
  - one skip: central MySQL integration credentials are not configured.
- Redesigned cross-package suite: **216 passed**.
- Focused security/atomicity suite after final adversarial fixes: **41 passed**.
- `tests/speaker_mapping_logic.test.mjs`: PASS.
- `tests/player_logic.test.mjs`: PASS.
- Node syntax checks for changed JavaScript: PASS.
- Ruff over changed Python: PASS.
- Python compileall: PASS.
- `git diff --check`: PASS.
- MySQL shell helper syntax: PASS.
- Real final Compose render: **NOT RUN — Docker Compose unavailable in this
  WebUI container**; static topology/observer regressions pass.

## Release boundary / next actions

1. Review the pushed exact commit and migration plan on the deployment host.
   The commit excludes pre-existing dashboard/browser artifacts and local Hermes
   helper/log files.
2. Deploy via `scripts/autoedit-deploy.sh` (backup → push → rebuild → verify),
   retaining production `mock|mock` unless a separately authorized rollout says
   otherwise.
3. Run a real rendered-Compose check on the deployment host.
4. Regenerate the GATE-3 candidate from existing accepted inputs and perform
   Peter's re-review.
5. Keep a future trusted-host GATE-4 collector separate from the read-only
   observer and require a fresh bounded live authorization before running it.

## Private evidence pointers

- `/mnt/user/automulticam/ai-gpu-1-acceptance/20260813-live-window/`
- `/mnt/user/automulticam/ai-gpu-1-acceptance/20260814-live-window-gate4/`

These remain consent-controlled and are not copied into Git.
