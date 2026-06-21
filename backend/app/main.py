from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.endpoints import auth, locations, items, search, tasks, admin
from backend.app.services.qdrant import init_qdrant_collections


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Qdrant collection on startup
    await init_qdrant_collections()
    
    # Initialize arq redis pool on startup
    from arq import create_pool
    from backend.app.services.worker import get_redis_settings
    from config import settings
    
    redis_settings = get_redis_settings(settings.REDIS_URL)
    app.state.arq_redis = await create_pool(redis_settings)
    
    yield
    
    await app.state.arq_redis.close()


app = FastAPI(
    title="Инвентаризатор API",
    description="Backend API for the cross-platform AI-assisted inventory system with user tiers and JWT authorization.",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(locations.router, prefix="/inventory", tags=["Locations"])
app.include_router(items.router, prefix="/inventory", tags=["Items"])
app.include_router(search.router, prefix="/inventory", tags=["Search"])
app.include_router(tasks.router, prefix="/inventory", tags=["ML Pipeline"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])


@app.get("/health", tags=["System"], summary="API Service Health Check")
async def health_check():
    """Verify that the API backend is active and running."""
    return {"status": "ok", "service": "inventory-app-api"}

