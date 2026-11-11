from fastapi import FastAPI
from app.core.config import settings
from app.api.v1.health import router as health_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Standalone ABDM Gateway for Medtatvaa MistiqRad and iMagic Neo",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Register routes
app.include_router(health_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {
        "message": "Medtatvaa ABDM Gateway is running.",
        "docs": "/docs"
    }