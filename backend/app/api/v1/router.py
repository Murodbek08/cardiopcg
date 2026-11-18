from fastapi import APIRouter

from app.api.v1 import (
    admin_drugs,
    analysis,
    analytics,
    auth,
    conclusions,
    examinations,
    exports,
    notifications,
    patients,
    prescriptions,
    recordings,
    system,
    users,
    ws,
)

api_router = APIRouter(prefix="/api/v1")
for r in (
    auth.router,
    admin_drugs.router,
    users.router,
    patients.router,
    examinations.router,
    recordings.router,
    analysis.router,
    prescriptions.router,
    conclusions.router,
    notifications.router,
    system.router,
    analytics.router,
    exports.router,
    ws.router,
):
    api_router.include_router(r)
