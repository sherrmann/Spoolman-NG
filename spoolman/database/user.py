"""Database helpers for optional user accounts (issue #52)."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.database import models
from spoolman.exceptions import ItemNotFoundError
from spoolman.users import ROLE_ADMIN


async def create(db: AsyncSession, *, username: str, password_hash: str, role: str) -> models.User:
    """Add a new user account."""
    user = models.User(
        username=username,
        password_hash=password_hash,
        role=role,
        registered=datetime.utcnow().replace(microsecond=0),
    )
    db.add(user)
    await db.commit()
    return user


async def get_by_id(db: AsyncSession, user_id: int) -> models.User:
    """Get a user by ID, or raise ItemNotFoundError."""
    user = await db.get(models.User, user_id)
    if user is None:
        raise ItemNotFoundError(f"No user with ID {user_id} found.")
    return user


async def get_by_username(db: AsyncSession, username: str) -> models.User | None:
    """Get a user by username, or None."""
    return (await db.execute(select(models.User).where(models.User.username == username))).scalar_one_or_none()


async def list_all(db: AsyncSession) -> list[models.User]:
    """Return all users, ordered by id."""
    return list((await db.execute(select(models.User).order_by(models.User.id))).scalars().all())


async def count(db: AsyncSession) -> int:
    """Return the total number of users."""
    return int((await db.execute(select(func.count(models.User.id)))).scalar_one())


async def count_admins(db: AsyncSession) -> int:
    """Return the number of admin users (used to prevent removing the last admin)."""
    stmt = select(func.count(models.User.id)).where(models.User.role == ROLE_ADMIN)
    return int((await db.execute(stmt)).scalar_one())


async def update(
    db: AsyncSession,
    user_id: int,
    *,
    password_hash: str | None = None,
    role: str | None = None,
) -> models.User:
    """Update a user's password and/or role."""
    user = await get_by_id(db, user_id)
    if password_hash is not None:
        user.password_hash = password_hash
    if role is not None:
        user.role = role
    await db.commit()
    return user


async def delete(db: AsyncSession, user_id: int) -> None:
    """Delete a user."""
    user = await get_by_id(db, user_id)
    await db.delete(user)
    await db.commit()


async def touch_last_login(db: AsyncSession, user: models.User) -> None:
    """Record a successful login timestamp."""
    user.last_login = datetime.utcnow().replace(microsecond=0)
    await db.commit()
