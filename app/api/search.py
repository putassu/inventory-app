from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import database, scope
from app.application.search import search

router = APIRouter()


@router.get("/search")
async def search_items(
    request: Request,
    query: str = Query("", max_length=2000),
    category: str | None = None,
    location_id: UUID | None = None,
    availability: str | None = None,
    expired: bool = False,
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=Depends(database),
):
    await db.commit()
    return await search(
        request.app.state.session_factory,
        selected.workspace_id,
        query,
        category=category,
        location_id=str(location_id) if location_id else None,
        availability=availability,
        expired=expired,
        limit=limit,
        cursor=cursor,
    )
