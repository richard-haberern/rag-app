class AppError(Exception):
    """Base for every error the application raises on purpose.

    Carries the HTTP status it maps to, so a single handler in the API layer can turn
    any subclass into a response by reading `status_code` — no per-type handler needed.
    """

    status_code: int = 500
    default_message: str = "Unexpected application error."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


# --- Client-facing (4xx) ----------------------------------------------------
class RagError(AppError):
    status_code = 400
    default_message = "Bad request."


class DocumentNotFound(RagError):
    status_code = 404
    default_message = "Document wasn't found."


class EmptyDocument(RagError):
    status_code = 422
    default_message = "Document has no usable content."


class DocumentExists(RagError):
    status_code = 409
    default_message = "Document with same content already exists."


class QueryTooLong(RagError):
    status_code = 413
    default_message = "The query length was too long."


# --- Internal invariant violations (5xx) ------------------------------------
class InternalError(AppError):
    status_code = 500
    default_message = "Internal consistency error."


class ChunkNotFound(InternalError):
    default_message = "Chunk wasn't found."

class UserNotFound(InternalError):
    default_message = "User wasn't found."

class VectorNotFound(InternalError):
    default_message = "Vector wasn't found."


# --- Upstream LLM failures (5xx) --------------------------------------------
class LLMError(AppError):
    status_code = 502
    default_message = "The LLM request failed."


class LLMBadAnswer(LLMError):
    default_message = "LLM didn't generate a valid answer."
