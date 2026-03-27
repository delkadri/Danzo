from datetime import datetime, timezone

from .extensions import db


class Word(db.Model):
    __tablename__ = "words"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(32), nullable=False, index=True)
    difficulty = db.Column(db.String(16), nullable=False, index=True)
    value = db.Column(db.String(160), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint("category", "difficulty", "value", name="uq_words_catalog_entry"),
    )
