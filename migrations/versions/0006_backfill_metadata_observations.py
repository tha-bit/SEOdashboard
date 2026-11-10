"""Backfill Phase 3 observations from previously confirmed Screaming Frog rows.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ImportBatch, ImportRow, PageMetadataObservation
from backend.services.imports import metadata_observation_payload

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    session = Session(bind=op.get_bind())
    batches = list(session.scalars(select(ImportBatch).where(ImportBatch.source == "screaming_frog", ImportBatch.status.in_(["completed", "completed_with_errors"]))))
    for batch in batches:
        already_observed = session.scalar(select(PageMetadataObservation.id).where(PageMetadataObservation.import_batch_id == batch.id).limit(1))
        if already_observed:
            continue
        rows = session.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id, ImportRow.page_id.is_not(None)).order_by(ImportRow.row_number)).all()
        for row in rows:
            data, supplied_fields, source_columns = metadata_observation_payload(row.raw_data or {}, batch.mapping or {})
            if not supplied_fields:
                continue
            session.add(PageMetadataObservation(
                project_id=batch.project_id,
                page_id=row.page_id,
                import_batch_id=batch.id,
                source_label=f"Screaming Frog · {batch.file_name} · migrated",
                reporting_date=batch.reporting_date,
                observed_at=batch.imported_at,
                supplied_fields=supplied_fields,
                source_columns=source_columns,
                data=data,
            ))
    session.commit()


def downgrade():
    session = Session(bind=op.get_bind())
    rows = session.scalars(select(PageMetadataObservation).where(PageMetadataObservation.source_label.like("% · migrated"))).all()
    for row in rows:
        session.delete(row)
    session.commit()
