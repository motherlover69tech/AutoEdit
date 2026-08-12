# Phase 6 — Terminal Truncation Release Handoff (2026-08-12)

**Status: DEPLOYED + LIVE-VERIFIED.** No open board tasks. Branch `phase6-confirmation-projection-spec` @ `1d5886a3e0d28ba97a769b9704d2e9b4a367416d` (clean).

## What shipped (4 layers)

1. **Gate 1 acceptance** — 3 words / 6 boundaries, bound to the current artifact (`audio/ai/v1/word-timing-review.json`, `peter_acceptance=true`, 0 ms manual adjustment). Current-version validation passes; stale-version rejected.
2. **Confirmation projection fix** (`0601b43`) — cut path now projects raw diarization turns through current MySQL `speaker_confirmations` even when the artifact has zero pre-resolved `speaker_turns`. 252/252 raw turns now confirmed (was 0).
3. **Terminal truncation, strict policy** (`0de62046`) — bounded fail-closed (`422 terminal source coverage is ineligible`) when the uncovered region is not a single terminal suffix.
4. **Amendment per Peter's explicit decision** (`f151804` + `1d5886a`) — boundary = greatest canonical frame where an authorized presenter/wide camera exists; covered segments after the boundary are dropped. Round-2 compliance closure: committed failing regression `f1a4abd` → green at `1d5886a` (two-round cap honored).

## Live state (independently verified 2026-08-12 ~05:20 UTC)

- Container `autoedit-app-1`: running, restarts 0, image `sha256:8133558f86f2e72adf17afebdc1476ee355cc5b9b5054a4103fd5b300a759477`; deployed `api.py` sha256 `4c076fa7699f1125197c1f226d7fae6c336ab35f6f7c88a2bcfc14a76571f9b7` == worktree file at `1d5886a`.
- Live WhisperX candidate: **HTTP 200**, cut `01KZT3372CDNV7SBKK18STZRZ2`, `selected=false`, 348 clips, last clip end **666,167 ms**.
- `truncation` object (exact, identical in API response, DB `cuts.cdl_json`, immutable `edit/cdl_whisperx_phase6-20260811T234633Z.json`, and `activity-whisperx.json`):
  - `applied=true`, `reason_code=terminal_authorized_camera_coverage_exhausted`, `original_artifact_end_ms=671296`, `candidate_end_ms=666167`, `omitted_tail_duration_ms=5129`
- `activity-whisperx.json` keeps the full 671,296 ms timeline (evidence preserved).
- Selected cut unchanged: `01KXPJJDCFSM377W46WDS1CJZ3` v1; selection mirror `edit/cdl.json` untouched (mtime 2026-07-17, 654 clips, no `truncation`).
- `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock`; internal `/health` ok; public health 200; `/projects` unauthenticated 401.
- Backup: `release-backups/publisher-1d5886a-20260812T041713Z` (5 files); rollback tag `autoedit-rollback:20260812T041713Z` → prior image `sha256:7f495df2...` (strict-policy build).

## Evidence chain (autoedit-agents board)

- Spec: `t_5fce0081` DESIGN_APPROVED; amendment spec `t_e716618f` DESIGN_APPROVED.
- Compliance: `t_5653f10c` (r1, 4 findings), `t_c7d1aee9` (amendment r1, 4 findings), `t_c63fa076` (r2, 1 finding → committed regression `f1a4abd`).
- Corrections: `t_145a3c3b`, `t_245ced07`, `t_2c653895`, `t_6f813a30`, `t_f3fbef77` (all READY_FOR_REVIEW, exact SHAs in comments).
- Tester: `t_281b2632` TEST_PASS on `1d5886a` (45 focused; 851 full/3 expected skips).
- Publisher: `t_a461c537` — Tower `DEPLOYED_AND_VERIFIED` (see wrapper note below).
- Tests: `tests/test_terminal_source_coverage_truncation.py` (real-topology, pre-boundary gap, unsafe-wide, full-length control, determinism, atomicity); plan docs `docs/plans/phase-6-confirmed-diarization-turn-projection-fix.md`, `docs/plans/phase-6-terminal-source-coverage-truncation-policy.md` (on this branch).

## Known issues / ops notes

1. **Deploy wrapper misparse (fix first, ops):** `scripts/autoedit-deploy.sh` outer wrapper parses the early `RESULT:mutation_started` marker and emits verdict `DEPLOY_FAILED` even when Tower reports `DEPLOYED_AND_VERIFIED`. Always adjudicate by the Tower transcript. Happened on every deploy this cycle.
2. **Gateway `su hermes` is broken** (auth failure). Worker-UID commands: `docker exec -u 10000:100 -e HOME=/opt/data/profiles/<role> hermes-gateway ...`. On Tower host, the workspace path is under `/mnt/user/appdata/hermes/workspace`; inside gateway/WebUI it is `/opt/data/workspace` / `/workspace`.
3. **Credential/key paths:** reviewer secret `kanban/secrets/autoedit-test-account.json` (Tower appdata); deploy SSH key `/opt/data/home/.ssh/id_ed25519` (set `AUTOEDIT_SSH_KEY`).
4. **Design nuance (real project):** presenter cam ends 652,720 ms; wide ends 666,185 ms; audio master 671,296 ms with final presenter speech; a covered interviewee segment 667,208–668,083 ms sits between presenter-uncovered spans — the amended boundary rule handles it (end 666,167 ms), strict rule did not.

## Next steps (handoff)

1. **Fix the deploy wrapper parser** in `scripts/autoedit-deploy.sh` — **DONE 2026-08-12 (`a2ac9a8`):** the wrapper now takes the LAST bare `RESULT:` line (terminal verdict) via `tail -1` instead of the first (`mutation_started`), and retains the remote exit code (`REMOTE_RC`) in the JSON. Parser validated against success/failure/dry-run/rollback transcript shapes. New Publisher cards no longer need the "wrapper may misparse" caveat.
2. **Integrate branch → master:** **DONE 2026-08-12 (`a2ac9a8` on origin/master):** `phase6-confirmation-projection-spec` fast-forwarded into master (`63085e7` → `7b0d27f`), then wrapper fix + docs committed as `a2ac9a8` and pushed. Remote master SHA == local (`a2ac9a8`).
3. **Product question (open):** UI/player treatment when the candidate video (666,167 ms) is shorter than program audio (671,296 ms) — needs a player/UI decision (freeze frame, silence, timeline affordance).
4. **Optional:** select candidate `01KZT3372CDNV7SBKK18STZRZ2` as the chosen cut via the existing save endpoint (currently `selected=false`; VAD cut remains selected).
5. **Rollback path** if ever needed: `docker tag autoedit-rollback:20260812T041713Z autoedit-app` + recreate (or redeploy prior backup).

## Re-verification (read-only)

```bash
# Tower
curl -fsS http://127.0.0.1:8010/health
docker inspect -f '{{.State.Status}}|{{.RestartCount}}|{{.Image}}' autoedit-app-1
docker exec autoedit-app-1 sha256sum /app/src/autoedit/api.py
# DB (selection + ai row)
PW=$(cat /mnt/user/appdata/autoedit/.db-credential)
docker exec -e MYSQL_PWD="$PW" mysql mysql -u autoedit --socket=/var/run/mysqld/mysqld.sock -N -B autoedit \
  -e "SELECT id,JSON_EXTRACT(cdl_json,'$.truncation') FROM cuts WHERE id='01KZT3372CDNV7SBKK18STZRZ2';"
```
