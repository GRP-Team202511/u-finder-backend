import asyncio
from src.utils import hash_password
from src.database import get_db, Account
from sqlalchemy import select

async def create_test_user():
    # Generate password hash for "test123"
    password_hash = hash_password("test123")
    print(f"Password hash: {password_hash}")
    
    #Create database connection
    async for db in get_db():
        # Check if user exists
        result = await db.execute(
            select(Account).where(Account.email == "test@example.com")
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            print(f"✅ User already exists: {existing.name} ({existing.email})")
            print(f"   User ID: {existing.user_id}")
            return
        
        # Create new user
        test_user = Account(
            name="Test User",
            email="test@example.com",
            password_hashed=password_hash,
            user_type=1,
            is_2fa_enabled=False,
            passkey_enabled=False,
            is_blocked=False
        )
        
        db.add(test_user)
        await db.commit()
        await db.refresh(test_user)
        
        print(f"✅ Test user created successfully!")
        print(f"   Name: {test_user.name}")
        print(f"   Email: {test_user.email}")
        print(f"   Password: test123")
        print(f"   User ID: {test_user.user_id}")
        break

if __name__ == "__main__":
    asyncio.run(create_test_user())
