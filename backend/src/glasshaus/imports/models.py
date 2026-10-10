import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from glasshaus.core.orm import Base, TenantScoped, TimestampMixin, UUIDPk


class ImportLink(UUIDPk, TenantScoped, TimestampMixin, Base):
    """What an imported item became, so importing the same file again updates instead of duplicating.

    ``key`` is the source's own id for a task (Nimble's work item id, a spreadsheet's ID column), or
    that id plus a hash of the text for a comment.
    """

    __tablename__ = "import_links"
    __table_args__ = (UniqueConstraint("project_id", "source", "kind", "key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # task | comment
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
