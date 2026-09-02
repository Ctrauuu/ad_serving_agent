from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.catalog import router as catalog_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router, tags=["auth"])
router.include_router(campaigns_router, tags=["campaigns"])
router.include_router(catalog_router,tags=["catalog"])
router.include_router(health_router, tags=["health"])
