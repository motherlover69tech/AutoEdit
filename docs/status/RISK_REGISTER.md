# AUTOEDIT Risk Register

> **Purpose:** Track every requirement that is currently *unmet / failed / waived* across the
> AUTOEDIT build, with owner-decision, impact, and remediation status. This is the audit trail
> for requirements that did not pass their acceptance gate.
>
> **Owner instruction (2026-07-18, Discord `#general`):** *"B) waive this but log all failed
> requirements on a risk register."* Requirement **B** is recorded below as **WAIVED** per owner
> instruction. The exact text of clause B was referenced in-thread and not yet pasted into this
> repo; the waiver stands and the clause identifier is retained so it can be reconciled later.
>
> **How to read:** Each row is a *failed or waived requirement*. "Met" requirements are NOT
> listed here — see `jobs/BACKLOG.md` for the green status table. This register is the inverse:
> the gap list.

## Legend

| Field | Values |
|-------|--------|
| Status | `OPEN` (failed, not waived), `WAIVED` (failed but owner-approved to skip), `PARTIAL` (met with caveats) |
| Severity | `HIGH` / `MED` / `LOW` — impact if left unaddressed |
| Source | where the requirement originates (spec stage, job, handoff) |
| Evidence | concrete proof of the gap (test count, doc reference, manual-gate result) |

## Register

| ID | Requirement | Status | Severity | Source | Evidence / Why it failed | Remediation | Owner |
|----|-------------|--------|----------|--------|--------------------------|-------------|-------|
| **B** | *(clause text to be reconciled from thread)* — owner-directed waiver | **WAIVED** | n/a | Discord `#general` 2026-07-18 | Owner explicitly waived; clause text not yet in repo | Confirm exact B clause and record here; otherwise treat as permanently waived | Peter |
| R-7.4 | Stage 7.4 independent Tester verdict against exact deployed commit `c096e4e` (multi-author, XSS-safe, marker seek, delete-from-list-and-lane) | OPEN | HIGH | Job 7.4 / BACKLOG §remaining gates | Candidate passes local Chromium harness; exact-commit independent Tester rerun still pending. Prior `TEST_FAIL` targeted old `master` @ `87b9d47` and is NOT valid evidence | Run independent Tester card against `/opt/data/workspace/AUTOEDIT/.worktrees/autoedit-integrated` @ `c096e4e` with normal fixtures, zero unexpected console/network errors | Peter / Tester |
| R-8.3 | Stage 8.3 OTIO-generated FCPXML/EDL fallback (source-spec optional path) | OPEN | MED | Job 8.3 / spec 8.3 | Direct CMX3600 EDL is Resolve-verified; the spec's OTIO fallback is unimplemented and unverified | Either implement OTIO fallback or formally amend spec to drop the optional clause (would then close R-8.3 as spec-change, not waiver) | Peter |
| R-9.2 | Stage 9.2 LLM-backed YouTube title generation (grouped-strategy / regeneration / defensive JSON) | OPEN | MED | Job 9.2 / spec 9.2 | Only deterministic 4-category template baseline exists; specified LLM strategies/regeneration/defensive path not wired | Implement LLM title path or document template-only as accepted scope | Peter |
| R-AI-TRANSCRIBE | Real Whisper transcription production-authoritative (`WHISPER_BACKEND=whisperx` on V100) | OPEN | HIGH | AI_HANDOFF "real-AI phase" / Job 5.1 | Opt-in WhisperX adapter + queued V100 run passed (20.93s, 241 segments); production still pinned `WHISPER_BACKEND=mock` until all AI gates pass | Complete frame-level timing + coexistence gates, then flip backend with rollback tag | Peter |
| R-AI-DIARIZE | Real speaker diarization production-authoritative (`DIARIZE_BACKEND` real) + confirmed speaker identity | OPEN | HIGH | Job AI-GPU-1-PHASE4 / AI_HANDOFF | Constrained diarization passed (8,024 MiB peak VRAM, 322 turns); confirmed speaker identity + speaker-aware cut acceptance still open; production pinned `DIARIZE_BACKEND=mock` | Finish speaker-identity confirmation + speaker-turn cut acceptance gates, then flip backend | Peter |
| R-AI-TOPIC | LLM topic segmentation (no silent mock fallback in prod) | OPEN | MED | AI_HANDOFF Tier roadmap / Job 5.2 | `mock_segment_topics()` is the active path; LLM segmentation not wired | Wire `OLLAMA_BASE_URL`/`LLM_MODEL` topic path with fail-closed behavior | Peter |
| R-AI-CONCISE | LLM conciseness grading (deterministic baseline only today) | OPEN | LOW | AI_HANDOFF Tier roadmap / Job 5.3 | Deterministic filler/WPM grading in place; LLM grading not wired | Optional upgrade once LLM pipeline is stable | Peter |
| R-GOLDEN | Golden/consent-cleared media fixtures in repo for end-to-end tests | OPEN | MED | BACKLOG "Remaining gates" | All tests use mocked ffprobe + numpy-generated audio; no real test media committed | Add consent-cleared fixture set under `tests/fixtures/` with hashes | Peter |
| R-QSV | QSV hardware proxy encoding (`h264_qsv`) | OPEN | LOW | AI_HANDOFF pitfalls / Job HWENC | `h264_qsv` fails `Error creating a MFX session: -9`; VAAPI (`h264_vaapi`) is the active production path | Investigate Intel MFX separately if QSV still desired; non-blocking (VAAPI works) | Peter |
| R-7.4-OLDMASTER | Guard: never treat `master` @ `87b9d47` test results as evidence for deployed `c096e4e` | PARTIAL | MED | BACKLOG / AI_HANDOFF branch topology | Guard documented, but the erroneous `TEST_FAIL` already occurred once; process now requires exact-commit naming on every regression card | Enforce exact-commit/worktree naming in every Tester/Publisher card template | Peter |

## Summary counts

- **WAIVED:** 1 (requirement B — owner instruction)
- **OPEN:** 10
  - HIGH: 3 (R-7.4, R-AI-TRANSCRIBE, R-AI-DIARIZE)
  - MED: 5 (R-8.3, R-9.2, R-AI-TOPIC, R-GOLDEN, R-7.4-OLDMASTER)
  - LOW: 2 (R-AI-CONCISE, R-QSV)
- **PARTIAL:** 1 (R-7.4-OLDMASTER)

## Notes

- This register is the **gap / failure** list only. Met requirements live in `jobs/BACKLOG.md`.
- "Waive" means the owner accepts the gap; it does **not** remove the requirement from
  audit — it is recorded here with status `WAIVED` and the rationale.
- Re-open or close any row by editing the table and updating the counts above.
- Requirement **B** row must be reconciled with the exact thread clause when available; the
  waiver itself is already in force per owner instruction dated 2026-07-18.
