import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk, utcnow
from glasshaus.goals.schemas import Confidence, KeyResultKind


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e], validate_strings=True)


class Portfolio(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "portfolios"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="", server_default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PortfolioProject(TenantScoped, Base):
    __tablename__ = "portfolio_projects"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class Objective(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "objectives"
    __table_args__ = (Index("ix_objectives_period", "tenant_id", "period"),)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("objectives.id", ondelete="SET NULL"))


class KeyResult(UUIDPk, TenantScoped, TimestampMixin, Base):
    __tablename__ = "key_results"
    __table_args__ = (CheckConstraint("weight > 0", name="weight_positive"),)

    objective_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[KeyResultKind] = mapped_column(_enum(KeyResultKind, "key_result_kind"), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    start_value: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    target_value: Mapped[float] = mapped_column(Float, nullable=False, default=100, server_default="100")
    current_value: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    tag: Mapped[str | None] = mapped_column(String(50))
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1, server_default="1")
    position: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    confidence: Mapped[Confidence | None] = mapped_column(_enum(Confidence, "kr_confidence"))


class CheckIn(UUIDPk, TenantScoped, Base):
    __tablename__ = "kr_check_ins"

    key_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("key_results.id", ondelete="CASCADE"), index=True, nullable=False
    )
    value: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[Confidence] = mapped_column(_enum(Confidence, "kr_confidence"), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="", server_default="")
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=text("now()")
    )
