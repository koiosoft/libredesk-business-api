"""PostgreSQL access and the conversation-cleanup domain.

Two non-negotiable rules inherited from the original design:
  - Dry-run by default. Executing requires explicit confirmation.
  - One UUID per request. There is no bulk-sweep route at all.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings

# conversations cascades into these tables (verified against schema.sql and the live
# instance). Reported in dry-run so the operator can inspect blast radius first.
CASCADE_TABLES = [
    "conversation_messages",
    "conversation_drafts",
    "conversation_participants",
    "conversation_mentions",
    "conversation_last_seen",
    "conversation_tags",
    "csat_responses",
    "applied_slas",
    "ai_agent_events",
    "copilot_messages",
    "ai_faq_suggestions",
    "user_notifications",
    "notification_email_queue",
]

SQL_FETCH_CONVERSATION = """
SELECT c.id, c.uuid, c.reference_number, c.subject, c.status_id,
       c.contact_id, c.assigned_user_id, c.assigned_team_id, c.inbox_id,
       c.created_at, c.updated_at,
       i.name AS inbox_name, i.channel AS inbox_channel,
       u.first_name || COALESCE(' ' || u.last_name, '') AS contact_name,
       u.type AS contact_type, u.email AS contact_email,
       u.phone_number AS contact_phone
FROM conversations c
LEFT JOIN inboxes i ON i.id = c.inbox_id
LEFT JOIN users u   ON u.id = c.contact_id
WHERE c.uuid = %s
"""

SQL_COUNT_ATTACHMENTS = """
SELECT count(*) AS n, COALESCE(sum(size), 0) AS bytes
FROM media
WHERE model_type = 'messages'
  AND model_id IN (SELECT id FROM conversation_messages WHERE conversation_id = %s)
"""

SQL_COUNT_OTHER_CONV = """
SELECT count(*) AS n FROM conversations
WHERE contact_id = %s AND uuid <> %s
"""


@contextmanager
def db() -> Iterator[psycopg.Connection]:
    s = get_settings()
    conn = psycopg.connect(
        host=s.db_host,
        port=s.db_port,
        dbname=s.db_name,
        user=s.db_user,
        password=s.db_password,
        row_factory=psycopg.rows.dict_row,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


class CleanupResult(BaseModel):
    deleted: bool
    conversation_uuid: str
    reference_number: str | None = None
    affected_rows: dict[str, int] = Field(default_factory=dict)
    contact_deleted: bool = False
    note_media: str = ""


def inspect(cur, uuid: str) -> dict[str, Any] | None:
    cur.execute(SQL_FETCH_CONVERSATION, (uuid,))
    conv = cur.fetchone()
    if not conv:
        return None

    counts: dict[str, int] = {}
    for table in CASCADE_TABLES:
        cur.execute(
            f'SELECT count(*) AS n FROM "{table}" WHERE conversation_id = %s',
            (conv["id"],),
        )
        row = cur.fetchone()
        counts[table] = row["n"] if row else 0

    # Attachments: media is polymorphic and has NO foreign key to conversations, so it
    # survives the cascade. LibreDesk already sweeps those rows every 12 hours
    # (internal/media/media.go), deleting the file and thumbnail too. We only report them.
    cur.execute(SQL_COUNT_ATTACHMENTS, (conv["id"],))
    m = cur.fetchone()
    attachments = {"rows": m["n"], "bytes": int(m["bytes"])}

    # Deleting the contact when it still owns other conversations would destroy real
    # history, so the remaining count is surfaced for the operator to decide.
    cur.execute(SQL_COUNT_OTHER_CONV, (conv["contact_id"], uuid))
    other_convs = cur.fetchone()["n"]

    conv["cascade_counts"] = counts
    conv["attachments"] = attachments
    conv["other_conversations_for_contact"] = other_convs
    return conv


def execute_cleanup(uuid: str, also_contact: bool) -> CleanupResult:
    with db() as conn, conn.cursor() as cur:
        conv = inspect(cur, uuid)
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")

        contact_id = conv["contact_id"]
        affected = dict(conv["cascade_counts"])
        affected["media_orphans_expected"] = conv["attachments"]["rows"]

        cur.execute("DELETE FROM conversations WHERE uuid = %s", (uuid,))
        affected["conversations"] = cur.rowcount

        contact_deleted = False
        if also_contact and contact_id:
            cur.execute(
                "SELECT count(*) AS n FROM conversations WHERE contact_id = %s",
                (contact_id,),
            )
            if cur.fetchone()["n"] == 0:
                cur.execute(
                    "DELETE FROM users WHERE id = %s AND type IN ('contact','visitor')",
                    (contact_id,),
                )
                contact_deleted = cur.rowcount > 0

        conn.commit()

    return CleanupResult(
        deleted=True,
        conversation_uuid=uuid,
        reference_number=conv["reference_number"],
        affected_rows=affected,
        contact_deleted=contact_deleted,
        note_media=(
            "Media rows are now orphaned; LibreDesk's internal job (every 12h) removes "
            "them together with their files and thumbnails."
        ),
    )
