"""Vector index for semantic discovery.

Embeddings come from a pluggable provider. The default is a deterministic local
implementation, so results are reproducible offline and in CI. Dimension is
fixed at the table level; swapping to a real model requires a migration.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column

EMBEDDING_DIM = 256


class WorkEmbedding(Base, TimestampMixin):
    __tablename__ = "work_embeddings"

    id: Mapped[str] = id_column("emb")
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    work_version_id: Mapped[str] = mapped_column(
        ForeignKey("work_versions.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), default="deterministic", nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    __table_args__ = (
        UniqueConstraint("work_version_id", "provider", name="uq_work_embeddings_version_provider"),
        Index(
            "ix_work_embeddings_vector",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
