from typing import Optional, Any

class MedtatvaaBaseException(Exception):
    def __init__(
        self, 
        error_code: str, 
        message: str, 
        status_code: int = 400, 
        details: Optional[Any] = None,
        transaction_id: Optional[str] = None
    ):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.transaction_id = transaction_id
        super().__init__(self.message)

class AbdmAuthFailedException(MedtatvaaBaseException):
    def __init__(self, message: str = "ABDM authentication or token verification failed", **kwargs):
        super().__init__(error_code="ABDM_AUTH_FAILED", message=message, status_code=401, **kwargs)

class AbhaInvalidException(MedtatvaaBaseException):
    def __init__(self, message: str = "Invalid or unresolvable ABHA address/identifier", **kwargs):
        super().__init__(error_code="ABHA_INVALID", message=message, status_code=404, **kwargs)

class CareContextNotLinkedException(MedtatvaaBaseException):
    def __init__(self, message: str = "Care context is not linked to patient ABHA account", **kwargs):
        super().__init__(error_code="CARE_CONTEXT_NOT_LINKED", message=message, status_code=409, **kwargs)

class FhirValidationFailedException(MedtatvaaBaseException):
    def __init__(self, message: str = "Report payload failed NRCeS FHIR R4 profile validation", **kwargs):
        super().__init__(error_code="FHIR_VALIDATION_FAILED", message=message, status_code=422, **kwargs)

class AbdmUnavailableException(MedtatvaaBaseException):
    def __init__(self, message: str = "ABDM Sandbox service is temporarily unavailable", **kwargs):
        super().__init__(error_code="ABDM_TEMPORARILY_UNAVAILABLE", message=message, status_code=503, **kwargs)

class CallbackValidationFailedException(MedtatvaaBaseException):
    def __init__(self, message: str = "ABDM webhook callback signature or timestamp verification failed", **kwargs):
        super().__init__(error_code="CALLBACK_VALIDATION_FAILED", message=message, status_code=400, **kwargs)