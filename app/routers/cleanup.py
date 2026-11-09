"""Conversation cleanup routes (control plane, direct database access).

Used ONLY where the official LibreDesk API cannot reach. Deleting conversations is one
of those cases: there is no DELETE /api/v1/conversations/{uuid}. Anything the API does
expose (notes, tags, assignment, status, custom attributes) must go through that client
instead, because it keeps caches, widget broadcasts and webhook coherence intact.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.db import CleanupResult, db, execute_cleanup, inspect
from app.core.security import require_api_key

log = logging.getLogger("hub-api.cleanup")

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

router = APIRouter(prefix="/conversations", tags=["cleanup"])


def _check_uuid(uuid: str) -> None:
    if not UUID_RE.match(uuid):
        raise HTTPException(status_code=400, detail="invalid uuid")


@router.get("/{uuid}")
def read_conversation(
    uuid: str,
    request: Request,
    caller: str = Depends(require_api_key),
):
    """Side-effect-free inspection: what would be deleted and how heavy it is."""
    _check_uuid(uuid)
    with db() as conn, conn.cursor() as cur:
        conv = inspect(cur, uuid)
    if not conv:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"mode": "READ", "conversation": conv}


@router.delete("/{uuid}")
def delete_conversation(
    uuid: str,
    request: Request,
    execute: bool = Query(False, description="false = dry-run (default)"),
    contact: bool = Query(False, description="also delete the contact if left orphaned"),
    caller: str = Depends(require_api_key),
):
    """Delete ONE conversation by UUID. Dry-run unless `execute=true`.

    Intended flow: call without `execute`, review `cascade_counts`, then repeat with
    `execute=true` only when the blast radius matches expectations.
    """
    _check_uuid(uuid)

    if not execute:
        with db() as conn, conn.cursor() as cur:
            conv = inspect(cur, uuid)
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")
        log.info("DRY-RUN uuid=%s caller=%s contact=%s", uuid, caller, contact)
        return {
            "mode": "DRY-RUN",
            "message": "Nothing was modified. Repeat with execute=true.",
            "conversation": conv,
            "contact_requested": contact,
        }

    result = execute_cleanup(uuid, contact)
    log.info(
        "EXECUTED delete uuid=%s caller=%s contact=%s summary=%s",
        uuid, caller, contact, result.affected_rows,
    )
    return {"mode": "EXECUTED", **result.model_dump()}
