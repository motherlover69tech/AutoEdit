# 2026-08-14 — POSTGAP Deploy + Board Clear + GATE-3 Regeneration Session

**Status: COMPLETE.** W1–W6 redesign (`97149bc`) deployed live and verified; superseded
kanban cards archived; GATE-3 candidate regenerated from the accepted artifact with the
POSTGAP-R1/R2 fix and selected (v5). **Peter's GATE-3 editorial re-review is the only
remaining acceptance item in the AI-GPU-1 flow.**

## 1. Kanban board cleared (matches reality)

- 54 superseded cards archived (53 blocked + 1 todo) with an audit comment on each:
  "Superseded audit record (rounds 3-7). Work replaced by the direct W1-W6 redesign at
  master 97149bc (docs/status/2026-08-14-next-stage-work.md)… No further work on this card."
- All archiving done via the gateway CLI (`hermes -p coordinator kanban archive`) in
  `hermes-gateway`; board DB identity confirmed first (sandbox md5 == gateway md5
  `f7bc77e9…`).
- Board now: **175 done / 141 archived / 0 blocked / 0 todo / 0 ready.** No dispatcher work.

## 2. Deploy `97149bc` (W1–W6 redesign) — DEPLOYED_AND_VERIFIED

- Command: `scripts/autoedit-deploy.sh --worktree .worktrees/deploy-97149bc --commit 97149bc…`
  (backup → source transfer → compose validation → rebuild → health check → rollback-ready).
- **New image `sha256:44938d4e…`** (prior `d60d773c`); container restarts **0**;
  started 2026-08-14T09:08:41Z. Backup dir
  `release-backups/publisher-97149bc-20260814T090825Z` (config archive + DB dump 389 KB +
  prior-image tag); rollback tag `autoedit-rollback:20260814T090825Z`.
- Public `/health` 200, unauth `/projects` 401, NPM `ingest.peteflix.uk` 200.
- Production backends preserved: `WHISPER_BACKEND=mock`, `DIARIZE_BACKEND=mock` (.env + container env).
- New code verified live in container: `ops/gate4_observer.py`, `ops/dots_completion.py`,
  `speaker-confirmations/batch` route, `DB_SORT_BUFFER_SIZE` env.
- **W6.1 live:** per-connection `SET SESSION sort_buffer_size` (16 MiB default) applied;
  `ix_cuts_project_created_id` index on `cuts(project_id, created_at, id)` created by the
  startup migration (verified via `SHOW INDEX`). Compose delta (3-line env passthrough)
  applied after deploy with backup (`docker-compose.pre-sortbuf.yml`), config validated,
  container recreated `--no-build`, health re-verified, restarts 0.
- Rendered-Compose check on deployment host: OK (host networking, DB 192.168.50.50,
  mock|mock, port 8010) — 54-line render saved to `/tmp/autoedit-compose-render.txt` on Tower.

## 3. GATE-3 candidate regenerated + selected (POSTGAP-R1/R2 live)

- `POST /projects/01KXPHM8XCBKZ96Y2JN6T9Q2MC/cut` with `analysis_source=whisperx` and the
  current cut's exact params (min_shot 800 / lead 80 / tail 150 / silence wide /
  wide_interval 45 s / overlap_min 1200 / interject_max 1500 / overlap_to_wide).
- New candidate **`01KZZRRT8SY5XY5TVN66XF6Z1Y`** ("GATE-3 POSTGAP rerun 97149bc"), bound to
  the **accepted artifact `live-20260814T004600Z`**, validation `valid`, 268 clips.
- Selected via `PUT /cut-selection` (expected_version 4 → **version 5**); mirror
  `edit/cdl.json` rewritten atomically; player-state serves the candidate
  (`selection_version: 5`, 268 clips, `whisperx_available: true`, mapping confirmed).
- **Post-gap boundary verification (the five clips Peter flagged):** 49762 / 92135 / 205467 /
  212318 / 316690 now project **`low_confidence:wide`** (fail-safe) instead of the wrong
  speaker's close-up. Reason census shifted: Low confidence 0→18, Speaking 140→112,
  Brief interjection hold 21→5, Silence 62→67, Crosstalk 39→48, Variety 1→3.
- Normal resolution intact: confirmed solo region 6832–11139 → Pete close cam
  (`speaker:interviewee`); overlap 11139–11422 → Wide (`overlap:wide`).
- Previous selected cut (v4 `01KZYT4PWN69CNDY3ZTA7229Q7`) remains in the cuts table
  (revert = `PUT` it with `expected_version: 5`). VAD baseline cuts untouched.

## 4. Remaining work

1. **Peter's GATE-3 re-review** (ingest.peteflix.uk → "sm test cab", cut v5): verify the
   post-gap regions (esp. 46387–51196, 89146–93029, 204432–213145, 307877–317568) read as
   wide/hold where the old cut showed wrong close-ups; sign PASS/FAIL per checklist.
2. **Rollout decision** for `WHISPER_BACKEND=whisperx` / `DIARIZE_BACKEND=whisperx` —
   separate, explicitly authorized step; stays mock until then.
3. Future **trusted-host GATE-4 collector** (separate authorization; the read-only observer
   shipped in 97149bc is not an executor).
4. Stage 8.3 OTIO fallback (optional; direct EDL already Resolve-verified) and Stage 9.2
   LLM-backed YouTube title generator remain open in the backlog.
5. Coordinating crons stay paused while Peter drives; resume watchdogs/dashboard on request.

## 5. Tidy-ups (recorded in this commit `be8d61b`)

- **Deploy wrapper safety booleans fixed** (`scripts/autoedit-deploy.sh`): the
  `emit_json` verdict always reported `"mutation_started": "false"` and
  `"candidate_live": "false"` even after a real rebuild+recreate — the local
  parser never derived them from the remote output. They now derive from the
  remote `RESULT:mutation_started` marker and the terminal verdict, so future
  deploy JSONs are honest. (Older wrapper JSONs: treat those two fields as
  unset; image SHA + `RESULT:` lines are the truth.)
- **Session records committed and pushed:** this doc + checklist GATE-3 update
  + BACKLOG current-state/next-action update + the wrapper fix landed as commit
  `be8d61b` on master, pushed to origin and verified
  (`git ls-remote` == `git rev-parse HEAD` == `be8d61b65396…`).
- **Ops lessons saved to the `autoedit-ops` skill** as
  `references/tower-ssh-deploy-2026-08-14.md` (Tower host has no python3/jq;
  `curl -d` defaults to POST — use `-X PUT`; mass-archive recipe for
  superseded cards; reusable `scripts/ssh_tower.py` / `run_on_tower.py` /
  `sftp_get.py` helpers; deploy payload note — compose/.env changes are NOT
  carried by the deploy script; verified GATE-3 regeneration sequence).

## Evidence pointers (private, on-array — not in Git)

- `/mnt/user/automulticam/ai-gpu-1-acceptance/20260813-live-window/`
- `/mnt/user/automulticam/ai-gpu-1-acceptance/20260814-live-window-gate4/`
- Deploy backup: `/mnt/user/appdata/autoedit/release-backups/publisher-97149bc-20260814T090825Z/`
