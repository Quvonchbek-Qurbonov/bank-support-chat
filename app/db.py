from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(10), index=True)
    page_url: Mapped[str] = mapped_column(String(2000))
    api_url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    discovered_from: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_updated_at: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
