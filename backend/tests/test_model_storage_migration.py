"""PostgreSQL contracts shared by model-center and legacy model consumers."""

from alembic import command
from sqlalchemy import text

from tests.conftest import TEST_DSN


def test_legacy_text_write_has_one_authoritative_revision(test_database):
    from sqlalchemy import create_engine

    engine = create_engine(TEST_DSN)
    try:
        with engine.connect() as db, db.begin():
            public_id = db.execute(text("""
                INSERT INTO model_configuration (domain_id, label, api_base, model_name, api_key_encrypted)
                VALUES ('b2-public-text', 'original', 'https://example.test/v1', 'before', 'cipher-v1')
                RETURNING id
            """)).scalar_one()
            db.execute(text("""
                UPDATE model_configuration SET model_name='after', api_key_encrypted='cipher-v2',
                    cost_per_1k_input=1.25, sort_order=15 WHERE id=:id
            """), {"id": public_id})
            revisions = db.execute(text("""
                SELECT v.model_name, c.ciphertext
                FROM model_resource r JOIN model_revision v ON v.resource_id=r.id
                JOIN model_credential c ON c.revision_id=v.id
                WHERE r.legacy_model_id=:id ORDER BY v.version
            """), {"id": public_id}).all()
            assert revisions == [('before', 'cipher-v1'), ('after', 'cipher-v2')]
            row = db.execute(text("""
                SELECT id, model_name, cost_per_1k_input, sort_order FROM model_configuration WHERE id=:id
            """), {"id": public_id}).one()
            assert tuple(row) == (public_id, 'after', 1.25, 15)
            db.execute(text("UPDATE model_configuration SET cost_per_1k_input=2.0 WHERE id=:id"), {"id": public_id})
            assert db.execute(text("""
                SELECT v.text_cost_input FROM model_revision v JOIN model_resource r ON r.id=v.resource_id
                WHERE r.legacy_model_id=:id ORDER BY v.version
            """), {"id": public_id}).scalars().all() == [0, 1.25, 2.0]
            db.execute(text("UPDATE model_configuration SET deleted_at=now() WHERE id=:id"), {"id": public_id})
            db.execute(text("UPDATE model_configuration SET deleted_at=NULL WHERE id=:id"), {"id": public_id})
            # Recycle-bin restoration allows the separate model-center restore / enable controls to proceed.
            assert db.execute(text("SELECT status FROM model_resource WHERE legacy_model_id=:id"),
                              {"id": public_id}).scalar_one() == "ARCHIVED"
            db.rollback()
    finally:
        engine.dispose()


def test_center_creates_one_revision_and_project_aliases(test_database):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.models.identity import User
    from app.core.models.project import Project
    from app.core.models.configuration import ModelConfiguration
    from app.platform.model_configuration.models import ModelCredential, ModelResource, ModelRevision
    from app.platform.model_configuration.services.model_center_service import create_resource, resolve_task_slots
    from app.platform.model_configuration.services.model_config_service import decrypt_api_key
    from app.platform.model_configuration.tests.test_model_center import _asr_resource, _text_resource
    from types import SimpleNamespace

    engine = create_engine(TEST_DSN)
    try:
        with engine.connect() as connection, connection.begin(), Session(connection) as db:
            admin = User(username="b2-model-admin", role="admin")
            db.add(admin)
            db.flush()
            projects = [Project(name=f"b2-model-scope-{i}", owner_id=admin.id) for i in (1,2)]
            db.add_all(projects)
            db.flush()
            text_body = _text_resource().model_copy(update={"credential": "b2-example-api-key"})
            result = create_resource(db, text_body, admin, commit=False)
            resource = db.get(ModelResource, result["id"])
            assert db.query(ModelRevision).filter_by(resource_id=resource.id).count() == 1
            config = db.get(ModelConfiguration, resource.legacy_model_id)
            assert decrypt_api_key(config.api_key_encrypted) == "b2-example-api-key"
            version = create_resource(db, _asr_resource([p.id for p in projects]), admin, commit=False)
            rev = version["current_revision"]
            selection = SimpleNamespace(slot="TEST", resource_id=version["id"], revision_id=rev["id"],
                                        profile_id=rev["profiles"][0]["id"])
            aliases = [resolve_task_slots(db, project.id, [selection], admin)[0] for project in projects]
            assert aliases[0]["connection"].id != aliases[1]["connection"].id
            assert aliases[0]["parameter_set"].id != aliases[1]["parameter_set"].id
            assert [a["connection"].project_id for a in aliases] == [p.id for p in projects]
            assert db.query(ModelRevision).filter_by(resource_id=version["id"]).count() == 1
            assert db.query(ModelCredential).filter(ModelCredential.alias_binding_id.is_not(None)).count() == 0

            # A project-specific parameter set may already occupy the native profile's display name/version.
            from app.platform.model_configuration.center_schemas import ModelProfileCreate
            from app.platform.model_configuration.services.model_center_service import create_profile

            local = db.execute(text("""
                INSERT INTO asr_parameter_set(project_id,connection_id,name,parameters)
                VALUES (:p,:c,'regional','{"language":"local"}') RETURNING id
            """), {"p": projects[0].id, "c": aliases[0]["connection"].id}).scalar_one()
            global_profile = create_profile(db, version["id"], ModelProfileCreate(
                revision_id=rev["id"], name="regional", values={"language":"global"}), admin)
            selection.profile_id = global_profile["id"]
            selected = resolve_task_slots(db, projects[0].id, [selection], admin)[0]["parameter_set"]
            assert selected.id != local and selected.parameters == {"language": "global"}
            db.rollback()
    finally:
        engine.dispose()


