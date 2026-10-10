from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import db_session, scope
from app.application.pagination import ItemSort, ReviewStatus
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
    sort: ItemSort | str = "relevance",
    review_status: ReviewStatus | None = None,
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    selected=Depends(scope),
    db=db_session,
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
        sort=sort,
        review_status=review_status,
        limit=limit,
        cursor=cursor,
    )
