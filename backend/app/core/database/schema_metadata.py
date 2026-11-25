"""Select physical tables and foreign keys for the PostgreSQL migration and SQLite debug schemas."""
from sqlalchemy import JSON, DefaultClause, ForeignKeyConstraint, MetaData, text

_MODEL_KEYS = {
    "model_configuration.id": "model_legacy_binding.model_public_id",
    "asr_connection.id": "model_legacy_binding.connection_public_id",
    "asr_parameter_set.id": "model_legacy_binding.parameter_public_id",
}


def postgres_metadata(application: MetaData) -> MetaData:
    views = {name for name, table in application.tables.items() if table.info.get("is_view")}
    return _physical_copy(application, views, _MODEL_KEYS)


def sqlite_metadata(application: MetaData) -> MetaData:
    # Local SQLite uses the original, directly writable test-asset relations.
    postgres_assets = {"test_collection", "test_collection_member", "test_case_component"}
    physical = _physical_copy(application, postgres_assets, {"test_collection.plan_public_id": "test_plan.id"})
    for table in physical.tables.values():
        for column in table.columns:
            default = column.server_default
            if isinstance(column.type, JSON) and isinstance(default, DefaultClause):
                literal = str(default.arg).removesuffix("::jsonb").removesuffix("::json")
                if literal in {"'{}'", "'[]'"}:
                    column.server_default = DefaultClause(text(literal))
    return physical


def _physical_copy(application: MetaData, excluded: set[str], foreign_targets: dict[str, str]) -> MetaData:
    physical = MetaData(naming_convention=application.naming_convention)
    for table in application.tables.values():
        if table.name not in excluded:
            table.to_metadata(physical)
    for table in physical.tables.values():
        for constraint in list(table.foreign_key_constraints):
            refs = [fk.target_fullname for fk in constraint.elements]
            targets = [foreign_targets.get(ref, ref) for ref in refs]
            if targets == refs:
                continue
            for key in constraint.elements:
                key.parent.foreign_keys.discard(key)
                table.foreign_keys.discard(key)
            table.constraints.discard(constraint)
            table.append_constraint(ForeignKeyConstraint(
                list(constraint.column_keys), targets, name=constraint.name, ondelete=constraint.ondelete,
                onupdate=constraint.onupdate, deferrable=constraint.deferrable, initially=constraint.initially,
                use_alter=constraint.use_alter,
            ))
    return physical
