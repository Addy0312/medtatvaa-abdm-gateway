from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.core.config import settings
from app.core.exceptions import MedtatvaaBaseException
from app.api.v1.health import router as health_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Standalone ABDM Gateway for Medtatvaa MistiqRad and iMagic Neo",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Custom exception handler for Medtatvaa domain errors
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

# Normalize standard Pydantic validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "transaction_id": None,
            "status": "FAILED_FINAL",
            "error_code": "FHIR_VALIDATION_FAILED",
            "message": "Invalid re