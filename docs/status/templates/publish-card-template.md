# Publish card template — AUTOEDIT → live (Unraid)

Created by the **Designer** after implementation, compliance, and Tester `TEST_PASS` are all done.

The Publisher's entire job: **run the deploy script, paste its JSON output, block the card.**

---

Title:
```
Publish AUTOEDIT to live — <slug> (<SHORT_COMMIT>)
```

Body:
```
Deploy commit {{COMMIT}} to live Unraid.

Step 1 — run the deploy script:

  bash scripts/autoedit-deploy.sh \
    --worktree {{WORKTREE}} \
    --commit   {{COMMIT}} \
    --files    "{{FILES}}"

Step 2 — paste the JSON the script printed into a comment.

Step 3 — block the card with the verdict from the JSON:
  - DEPLOYED_AND_VERIFIED
  - DEPLOY_FAILED (the script already rolled back; do not retry)

Do not run any other command. Do not retry.
```

Create:
```bash
BODY=$(cat /tmp/publish_body.md)
/app/venv/bin/hermes kanban --board autoedit-agents create \
  "Publish AUTOEDIT to live — <slug> (<SHORT_COMMIT>)" \
  --body "$BODY" \
  --assignee autoeditpublisher \
  --workspace worktree:<PUBLISH_WORKTREE> \
  --project autoedit \
  --priority 95 \
  --created-by autoeditdesigner \
  --skill unraid-docker-administration --skill homelab-infrastructure-operations --skill github-operations --skill software-quality-workflows --skill systematic-debugging \
  --idempotency-key publish-<BRANCH>-<SHORT_COMMIT> \
  --max-retries 1 \
  --json

/app/venv/bin/hermes kanban --board autoedit-agents dispatch --max 1
```

Notes for the Designer creating the card:
- `--max-retries 1`: one attempt, no loop. Use the terminal CLI if the kanban tool can't set it.
- `--workspace` must be an absolute `worktree:` path.
- OpenRouter is forbidden for the publisher profile (enforced in profile config, not in the card body).
- The script (`scripts/autoedit-deploy.sh`) handles everything else: backup, DB dump, transfer, build, health check, rollback. That's why the card body doesn't mention them.
