"""Typed parameter and response storage. Public IDs are unique within their kind."""
from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, FetchedValue, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func, text,
)

from app.core.database.base import Base


class ApiContractEntry(Base):
    __tablename__ = "api_contract_entry"
    __table_args__ = (
        UniqueConstraint("kind", "public_id", name="uq_api_contract_public_id"),
        CheckConstraint(
            "(kind = 'PARAMETER' AND name IS NOT NULL AND location IS NOT NULL AND type IS NOT NULL "
            "AND required IS NOT NULL AND status_code IS NULL AND response_key IS NULL AND example_json "
            "IS NULL AND updated_at IS NULL) OR (kind = 'RESPONSE' AND response_key IS NOT NULL AND "
            "updated_at IS NOT NULL AND name IS NULL AND location IS NULL AND type IS NULL AND required "
            "IS NULL AND example IS NULL AND default_value IS NULL)", name="ck_api_contract_kind",
        ),
        Index("ix_api_contract_order", "interface_id", "kind", "sort", "public_id"),
        Index("ix_api_contract_location", "interface_id", "location",
              postgresql_where=text("kind = 'PARAMETER'"), sqlite_where=text("kind = 'PARAMETER'")),
        Index("ix_api_contract_status", "interface_id", "status_code",
              postgresql_where=text("kind = 'RESPONSE'"), sqlite_where=text("kind = 'RESPONSE'")),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(12), nullable=False)
    public_id = Column(Integer, nullable=False, server_default=FetchedValue())
    interface_id = Column(Integer, ForeignKey("api_interface.id", ondelete="CASCADE"), nullable=False)
    sort = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    description = Column(String(500))
    schema_json = Column(JSON)
    name = Column(String(100))
    location = Column(String(10))
    type = Column(String(30))
    required = Column(Boolean)
    example = Column(Text)
    default_value = Column(Text)
    status_code = Column(Integer)
    response_key = Column(String(16))
    example_json = Column(Text)
    updated_at = Column(DateTime)
