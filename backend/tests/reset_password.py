"""Quick script to reset the aryan@gmail.com password so we can test the API."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import SessionLocal
from app.db.models import User
from app.core.security import hash_password

db = SessionLocal()
u = db.query(User).filter(User.email == "aryan@gmail.com").first()
if u:
    u.password_hash = hash_password("password123")
    db.commit()
    print(f"Password reset for {u.email}")
else:
    print("User not found")
db.close()
