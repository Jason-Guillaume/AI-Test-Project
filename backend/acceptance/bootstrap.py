import json, secrets, time
from pathlib import Path
from app.core.database.session import SessionLocal
from app.core.models.identity import User, Organization, OrganizationMember
from app.core.models.project import Project, ProjectMember
from app.core.security.passwords import hash_password
prefix='acceptance_'+str(int(time.time()))
password='E2e!'+secrets.token_hex(12)
with SessionLocal() as db:
    users=[]
    for label,role in [('admin','admin'),('member','test'),('outsider','test')]:
        user=User(username=prefix+'_'+label, role=role, hashed_password=hash_password(password), is_active=True)
        db.add(user); db.flush(); users.append(user)
    admin,member,outsider=users
    org=Organization(name=prefix,owner_id=admin.id);db.add(org);db.flush()
    for user in users:
        db.add(OrganizationMember(organization_id=org.id,user_id=user.id,role='owner' if user==admin else 'member',agent_enabled=True,allowed_model_ids=[]))
    projects=[]
    for label in ['商城','支付']:
        project=Project(name=prefix+'_'+label,owner_id=admin.id,organization_id=org.id);db.add(project);db.flush();projects.append(project)
        db.add(ProjectMember(project_id=project.id,user_id=member.id,role='editor',created_by=admin.id))
    db.add(ProjectMember(project_id=projects[1].id,user_id=outsider.id,role='member',created_by=admin.id))
    db.commit()
    value={'prefix':prefix,'password':password,'users':{label:{'id':u.id,'username':u.username} for label,u in zip(['admin','member','outsider'],users)},'projects':[p.id for p in projects],'organization_id':org.id}
    path=Path('/tmp/knowledge-e2e-state.json');path.write_text(json.dumps(value));path.chmod(0o600)
    print('Acceptance accounts and two projects created:', prefix)
