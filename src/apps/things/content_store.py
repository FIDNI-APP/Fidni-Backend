"""
MongoDB content store — single source of truth for content structure.

Each document:
{
    "type":       "exercise" | "lesson" | "exam",
    "display_id": <int>,
    "json_content": {
        "version": "2.0",
        "blocks": [ ... ]
    },
    "created_at": <datetime>,
    "updated_at": <datetime>,
}

Lookup key: (type, display_id) — unique index enforced at connection time.
"""

import logging
from datetime import datetime, timezone

from config.mongodb import get_db

logger = logging.getLogger('django')

COLLECTION = 'content_structures'


def _col():
    return get_db()[COLLECTION]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_structure(content_type: str, display_id: int) -> dict:
    """Return the json_content dict or {} if not found."""
    doc = _col().find_one(
        {'type': content_type, 'display_id': display_id},
        {'_id': 0, 'json_content': 1},
    )
    return doc['json_content'] if doc else {}


def get_structures_batch(content_type: str, display_ids: list) -> dict:
    """Return {display_id: json_content} for all given IDs in one query."""
    docs = _col().find(
        {'type': content_type, 'display_id': {'$in': display_ids}},
        {'_id': 0, 'display_id': 1, 'json_content': 1},
    )
    return {doc['display_id']: doc['json_content'] for doc in docs}


def upsert_structure(content_type: str, display_id: int, json_content: dict) -> None:
    """Insert or replace the json_content for (type, display_id)."""
    now = datetime.now(tz=timezone.utc)
    _col().update_one(
        {'type': content_type, 'display_id': display_id},
        {
            '$set': {
                'json_content': json_content,
                'updated_at': now,
            },
            '$setOnInsert': {
                'type': content_type,
                'display_id': display_id,
                'created_at': now,
            },
        },
        upsert=True,
    )


def delete_structure(content_type: str, display_id: int) -> None:
    """Remove the document for (type, display_id)."""
    _col().delete_one({'type': content_type, 'display_id': display_id})


def model_type(instance) -> str:
    """Return the canonical type string for a Content instance."""
    from apps.things.models import Content
    if isinstance(instance, Content):
        return instance.type
    # fallback for legacy callers
    return type(instance).__name__.lower()


def display_id_for(instance) -> int | None:
    """Return the display_id for a Content instance."""
    return getattr(instance, 'display_id', None)
