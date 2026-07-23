"""Login and user-account management endpoints for optional accounts (#52).

The static #48 machine token keeps working unchanged; this adds password login on top. All routes
are additive under /api/v1/auth. Account management requires an admin principal — which, before any
account exists, is the anonymous default, so the very first admin can bootstrap itself.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spoolman.auth import TOKEN_TTL_SECONDS, Principal, auth_state, get_signing_secret, refresh_user_roles
from spoolman.database import user as user_db
from spoolman.database.database import get_db_session
from spoolman.users import ROLE_ADMIN, ROLES, hash_password, mint_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# ruff: noqa: D103


class AuthStatus(BaseModel):
    auth_required: bool = Field(description="Whether requests must be authenticated.")
    accounts_enabled: bool = Field(description="Whether one or more user accounts exist.")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — the OAuth token type, not a secret
    username: str
    role: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)
    role: str = Field(default=ROLE_ADMIN, description="admin or readonly.")


class UpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=1)
    role: str | None = Field(default=None)


def _principal(request: Request) -> Principal:
    """Return the caller's principal, defaulting to anonymous admin when the middleware isn't active."""
    return getattr(request.state, "principal", None) or Principal(name="anonymous")


def current_principal(request: Request) -> Principal:
    """Dependency: the caller's principal (the anonymous admin when auth is not configured)."""
    return _principal(request)


def require_admin(request: Request) -> Principal:
    """Dependency: allow only an admin principal (the default when no accounts exist yet)."""
    principal = _principal(request)
    if principal.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return principal


def _to_response(user: object) -> UserResponse:
    return UserResponse(id=user.id, username=user.username, role=user.role)


@router.get("/status", name="Auth status")
async def status() -> AuthStatus:
    return AuthStatus(auth_required=auth_state.auth_required(), accounts_enabled=auth_state.accounts_enabled)


@router.get("/me", name="Current user")
async def me(request: Request) -> UserResponse:
    principal = _principal(request)
    return UserResponse(id=0, username=principal.name, role=principal.role)


@router.post("/login", name="Log in")
async def login(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: LoginRequest,
) -> LoginResponse:
    user = await user_db.get_by_username(db, body.username)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    await user_db.touch_last_login(db, user)
    token = mint_token(user.username, user.role, get_signing_secret(), ttl_seconds=TOKEN_TTL_SECONDS)
    return LoginResponse(access_token=token, username=user.username, role=user.role)


@router.get("/users", name="List users")
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[Principal, Depends(require_admin)],
) -> list[UserResponse]:
    return [_to_response(u) for u in await user_db.list_all(db)]


@router.post("/users", name="Create user")
async def create_user(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: CreateUserRequest,
    _admin: Annotated[Principal, Depends(require_admin)],
) -> UserResponse:
    role = body.role if body.role in ROLES else ROLE_ADMIN
    # The very first account is always an admin, so a system can never be left with no way in.
    if await user_db.count(db) == 0:
        role = ROLE_ADMIN
    try:
        user = await user_db.create(db, username=body.username, password_hash=hash_password(body.password), role=role)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"A user named '{body.username}' already exists.") from exc
    await refresh_user_roles(db)
    return _to_response(user)


@router.put("/users/{user_id}", name="Update user")
async def update_user(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user_id: int,
    body: UpdateUserRequest,
    _admin: Annotated[Principal, Depends(require_admin)],
) -> UserResponse:
    role = body.role
    if role is not None and role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role '{role}'.")
    # Don't let the last admin demote themselves out of administration.
    if role is not None and role != ROLE_ADMIN:
        target = await user_db.get_by_id(db, user_id)
        if target.role == ROLE_ADMIN and await user_db.count_admins(db) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last administrator.")
    password_hash = hash_password(body.password) if body.password is not None else None
    user = await user_db.update(db, user_id, password_hash=password_hash, role=role)
    await refresh_user_roles(db)
    return _to_response(user)


@router.delete("/users/{user_id}", name="Delete user")
async def delete_user(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user_id: int,
    _admin: Annotated[Principal, Depends(require_admin)],
) -> None:
    target = await user_db.get_by_id(db, user_id)
    if target.role == ROLE_ADMIN and await user_db.count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last administrator.")
    await user_db.delete(db, user_id)
    await refresh_user_roles(db)
