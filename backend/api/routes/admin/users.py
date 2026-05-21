"""
Admin API routes for user management.

Provides endpoints to list, view, create, and update users.
All endpoints require `users:write` scope.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

from api.auth_deps import CurrentUser, get_current_user, require_scopes
from db import get_session
from models import Role, User, UserRole
from services.auth import hash_password, validate_password_policy


router = APIRouter(prefix="/admin/users", tags=["admin-users"])


                          

class RoleOut(BaseModel):
    """Role summary for user responses."""
    role_id: str
    name: str
    description: Optional[str] = None


class UserOut(BaseModel):
    """User response for list/detail views."""
    user_id: str
    email: str
    org_id: str
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    roles: List[str]

    class Config:
        from_attributes = True


class UserCreateRequest(BaseModel):
    """Request body for creating a new user."""
    email: EmailStr
    password: str
    org_id: Optional[str] = None
    roles: List[str] = []
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    """Request body for updating an existing user."""
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    roles: Optional[List[str]] = None


class UserCreateResponse(BaseModel):
    """Response after creating a user."""
    user_id: str
    email: str
    org_id: str
    is_active: bool
    roles: List[str]


                          

def _user_to_dict(user: User, roles: List[str]) -> dict:
    """Convert User model to response dict."""
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "org_id": str(user.org_id),
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "roles": roles,
    }


def _load_user_roles(session: Session, user_id: uuid.UUID) -> List[str]:
    """Load role names for a user."""
    roles = session.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id)
    ).scalars().all()
    return sorted(set(roles))


def _sync_user_roles(session: Session, user_id: uuid.UUID, role_names: List[str]) -> List[str]:
    """
    Synchronize user roles to match the provided role_names list.
    Returns the final list of role names.
    """
                             
    all_roles = session.execute(select(Role)).scalars().all()
    role_map = {r.name: r.role_id for r in all_roles}

                                            
    for role_name in role_names:
        if role_name not in role_map:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role '{role_name}' does not exist"
            )

                            
    current_roles = session.execute(
        select(UserRole).where(UserRole.user_id == user_id)
    ).scalars().all()
    current_role_ids = {ur.role_id for ur in current_roles}

                                       
    desired_role_ids = {role_map[name] for name in role_names}
    to_add = desired_role_ids - current_role_ids
    to_remove = current_role_ids - desired_role_ids

                  
    if to_remove:
        session.execute(
            UserRole.__table__.delete().where(
                UserRole.user_id == user_id,
                UserRole.role_id.in_(to_remove)
            )
        )

               
    for role_id in to_add:
        session.add(UserRole(user_id=user_id, role_id=role_id))

    return sorted(role_names)


                   

@router.get("", response_model=List[UserOut])
def list_users(
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[UserOut]:
    """
    List all users.
    
    Returns a list of all users with their roles.
    Restricted to users with `users:write` scope.
    """
    users = session.execute(
        select(User).order_by(User.email)
    ).scalars().all()

    result = []
    for user in users:
        roles = _load_user_roles(session, user.user_id)
        result.append(UserOut(**_user_to_dict(user, roles)))

    return result


@router.get("/roles", response_model=List[RoleOut])
def list_roles(
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[RoleOut]:
    """
    List all available roles.
    
    Returns a list of all roles that can be assigned to users.
    """
    roles = session.execute(
        select(Role).order_by(Role.name)
    ).scalars().all()

    return [
        RoleOut(
            role_id=str(r.role_id),
            name=r.name,
            description=r.description
        )
        for r in roles
    ]


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> UserOut:
    """
    Get a single user by ID.
    
    Returns user details including their assigned roles.
    """
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user_id format"
        )

    user = session.execute(
        select(User).where(User.user_id == user_uuid)
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    roles = _load_user_roles(session, user.user_id)
    return UserOut(**_user_to_dict(user, roles))


@router.post("", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> UserCreateResponse:
    """
    Create a new user.
    
    Creates a user with the specified email, password, and optional roles.
    If org_id is not provided, the new user is added to the same organization
    as the current user.
    """
    normalized_email = payload.email.lower().strip()

                                   
    existing = session.execute(
        select(User).where(User.email == normalized_email)
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists"
        )

                      
    if payload.org_id:
        try:
            org_uuid = uuid.UUID(payload.org_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid org_id format"
            )
    else:
                                                
        org_uuid = current_user.org_id

                 
    try:
        validate_password_policy(payload.password, email=normalized_email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    password_hash = hash_password(payload.password)
    new_user = User(
        email=normalized_email,
        password_hash=password_hash,
        org_id=org_uuid,
        is_active=payload.is_active,
    )
    session.add(new_user)
    session.flush()                   

                  
    final_roles = []
    if payload.roles:
        final_roles = _sync_user_roles(session, new_user.user_id, payload.roles)

    session.commit()

    return UserCreateResponse(
        user_id=str(new_user.user_id),
        email=new_user.email,
        org_id=str(new_user.org_id),
        is_active=new_user.is_active,
        roles=final_roles,
    )


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> UserOut:
    """
    Update an existing user.
    
    Can update email, password, is_active status, and roles.
    Only provided fields are updated.
    """
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user_id format"
        )

    user = session.execute(
        select(User).where(User.user_id == user_uuid)
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

                              
    if payload.email is not None:
        normalized_email = payload.email.lower().strip()
                                   
        existing = session.execute(
            select(User).where(
                User.email == normalized_email,
                User.user_id != user_uuid
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists"
            )
        user.email = normalized_email

                                 
    if payload.password is not None:
        email_for_policy = normalized_email if payload.email is not None else user.email
        try:
            validate_password_policy(payload.password, email=email_for_policy)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        user.password_hash = hash_password(payload.password)

                                  
    if payload.is_active is not None:
        user.is_active = payload.is_active

                              
    if payload.roles is not None:
        _sync_user_roles(session, user.user_id, payload.roles)

    session.add(user)
    session.commit()

    roles = _load_user_roles(session, user.user_id)
    return UserOut(**_user_to_dict(user, roles))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    """
    Delete a user.
    
    Permanently removes a user and their associated data.
    Cannot delete your own account.
    """
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user_id format"
        )

                           
    if user_uuid == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    user = session.execute(
        select(User).where(User.user_id == user_uuid)
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    session.delete(user)
    session.commit()
