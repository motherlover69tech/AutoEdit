# AUTOEDIT progress reporting contract

**Last contract review:** `2026-07-17T17:31:44Z`

**Dashboard:** `docs/status/autoedit-progress.html`
**Cadence:** every three hours while active work continues
**Purpose:** give Peter one durable, collapsible, evidence-based view of the numbered AUTOEDIT product stages, the separate real-AI modernization phases, and work performed by each agent.

## 1. Taxonomies must stay separate

1. **Numbered product plan:** use the exact stage and sub-stage headings from `docs/source/multicam_autoedit_spec.md`. Derive the current product-plan position afresh from the spec, backlog, handoff, live board, and acceptance evidence. Never pin this contract or either scheduled job to one stage.
2. **Real-AI modernization:** use the Phase 0–8 roadmap in `docs/plans/whisperx-speaker-aware-ai-roadmap.md` and related corrective/acceptance plans. This is a separate track; never call an AI phase an AUTOEDIT product stage.
3. **Agent workflow:** Designer → Programmer → Designer compliance → Tester → integration → deployment approval. These are delivery gates, not product stages.

## 2. Required evidence order

Each refresh should inspect, in this order:

1. Authoritative plan/spec and relevant acceptance documents.
2. Live Kanban board `autoedit-agents`: tasks, current status, comments, runs, heartbeats, and returned child-card IDs.
3. Git base branch, worktree branches, commits, clean/dirty state, and whether any commit is integrated.
4. Existing test logs, QA reports, browser evidence, screenshots, and payload records referenced by the cards.
5. Production state only when explicitly authorized and safely available read-only. Do not infer deployment from a completed commit.

Agent summaries are useful leads, but they are not independent acceptance proof. Distinguish clearly between:

- **Reported by agent** — evidence exists only in that agent's handoff.
- **Independently verified** — another role or the coordinator inspected/reran the evidence.
- **Accepted** — the required review gate recorded a pass.
- **Integrated** — the exact commit is present in the base branch.
- **Deployed** — separately verified in production after explicit approval.

## 3. Dashboard sections that must remain

- Snapshot timestamp and safety/deployment boundary.
- At-a-glance current product stage, AI phase, active agent, and integration state.
- **Just done**, **Now**, **Next**, blockers, and next approval gate.
- All numbered product stages and exact sub-stages in collapsible sections.
- Real-AI Phase 0–8 in a separately labelled collapsible section.
- Per-agent cards for Coordinator, Designer, Programmer, and Tester, with durable card IDs and commits where applicable.
- A collapsible **Plain-English glossary** covering the technical and project terms used in the report, including VAD, Whisper, WhisperX, the separate WhisperX service/worker, diarization, media/export terms, and delivery-state terms. Preserve existing definitions; add or clarify a term when new jargon appears.
- A separate **"Reporting contract"** section describing the scheduled jobs, cadence, and safety boundaries. Two jobs exist: (a) the 3-hour dashboard job (`openai-codex` / `gpt-5.6-luna`, report-only, writes only this dashboard); (b) the 30-minute coordinator watchdog (`openai-codex` / `gpt-5.6-sol`) which dynamically reads the whole live board plus backlog/handoff, selects the highest-priority dependency-eligible chain, and performs at most one coordination action. Neither job is tied to a named stage or feature. The watchdog never edits code, tests, merges, or deploys; deployment remains Designer-gated and Publisher-executed through `scripts/autoedit-deploy.sh`. OpenRouter stays forbidden for workers.
- **Evidence screenshots must be embedded** when a `TEST_PASS` from real Chromium exists. The BUG-AE-P2-003 rerun produced four PNGs: `/tmp/autoedit_desktop_non2xx.png` (desktop 1440×900 visible non-2xx error), `/tmp/autoedit_mobile_non2xx.png` (mobile 375×812 same), `/tmp/autoedit_desktop_thrown.png` (thrown-fetch recovery), `/tmp/autoedit_desktop_success_reload.png` (success list+marker + reload persistence). Render them as `<img>` referencing `MEDIA:/tmp/...` (or base64 if the renderer needs inline) inside the Stage 7.4 evidence block, with captions labelling viewport + behavior. Do not omit browser evidence when it exists.
- Evidence ledger with paths, card IDs, commit IDs, and exact test/browser counts.
- Reporting cadence and restricted write scope.

## 4. Status vocabulary

Use these labels consistently:

- **Done:** implemented and accepted for the stated scope.
- **Current / In progress:** active work or an acceptance gate is open.
- **Mixed:** deterministic/mock/primary scope works, but a real, optional, or secondary acceptance path remains open.
- **Planned:** not yet started under the current roadmap.
- **Blocked:** a concrete dependency, failed gate, or explicit approval is required.
- **Reported:** an agent claims the result, but it has not yet passed independent acceptance.

Do not collapse “implemented,” “tested,” “merged,” and “deployed” into one status.

## 5. Three-hour update procedure

1. Record the current UTC timestamp.
2. Read this contract and the current HTML before editing.
3. Gather a fresh Kanban/Git/evidence snapshot.
4. Identify material changes since the timestamp embedded in `<body data-updated-utc="…">`.
5. Update only factual report content and timestamp fields. Preserve the self-contained CSS/JS, collapsible controls, mobile layout, taxonomy, and safety banner.
6. Update “Just done” only for genuinely new completed evidence; move older items into the relevant stage or evidence ledger.
7. Update each agent card from durable board evidence, including card IDs and precise verdicts.
8. Keep current blockers and next gates explicit.
9. Validate the HTML before finishing:
   - parses successfully;
   - contains no external scripts/styles/assets;
   - retains all product stages 3–9 and all exact sub-stage labels;
   - retains AI Phase 0–8;
   - has no duplicate element IDs;
   - embedded JavaScript passes syntax checking;
   - renders without horizontal overflow at desktop and 375px mobile widths when a browser is available.
10. Deliver a short summary stating whether the dashboard changed and what materially moved. Attach/link the HTML file when the delivery surface supports it.

## 6. Safety boundary for scheduled runs

Scheduled reporting may write **only**:

- `/workspace/AUTOEDIT/docs/status/autoedit-progress.html`

It must not:

- edit product source or tests;
- create, update, block, archive, dispatch, or run Kanban cards;
- start or stop agents;
- commit, merge, push, rebase, or deploy;
- mutate Docker, Unraid, databases, NPM, production, source media, or user data;
- alter provider/model configuration;
- expose credentials or secrets.

### Coordination belongs to the separate watchdog

The dashboard job is strictly report-only. All board mutation belongs to the separate 30-minute coordinator watchdog, which may take at most one stage-agnostic coordination action per tick under its own loop-breakers and safety boundary. This separation prevents two recurring jobs from racing or creating duplicate successors.

If evidence is inaccessible, stale, contradictory, or incomplete, preserve the last verified state and label the uncertainty. Never invent progress.

## 7. Maintenance and retirement

The job can continue indefinitely while active development is underway. Pause or remove it when Peter says reporting is no longer needed. If the file structure must change materially, update this contract first so future scheduled runs remain deterministic and reviewable.
