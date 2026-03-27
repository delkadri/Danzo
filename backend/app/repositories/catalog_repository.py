from collections import defaultdict

from sqlalchemy import func, select

from ..extensions import db
from ..models import Word


def count_words() -> int:
    return db.session.execute(select(func.count(Word.id))).scalar_one()


def replace_catalog(entries: list[dict[str, str]]) -> int:
    Word.query.delete()
    db.session.bulk_insert_mappings(Word, entries)
    db.session.commit()
    return len(entries)


def get_catalog_counts() -> dict[str, dict[str, int]]:
    rows = db.session.execute(
        select(Word.category, Word.difficulty, func.count(Word.id))
        .group_by(Word.category, Word.difficulty)
        .order_by(Word.category, Word.difficulty)
    ).all()

    stats = defaultdict(dict)
    for category, difficulty, count in rows:
        stats[str(category)][str(difficulty)] = int(count)

    return {category: dict(difficulties) for category, difficulties in stats.items()}


def fetch_random_words(
    category: str,
    difficulty: str,
    count: int,
    exclude_words: list[str] | None = None,
) -> list[str]:
    stmt = (
        select(Word.value)
        .where(Word.category == category, Word.difficulty == difficulty)
        .order_by(func.random())
    )

    if exclude_words:
        stmt = stmt.where(Word.value.not_in(exclude_words))

    words = list(db.session.execute(stmt.limit(count)).scalars())
    if len(words) >= count:
        return words

    fallback_stmt = (
        select(Word.value)
        .where(Word.category == category, Word.difficulty == difficulty)
        .order_by(func.random())
        .limit(count)
    )
    return list(db.session.execute(fallback_stmt).scalars())
