from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.ad_tasks import router as ad_tasks_router
from app.api.v1.ad_groups import (router as ad_groups_router)
from app.api.v1.monitor_rules import router as monitor_rules_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router, tags=["auth"])
router.include_router(campaigns_router, tags=["campaigns"])
router.include_router(catalog_router,tags=["catalog"])
router.include_router(ad_tasks_router,tags=["ad-tasks"])
router.include_router(health_router, tags=["health"])
router.include_router(ad_groups_router,tags=["ad-groups"])
router.include_router(monitor_rules_router)
