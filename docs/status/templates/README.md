# Stall-recovery Tester acceptance templates (AUTOEDIT)

These templates are consumed by the recurring progress job
(`AUTOEDIT progress dashboard + stall recovery — every 3 hours`) when it
detects a stalled handoff: a Designer compliance card marked done with
`DESIGN_COMPLIANCE_PASS`, but the corresponding implementation card remains
`blocked` and no fresh `autoedittester` acceptance card exists yet.

## Usage

1. Read the blocked implementation card (`kanban show <impl_card>`) for its
   exact commit, worktree path, branch, requirement IDs, and named defects.
2. Read the Designer compliance card for the `DESIGN_COMPLIANCE_PASS` verdict
   and the commits it approved.
3. Copy `tester-acceptance-template.md`, substitute the placeholders:
   - `{{COMMIT}}` — implementation commit SHA
   - `{{WORKTREE}}` — worktree path
   - `{{BRANCH}}` — branch name
   - `{{PARENT_DESIGN_CARD}}` — Designer compliance card id
   - `{{IMPL_CARD}}` — blocked implementation card id
   - `{{SLUG}}` — short stable slug, e.g. `p1-home-ingest` or `p2-player`
4. Create the card (idempotent) and dispatch it:

```bash
BODY=$(cat /path/to/filled-template.md)
/app/venv/bin/hermes kanban --board autoedit-agents create \
  "Tester — <slug> independent acceptance (<commit>)" \
  --body "$BODY" \
  --assignee autoedittester \
  --parent <PARENT_DESIGN_CARD> \
  --workspace worktree:<WORKTREE> \
  --branch <BRANCH> \
  --project autoedit \
  --priority 91 \
  --created-by coordinator \
  --skill software-quality-workflows --skill computer-use \
  --idempotency-key tester-acceptance-<COMMIT> \
  --json

/app/venv/bin/hermes kanban --board autoedit-agents dispatch --max 2
```

Safety: never modify product source/tests, merge, deploy, or use OpenRouter.
Only create the forward-progress Tester card; never auto-merge or auto-deploy.
