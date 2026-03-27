import json
from pathlib import Path

from sqlalchemy import text

from ..constants import ALL_CATEGORIES, DIFFICULTIES, MIN_WORDS_PER_DIFFICULTY
from ..extensions import db
from ..repositories import catalog_repository


def seed_file_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "words.json"


def load_seed_payload() -> dict:
    with seed_file_path().open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
    payload = load_seed_payload()
    entries = validate_catalog_payload(payload)

    if force or catalog_repository.count_words() == 0:
        inserted = catalog_repository.replace_catalog(entries)
        return {
            "seeded": True,
            "entries": inserted,
            "source": str(seed_file_path()),
        }

    return {
        "seeded": False,
        "entries": catalog_repository.count_words(),
        "source": str(seed_file_path()),
    }


def get_public_meta() -> dict[str, object]:
    return {
        "categories": ALL_CATEGORIES,
        "difficulties": DIFFICULTIES,
        "catalog": get_catalog_counts(),
    }


def get_catalog_counts() -> dict[str, dict[str, int]]:
    counts = catalog_repository.get_catalog_counts()
    completed: dict[str, dict[str, int]] = {}
    for category in ALL_CATEGORIES:
        completed[category] = {
            difficulty: int(counts.get(category, {}).get(difficulty, 0))
            for difficulty in DIFFICULTIES
        }
    return completed


def get_words(category: str, difficulty: str, count: int, exclude_words: list[str] | None = None) -> list[str]:
    return catalog_repository.fetch_random_words(
        category=category,
        difficulty=difficulty,
        count=count,
        exclude_words=exclude_words,
    )


def healthcheck() -> dict[str, object]:
    db.session.execute(text("SELECT 1"))
    return {
        "ok": True,
        "database": "up",
        "catalog_entries": catalog_repository.count_words(),
    }
