from fastapi import FastAPI

from src.routers.health import router as health_router

app = FastAPI(title="Emberpath Weight Service")
app.include_router(health_router)
