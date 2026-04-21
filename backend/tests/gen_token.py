"""Generate an auth token directly for testing."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.db.models import User

db = SessionLocal()
user = db.query(User).filter(User.email == "aryan@gmail.com").first()
if user:
    token = create_access_token(user.id)
    print(f"TOKEN={token}")
else:
    print("User not found")
db.close()