def test_populated_model_center_preserves_project_credentials_history_and_downgrade(isolated_migration_database):
    import pytest
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    from app.core.models.configuration import ModelConfiguration
    from app.platform.model_configuration.services.model_config_service import model_configuration_revision

    cfg, engine = isolated_migration_database
    command.downgrade(cfg, "0105")
    with engine.begin() as con:
        def add(statement, **params):
            return con.execute(text(statement + " RETURNING id"), params).scalar_one()

        user = add('INSERT INTO "user"(username) VALUES (\'b2-migration-owner\')')
        projects = [add("INSERT INTO project(name,owner_id) VALUES (:name,:owner)", name=f"b2-project-{i}", owner=user)
                    for i in (1, 2)]
        model = add("""
            INSERT INTO model_configuration(domain_id,label,api_base,model_name,api_key_encrypted,is_default,
                cost_per_1k_output,temperature,max_tokens,timeout,updated_at)
            VALUES('b2-domain','Public text','https://text.invalid/v1','second','historic-text-bytes',true,
                2.5,0.75,123,120,'2021-01-02 12:34:56.123456')
        """)
        text_resource = add("""
            INSERT INTO model_resource(resource_key,category,display_name,legacy_model_id)
            VALUES('b2-domain','TEXT_GENERATION','Public text',:id)
        """, id=model)
        revisions = [add("""
            INSERT INTO model_revision(resource_id,version,provider,adapter_key,model_name,endpoint_display,enabled)
            VALUES(:r,:v,'openai-compatible','openai-compatible-chat',:n,'https://text.invalid/v1',:enabled)
        """, r=text_resource, v=v, n=n, enabled=e) for v,n,e in [(1,'first',False),(2,'second',True)]]
        con.execute(text("UPDATE model_resource SET current_revision_id=:v WHERE id=:r"), {"v":revisions[1],"r":text_resource})
        con.execute(text("""
            INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,legacy_domain_id)
            VALUES('MODEL_CONFIGURATION',:id,:r,:v,'b2-domain')
        """), {"id":model,"r":text_resource,"v":revisions[0]})
        con.execute(text("""
            INSERT INTO model_credential(revision_id,ciphertext,cipher_format)
            VALUES(:v,'canonical-format-bytes','shared-fernet')
        """), {"v":revisions[1]})

        asr_resource = add("INSERT INTO model_resource(resource_key,category,display_name) VALUES ('b2-shared','ASR','Shared')")
        version = add("""
            INSERT INTO model_revision(resource_id,version,provider,adapter_key,model_name,endpoint_ciphertext,endpoint_display)
            VALUES(:r,1,'example','generic-json-http','speech','endpoint-v1','https://speech.invalid/transcribe')
        """,r=asr_resource)
        con.execute(text("UPDATE model_resource SET current_revision_id=:v WHERE id=:r"),{"v":version,"r":asr_resource})
        con.execute(text("INSERT INTO model_credential(revision_id,ciphertext) VALUES (:v,'credential-a')"),{"v":version})
        profiles = [add("""
            INSERT INTO model_parameter_profile(resource_id,revision_id,name,version,parameter_values)
            VALUES(:r,:v,'dialect',:n,json_build_object('level',CAST(:n AS int)))
        """,r=asr_resource,v=version,n=n) for n in (1,2)]
        connection_ids, parameters = [], []
        for i, project in enumerate(projects):
            connection = add("""
                INSERT INTO asr_connection(project_id,name,role,task_type,provider_id,model_id,endpoint_ciphertext,
                    endpoint_display,config_json,secret_ciphertext,secret_header)
                VALUES(:p,:name,'TEST','TRANSCRIPTION','example','speech','endpoint-v1',
                    'https://speech.invalid/transcribe','{}',:key,'X-Api-Key')
            """,p=project,name=f"project {i} alias",key='credential-a' if i == 0 else None)
            connection_ids.append(connection)
            con.execute(text("""
                INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id)
                VALUES('ASR_SHARED_CONNECTION',:id,:r,:v)
            """),{"id":connection,"r":asr_resource,"v":version})
            for number in (1,2):
                param = add("""
                    INSERT INTO asr_parameter_set(project_id,connection_id,name,version,parameters)
                    VALUES(:p,:c,'dialect',:n,json_build_object('level',CAST(:n AS int)))
                """,p=project,c=connection,n=number)
                parameters.append(param)
                con.execute(text("""
                    INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id)
                    VALUES('ASR_SHARED_PARAMETER_SET',:id,:r,:v)
                """),{"id":param,"r":asr_resource,"v":version})
        schedule = add("""
            INSERT INTO asr_schedule(project_id,name,audio_ids,connection_ids,parameter_set_id,schedule_type,local_time)
            VALUES(:p,'pinned','[]',json_build_array(CAST(:c AS integer)),:s,'DAILY','08:00')
        """,p=projects[1],c=connection_ids[1],s=parameters[-1])
        with Session(con) as db:
            original = db.get(ModelConfiguration,model)
            fingerprint = model_configuration_revision(original)
            timestamp = original.updated_at.isoformat()

    command.upgrade(cfg, "0106")
    with engine.begin() as con:
        with Session(con) as db:
            migrated = db.get(ModelConfiguration,model)
            assert model_configuration_revision(migrated) == fingerprint
            assert migrated.updated_at.isoformat() == timestamp
            assert migrated.timeout == 120
        assert con.execute(text("SELECT config_json FROM model_revision WHERE id=:id"),
                           {"id": revisions[1]}).scalar_one() == {}
        scoped = con.execute(text("""
            SELECT project_id,legacy_id,profile_id FROM model_legacy_binding
            WHERE parameter_public_id IS NOT NULL ORDER BY legacy_id
        """)).all()
        assert [r.profile_id for r in scoped] == profiles * 2
        assert [r.project_id for r in scoped] == [projects[0], projects[0], projects[1], projects[1]]
        assert con.execute(text("SELECT secret_ciphertext FROM asr_connection ORDER BY id")).scalars().all() == [
            "credential-a", None]
        with pytest.raises(IntegrityError), con.begin_nested():
            con.execute(text("DELETE FROM asr_parameter_set WHERE id=:id"),{"id":parameters[-1]})
        local_parameter = con.execute(text("""
            INSERT INTO asr_parameter_set(project_id,connection_id,name,parameters)
            VALUES(:p,:c,'local-only','{"private":"project-a"}') RETURNING id
        """), {"p":projects[0], "c":connection_ids[0]}).scalar_one()
        local_profile = con.execute(text("SELECT profile_id FROM model_legacy_binding WHERE parameter_public_id=:id"),
                                    {"id":local_parameter}).scalar_one()
        con.execute(text("UPDATE asr_connection SET secret_ciphertext='project-b-key' WHERE id=:id"),
                    {"id":connection_ids[1]})
        con.execute(text("UPDATE model_configuration SET model_name='third',updated_at='2024-04-05' WHERE id=:id"),
                    {"id":model})
    command.downgrade(cfg,"0105")
    with engine.begin() as con:
        # An old process lists every profile on each active platform resource without checking scope_connection_id.
        assert con.execute(text("""
            SELECT count(*) FROM model_parameter_profile p JOIN model_resource r ON r.id=p.resource_id
            WHERE p.id=:p AND r.visibility='PLATFORM'
        """), {"p":local_profile}).scalar_one() == 0
        assert con.execute(text("SELECT parameters FROM asr_parameter_set WHERE id=:id AND project_id=:p"),
                           {"id":local_parameter,"p":projects[0]}).scalar_one() == {"private":"project-a"}
        assert con.execute(text("SELECT secret_ciphertext FROM asr_connection ORDER BY id")).scalars().all() == [
            "credential-a","project-b-key"]
        assert con.execute(text("SELECT model_name FROM model_configuration WHERE id=:id"),{"id":model}).scalar_one() == "third"
        assert con.execute(text("SELECT parameter_set_id FROM asr_schedule WHERE id=:id"),{"id":schedule}).scalar_one() == parameters[-1]
    command.upgrade(cfg,"0106")
    with engine.begin() as con:
        assert con.execute(text("""
            SELECT b.profile_id,p.revision_id,p.scope_connection_id FROM model_legacy_binding b
            JOIN model_parameter_profile p ON p.id=b.profile_id WHERE b.parameter_public_id=:s
        """), {"s":local_parameter}).one() == (local_profile,version,connection_ids[0])
        assert con.execute(text("SELECT secret_ciphertext FROM asr_connection ORDER BY id")).scalars().all() == [
            "credential-a","project-b-key"]
        assert con.execute(text("SELECT count(*) FROM model_revision WHERE resource_id=:r"),{"r":text_resource}).scalar_one() == 3
        assert con.execute(text("SELECT text_cost_output,text_timeout,config_json FROM model_revision WHERE id=:v"),
                           {"v":revisions[1]}).one() == (2.5,120,{})


