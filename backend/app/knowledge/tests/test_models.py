from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import app.core.models
from app.core.database.base import Base
from app.core.models.identity import User, Organization, OrganizationMember
from app.core.models.project import Project, ProjectMember
from app.platform.model_configuration.models import ModelResource, ModelRevision
from app.platform.model_configuration.services.model_center_service import list_available_models
from app.platform.model_configuration.services.model_config_service import load_model_for_provider
from app.core.models.configuration import ModelConfiguration


def test_member_needs_no_grant_and_disabled_provider_rejected():
    engine = create_engine('sqlite://')
    names = {'user', 'organization', 'organization_member', 'project', 'project_member', 'model_configuration',
             'model_resource', 'model_revision', 'model_parameter_profile', 'model_default_binding', 'model_resource_grant'}
    # Resolve optional ASR FK tables without creating unrelated domain tables.
    from app.features.asr_evaluation import models
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if t.name in names])
    with Session(engine) as db:
        actor = User(id=2, username='member', role='test')
        db.add_all([User(id=1, username='owner'), actor, Organization(id=1, name='org', owner_id=1), OrganizationMember(organization_id=1, user_id=2, role='member', agent_enabled=True, allowed_model_ids=[]), Project(id=1, name='project', owner_id=1, organization_id=1), ProjectMember(project_id=1, user_id=2, role='member', created_by=1)])
        model = ModelConfiguration(id=1, domain_id='global', label='global', api_base='http://example.test', model_name='test', is_enabled=True)
        db.add(model)
        db.add(ModelResource(id=1, resource_key='global', category='TEXT_GENERATION', visibility='PLATFORM', display_name='global', status='DISABLED', legacy_model_id=1))
        db.commit()
        resource = db.get(ModelResource, 1)
        resource.status = 'ACTIVE'
        revision = ModelRevision(id=1, resource_id=1, version=1, provider='custom', adapter_key='openai-compatible-chat', model_name='test', enabled=True)
        db.add(revision); resource.current_revision_id = 1; db.commit()
        assert list_available_models(db, project_id=1, category=None, actor=actor)['items'][0]['id'] == 1
        assert load_model_for_provider(db, 1) is not None
        from app.orchestration.tasks.services.assembly_service import resolve_authorized_model
        assert resolve_authorized_model(db, 1, actor, requested_model_id=1).id == 1
        resource.status = 'DISABLED'; db.commit()
        assert list_available_models(db, project_id=1, category=None, actor=actor)['items'] == []
        assert load_model_for_provider(db, 1) is None
