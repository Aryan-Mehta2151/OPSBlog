from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.deps import get_db, get_current_user
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_refresh_token
from app.db.models import User, Organization, Membership
from app.schemas.auth import SignupRequest, LoginRequest, TokenResponse, RefreshRequest, UserWithOrgResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    email = data.email.lower().strip()
    org_name = data.organization.value  # Enum -> "Google"/"Amazon"/"Meta"

    # 1) Find or create the organization (since you said you don't have orgs yet)
    org = db.query(Organization).filter(Organization.name == org_name).first()
    if not org:
        org = Organization(name=org_name)
        db.add(org)
        db.flush()  # makes org.id available without committing

    # 2) Find or create the user
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password_hash=hash_password(data.password))
        db.add(user)
        db.flush()
    else:
        # If email already exists, treat "signup" as "join org"
        # but only allow it if password matches (prevents random people attaching to org)
        if not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=400, detail="Email already registered")

    # 3) Create membership (link user to org)
    membership = Membership(user_id=user.id, org_id=org.id, role="Admin")
    db.add(membership)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="User already belongs to this organization")

    token = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return TokenResponse(access_token=token, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    email = data.email.lower().strip()
    org_name = data.organization.value

    # 1) Verify user credentials
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # 2) Find org + verify membership
    org = db.query(Organization).filter(Organization.name == org_name).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    member = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id == org.id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")

    token = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return TokenResponse(access_token=token, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(data: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for new access + refresh tokens"""
    try:
        user_id = decode_refresh_token(data.refresh_token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    new_access = create_access_token(user.id)
    new_refresh = create_refresh_token(user.id)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me", response_model=UserWithOrgResponse)
def get_current_user_info(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current authenticated user and their organizations"""
    memberships = db.query(Membership).filter(Membership.user_id == current_user.id).all()
    
    organizations = [
        {
            "id": m.org.id,
            "name": m.org.name,
            "role": m.role,
        }
        for m in memberships
    ]
    
    return UserWithOrgResponse(
        id=current_user.id,
        email=current_user.email,
        organizations=organizations,
    )