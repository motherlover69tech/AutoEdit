Fresh, independent acceptance test of the implementation at commit {{COMMIT}} in worktree {{WORKTREE}} (branch {{BRANCH}}).

Parent: Designer compliance card {{PARENT_DESIGN_CARD}} returned DESIGN_COMPLIANCE_PASS. This is the required independent Tester acceptance before integration.

Do NOT trust the Programmer's or Designer's summaries — run everything yourself. Read-only with respect to production (no Unraid/deployed-container mutation); local runtime only.

Scope and acceptance criteria: take the requirement IDs and acceptance evidence from the linked implementation card {{IMPL_CARD}} and the approved design. At minimum verify:
- Backend/API: run the suite the same way the implementation did and report exact counts. Also run targeted `-k "player or web or static"` and any language-specific regression suite used by that card.
- Real browser testing at desktop 1440px AND mobile 375px against a locally served ready project (mock pipeline/fixture acceptable):
  - Default UI state matches the approved simplification; progressive disclosure collapsed by default.
  - Zero console errors; no failing requests introduced by the UI.
  - No horizontal overflow at 375px in any shown state.
  - Any specific defects named in {{IMPL_CARD}} are reproduced as fixed (or still failing).
- Capture screenshots for every checked state under /tmp/autoedit_tester_{{SLUG}}/ and list paths. Any defect: write a reproducible bug report as a card comment.

Verdict: comment a requirement->evidence->pass/fail matrix and end with exactly one of TEST_PASS or TEST_FAIL (with defect list). Then kanban_block(reason="test-verdict: <TEST_PASS|TEST_FAIL> {{SLUG}}") for oversight review. Do not modify product code. Do not merge or deploy.

Fill placeholders from `kanban show` of the blocked implementation card (commit/worktree/branch) and the Designer compliance card (parent + pass verdict). Use a stable --idempotency-key such as `tester-acceptance-{{COMMIT}}` and --parent {{PARENT_DESIGN_CARD}}.
