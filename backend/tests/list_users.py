"""Find valid user credentials for API testing."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models import User, Membership, Organization

db = SessionLocal()
users = db.query(User).all()
for u in users:
    m = db.query(Membership).filter(Membership.user_id == u.id).first()
    org = db.query(Organization).filter(Organization.id == m.org_id).first() if m else None
    org_name = org.name if org else "None"
    role = m.role if m else "None"
    org_id = m.org_id if m else "None"
    print(f"User: {u.email} | Org: {org_name} | Role: {role} | OrgId: {org_id}")
db.close()
