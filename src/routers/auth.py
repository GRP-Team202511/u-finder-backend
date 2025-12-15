"""
Authentication router module
Contains authentication related endpoints such as user login
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.database.models import Account
from src.schemas.auth import (
    LoginRequest, 
    LoginResponse, 
    ErrorResponse
)
from src.utils.password_utils import verify_password
from src.utils.jwt_utils import create_access_token
from src.config.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

# Create authentication router
router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="User Login",
    responses={
        200: {"description": "Login successful", "model": LoginResponse},
        401: {"description": "Incorrect password", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse}
    }
)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    User login endpoint
    
    - **email**: User email address (required)
    - **password**: User password (required)
    """
    try:
        logger.info(f"Login attempt for email: {login_data.email}")
        
        # Query user by email
        result = await db.execute(
            select(Account).where(Account.email == login_data.email)
        )
        user = result.scalar_one_or_none()
        
        # Check if user exists
        if not user:
            logger.warning(f"User not found: {login_data.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Verify password
        if not verify_password(login_data.password, user.password):
            logger.warning(f"Incorrect password for user: {login_data.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect Password"
            )
        
        # Create access token
        access_token = create_access_token(
            data={"sub": str(user.user_id), "email": user.email}
        )
        
        logger.info(f"Login successful for user: {login_data.email}")
        
        return LoginResponse(
            id=user.user_id,
            name=user.user_name or '',
            token=access_token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
