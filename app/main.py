# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.core.config import settings
from app.core.exceptions import MedtatvaaBaseException

# Import routers
from app.api.v1.health import router as health_router
from app.api.v1.patients import router as patients_router
from app.api.v1.care_contexts import router as care_contexts_router
from app.api.v1.records import router as records_router
from app.api.v1.transactions import router as transactions_router
from app.api.v1.abha import router as abha_router
from app.api.v1.hip_link import router as hip_link_router
from app.api.v0_5.discovery import router as v0_5_discovery_router
from app.api.v0_5.linking import router as v0_5_linking_router
from app.api.v0_5.hip_linking import router as v0_5_hip_linking_router
from app.api.v0_5.consent import router as v0_5_consent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.database import engine, Base
    import app.models.entities
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Standalone ABDM Gateway for Medtatvaa MistiqRad and iMagic Neo",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.exception_handler(MedtatvaaBaseException)
async def medtatvaa_exception_handler(request: Request, exc: MedtatvaaBaseException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "transaction_id": exc.transaction_id,
            "status": "FAILED_FINAL",
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "transaction_id": None,
            "status": "FAILED_FINAL",
            "error_code": "FHIR_VALIDATION_FAILED",
            "message": "Invalid request payload format",
            "details": exc.errors(),
        }
    )


# Register versioned internal API routers
app.include_router(health_router, prefix=settings.API_V1_STR)
app.include_router(abha_router, prefix=settings.API_V1_STR)
app.include_router(patients_router, prefix=settings.API_V1_STR)
app.include_router(care_contexts_router, prefix=settings.API_V1_STR)
app.include_router(hip_link_router, prefix=settings.API_V1_STR)
app.include_router(records_router, prefix=settings.API_V1_STR)
app.include_router(transactions_router, prefix=settings.API_V1_STR)

# ABDM v0.5 Callbacks
app.include_router(v0_5_discovery_router, prefix="/v0.5")
app.include_router(v0_5_linking_router, prefix="/v0.5")
app.include_router(v0_5_hip_linking_router, prefix="/v0.5")
app.include_router(v0_5_consent_router, prefix="/v0.5")


@app.get("/")
async def root():
    return {
        "message": "Medtatvaa ABDM Gateway is running.",
        "docs": "/docs"
    }