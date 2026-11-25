"""Typed historical evidence retained for audit and downgrade replay."""
from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String

from app.core.database.base import Base


class MigrationEvidence(Base):
    __tablename__ = "migration_evidence"
    __table_args__ = (CheckConstraint(
        "(kind = 'SCOPE_CHECK' AND metric IS NOT NULL AND before_count IS NOT NULL AND after_count IS NOT NULL "
        "AND test_case_id IS NULL AND project_id IS NULL AND previous_status IS NULL "
        "AND replacement_resource_id IS NULL AND decision IS NULL) OR "
        "(kind = 'API_BACKFILL' AND test_case_id IS NOT NULL AND test_case_id = public_id AND metric IS NULL "
        "AND before_count IS NULL AND after_count IS NULL AND project_id IS NULL AND previous_status IS NULL "
        "AND replacement_resource_id IS NULL AND decision IS NULL) OR "
        "(kind = 'MODEL_AUDIT' AND decision IS NOT NULL AND metric IS NULL AND before_count IS NULL "
        "AND after_count IS NULL AND test_case_id IS NULL)", name="ck_migration_evidence_kind",
    ),)

    kind = Column(String(20), primary_key=True)
    public_id = Column(Integer, primary_key=True)
    metric = Column(String(80), unique=True)
    before_count = Column(Integer)
    after_count = Column(Integer)
    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="CASCADE"))
    project_id = Column(Integer)
    previous_status = Column(String(20))
    replacement_resource_id = Column(Integer)
    decision = Column(String(40))
