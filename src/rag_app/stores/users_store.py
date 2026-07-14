from sqlalchemy.ext.asyncio import AsyncSession
from rag_app.schemas import UserDTO
from rag_app.models.user import User
from sqlalchemy import select, delete
from uuid import UUID
from rag_app.exceptions import UserNotFound

class UserStore:
    async def add_user(self, session: AsyncSession, id: UUID) -> None:
        # created_at is filled by the DB (server_default=now()); passing it would override it.
        session.add(User(id=id))

    async def get_user(self, session: AsyncSession, id: UUID) -> UserDTO:
        res = await session.execute(select(User).where(User.id == id))
        user = res.scalar_one_or_none()
        if user is None:
            raise UserNotFound(f"User with id: {id} doesn't exist.")
        return UserDTO(id=user.id, created_at=user.created_at)

    async def remove_user(self, session: AsyncSession, id: UUID) -> None:
        await session.execute(delete(User).where(User.id == id))