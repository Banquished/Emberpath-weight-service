from fastapi import FastAPI

from src.routers.health import router as health_router
from src.routers.weight_logs import router as weight_logs_router

app = FastAPI(title="Emberpath Weight Service")
app.include_router(health_router)
app.include_router(weight_logs_router)
