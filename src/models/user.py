from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_external_identity"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
