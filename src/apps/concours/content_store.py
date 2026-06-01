"""
MongoDB content store for concours exam JSON structures.

One document per ConcoursExam, looked up by (concours_type, display_id).
Mirrors apps/things/content_store.py.

Document shape:
{
    "concours_type": "ensa" | "ensam" | "medecine",
    "display_id":    <int>,
    "json_content":  {
        "version": "1.0",
        "questions": [
            {
                "id": "q1",
                "statement": "<rich HTML>",
                "options": [{"key": "A", "text": "..."}, ...],
                "correct_key": "B",
                "explanation": "<rich HTML>",
                "subject_id":  <int|null>,
                "subfield_id": <int|null>,
                "chapter_id":  <int|null>,
                "tip_id":      <int|null>,
                "points":      <int, default 1>
            }
        ]
    },
    "created_at": <datetime>,
    "updated_at": <datetime>,
}
"""

from datetime import datetime, timezone

from config.mongodb import get_db


COLLECTION = 'concours_structures'


def _col():
    col = get_db()[COLLECTION]
    # Ensure unique index — cheap idempotent operation.
    col.create_index([('concours_type', 1), ('display_id', 1)], unique=True)
    return col


def get_concours_structure(concours_type: str, display_id: int) -> dict:
    """Return the json_content dict, or {} if absent."""
    doc = _col().find_one(
        {'concours_type': concours_type, 'display_id': display_id},
        {'_id': 0, 'json_content': 1},
    )
    return doc['json_content'] if doc else {}


def get_concours_structures_batch(concours_type: str, display_ids: list) -> dict:
    """Return {display_id: json_content} for all given IDs in one query."""
    if not display_ids:
        return {}
    docs = _col().find(
        {'concours_type': concours_type, 'display_id': {'$in': display_ids}},
        {'_id': 0, 'display_id': 1, 'json_content': 1},
    )
    return {doc['display_id']: doc['json_content'] for doc in docs}


def set_concours_structure(concours_type: str, display_id: int, json_content: dict) -> None:
    """Insert or replace the json_content for (concours_type, display_id)."""
    now = datetime.now(tz=timezone.utc)
    _col().update_one(
        {'concours_type': concours_type, 'display_id': display_id},
        {
            '$set': {'json_content': json_content, 'updated_at': now},
            '$setOnInsert': {
                'concours_type': concours_type,
                'display_id': display_id,
                'created_at': now,
            },
        },
        upsert=True,
    )


def delete_concours_structure(concours_type: str, display_id: int) -> None:
    _col().delete_one({'concours_type': concours_type, 'display_id': display_id})
