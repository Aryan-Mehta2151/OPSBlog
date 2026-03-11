from app.db.session import SessionLocal
from app.db.models import User, Organization, Membership

db = SessionLocal()
users = db.query(User).all()
print('Users:')
for user in users:
    memberships = db.query(Membership).filter(Membership.user_id == user.id).all()
    org_names = [m.org.name for m in memberships]
    print(f'  {user.email} - Orgs: {", ".join(org_names) if org_names else "No orgs"}')

orgs = db.query(Organization).all()
print('Organizations:')
for org in orgs:
    print(f'  {org.name}')

db.close()