def test_native_revision_changes_fingerprint_and_preserves_canonical_default_order(test_database):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.models.configuration import ModelConfiguration
    from app.core.models.identity import User
    from app.platform.model_configuration.center_schemas import ModelDefaultInput, ModelRevisionInput
    from app.platform.model_configuration.models import ModelResource, ModelRevision
    from app.platform.model_configuration.services.model_center_service import create_resource, create_revision, set_default_binding
    from app.platform.model_configuration.services.model_config_service import model_configuration_revision, load_model_for_provider
    from app.platform.model_configuration.tests.test_model_center import _text_resource

    engine = create_engine(TEST_DSN)
    try:
        with engine.connect() as con, con.begin(), Session(con) as db:
            admin = User(username="b2-rotation-admin",role="admin")
            db.add(admin)
            db.flush()
            template = _text_resource().model_copy(update={"credential":"first-key-for-pending-work", "config": {"timeout":120}})
            resources = [create_resource(db, template, admin, commit=False) for _ in range(3)]
            primary = db.get(ModelResource,resources[0]["id"])
            public_ids = [db.get(ModelResource,item["id"]).legacy_model_id for item in resources]
            old = db.get(ModelConfiguration,public_ids[0])
            original_digest = model_configuration_revision(old)
            update = ModelRevisionInput.model_validate(template.model_dump(include=set(ModelRevisionInput.model_fields)))
            create_revision(db, primary.id, update.model_copy(update={"credential":"rotated-key-for-pending-work", "config":{}}), admin)
            active = db.get(ModelConfiguration,public_ids[0],populate_existing=True)
            assert active.timeout == 120
            assert model_configuration_revision(active) != original_digest
            db.get(ModelRevision,resources[0]["current_revision_id"]).enabled = False
            db.flush()
            assert load_model_for_provider(db,public_ids[0]).api_key == "rotated-key-for-pending-work"
            set_default_binding(db, ModelDefaultInput(category="TEXT_GENERATION",purpose="TEXT_INFERENCE",
                resource_id=primary.id,revision_id=primary.current_revision_id,
                fallback_resource_ids=[resources[2]["id"],resources[1]["id"]],automatic_fallback=True), admin)
            current = db.get(ModelConfiguration,public_ids[0],populate_existing=True)
            assert current.is_default and current.fallback_model_ids == [public_ids[2],public_ids[1]]
    finally:
        engine.dispose()



