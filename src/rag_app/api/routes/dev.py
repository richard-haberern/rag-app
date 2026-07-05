from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def get_health_info() -> str:
    return "Everything is running"
