from fastapi import APIRouter
from fastapi import Depends

from typing import Annotated
from pydantic import BaseModel
from uuid import UUID

router = APIRouter()

@router.get("/health")
def get_health_info() -> str:
    return "Everything is running"