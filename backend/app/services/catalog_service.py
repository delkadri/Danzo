import json
import os
import random
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..constants import ALL_CATEGORIES, DIFFICULTIES, MIN_WORDS_PER_DIFFICULTY
from ..extensions import db
from ..repositories import catalog_repository


_database_available: bool | None = None if os.getenv("DATABASE_URL") else False


def seed_file_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "words.json"


def load_seed_payload() -> dict:
    with seed_file_path().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def reset_failed_database_session() -> None:
    try:
        db.session.rollback()
    except Exception:
        db.session.remove()


def local_catalog_counts() -> dict[str, dict[str, int]]:
    payload = load_seed_payload()
    return {
        category: {
            difficulty: len(payload.get(category, {}).get(difficulty, []))
            for difficulty in DIFFICULTIES
        }
        for category in ALL_CATEGORIES
    }


def get_local_words(
    category: str,
    difficulty: str,
    count: int,
    exclude_words: list[str] | None = None,
) -> list[str]:
    payload = load_seed_payload()
    source_words = payload.get(category, {}).get(difficulty, [])
    words = [str(word).strip() for word in source_words if str(word).strip()]

    excluded = {word.casefold() for word in (exclude_words or [])}
    available = [word for word in words if word.casefold() not in excluded]
    if len(available) < count:
        available = words

    sample_size = min(max(count, 0), len(available))
    return random.sample(available, sample_size)


def validate_catalog_payload(payload: dict) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("Catalog seed must be a JSON object.")

    entries: list[dict[str, str]] = []

    for category in ALL_CATEGORIES:
        block = payload.get(category)
        if not isinstance(block, dict):
            raise ValueError(f"Missing category block '{category}' in seed file.")

        for difficulty in DIFFICULTIES:
            words = block.get(difficulty)
            if not isinstance(words, list):
                raise ValueError(
                    f"Category '{category}' difficulty '{difficulty}' must be a list."
                )
            if len(words) < MIN_WORDS_PER_DIFFICULTY:
                raise ValueError(
                    f"Category '{category}' difficulty '{difficulty}' has too few words "
                    f"({len(words)}/{MIN_WORDS_PER_DIFFICULTY})."
                )

            seen = set()
            for word in words:
                value = str(word or "").strip()
                if not value:
                    continue
                dedupe_key = value.casefold()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                entries.append(
                    {
                        "category": category,
                        "difficulty": difficulty,
                        "value": value,
                    }
                )

    return entries


def ensure_catalog_seeded(force: bool = False) -> dict[str, object]:
    global _database_available

    payload = load_seed_payload()
    entries = validate_catalog_payload(payload)

    try:
        if force or catalog_repository.count_words() == 0:
            inserted = catalog_repository.replace_catalog(entries)
            _database_available = True
            return {
                "seeded": True,
                "entries": inserted,
                "source": str(seed_file_path()),
            }

        _database_available = True
        return {
            "seeded": False,
            "entries": catalog_repository.count_words(),
            "source": str(seed_file_path()),
        }
    except SQLAlchemyError:
        _database_available = False
        reset_failed_database_session()
        raise


def get_public_meta() -> dict[str, object]:
    return {
        "categories": ALL_CATEGORIES,
        "difficulties": DIFFICULTIES,
        "catalog": get_catalog_counts(),
    }


def get_catalog_counts() -> dict[str, dict[str, int]]:
    global _database_available

    if _database_available is False:
        return local_catalog_counts()

    try:
        counts = catalog_repository.get_catalog_counts()
        if not any(counts.values()):
            return local_catalog_counts()
        _database_available = True
    except SQLAlchemyError:
        _database_available = False
        reset_failed_database_session()
        return local_catalog_counts()

    completed: dict[str, dict[str, int]] = {}
    for category in ALL_CATEGORIES:
        completed[category] = {
            difficulty: int(counts.get(category, {}).get(difficulty, 0))
            for difficulty in DIFFICULTIES
        }
    return completed


def get_words(category: str, difficulty: str, count: int, exclude_words: list[str] | None = None) -> list[str]:
    global _database_available

    if _database_available is not False:
        try:
            words = catalog_repository.fetch_random_words(
                category=category,
                difficulty=difficulty,
                count=count,
                exclude_words=exclude_words,
            )
            if len(words) >= count:
                _database_available = True
                return words
        except SQLAlchemyError:
            _database_available = False
            reset_failed_database_session()

    return get_local_words(
        category=category,
        difficulty=difficulty,
        count=count,
        exclude_words=exclude_words,
    )


def healthcheck() -> dict[str, object]:
    global _database_available

    if _database_available is not False:
        try:
            db.session.execute(text("SELECT 1"))
            entries = catalog_repository.count_words()
            _database_available = True
            return {
                "ok": True,
                "database": "up",
                "catalog_source": "database" if entries else "seed_file",
                "catalog_entries": entries or sum(
                    sum(difficulties.values())
                    for difficulties in local_catalog_counts().values()
                ),
            }
        except SQLAlchemyError:
            _database_available = False
            reset_failed_database_session()

    counts = local_catalog_counts()
    return {
        "ok": True,
        "database": "unavailable",
        "catalog_source": "seed_file",
        "catalog_entries": sum(sum(values.values()) for values in counts.values()),
    }
