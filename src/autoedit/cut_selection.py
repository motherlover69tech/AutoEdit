from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from autoedit.db.schema import cuts, project_cut_selections


def resolve_selected_cut(session: Session, project_id: str):
    """Resolve the persisted authority, with legacy read compatibility."""
    row = session.execute(
        select(cuts, project_cut_selections.c.version.label("selection_version"))
        .join(project_cut_selections, project_cut_selections.c.cut_id == cuts.c.id)
        .where(
            project_cut_selections.c.project_id == project_id,
            cuts.c.project_id == project_id,
        )
    ).first()
    if row is not None:
        return row
    # Older test fixtures/installations may create a cut after migration. Keep
    # their historical latest-rough behavior until the next migration backfill.
    return session.execute(
        select(cuts,).where(cuts.c.project_id == project_id, cuts.c.kind == "rough")
        .order_by(cuts.c.created_at.desc(), cuts.c.id.desc()).limit(1)
    ).first()
