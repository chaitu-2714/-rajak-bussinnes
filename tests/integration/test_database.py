"""Integration tests: schema, constraints, transactions, persistence, backup."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import Database
from app.core.exceptions import BackupError
from app.database.base import Base
from app.database.models.role import Role
from app.database.models.user import User
from app.database.models.user_role import UserRole

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_PAYLOAD


def test_all_tables_are_created(database: Database) -> None:
    tables = set(database.table_names())
    expected = {
        "users",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
        "sessions",
        "business",
        "audit_logs",
    }
    assert expected.issubset(tables)


def test_schema_version_is_recorded(database: Database) -> None:
    assert database.schema_version() == "0009_security"


def test_foreign_keys_are_enforced(database: Database) -> None:
    with database.session_factory() as db:
        db.add(UserRole(user_id=999, role_id=999, assigned_by=None))
        with pytest.raises(IntegrityError):
            db.commit()


def test_unique_email_constraint(database: Database) -> None:
    with database.session_factory() as db:
        db.add(User(full_name="One", email="dup@example.com", password_hash="x"))
        db.commit()
        db.add(User(full_name="Two", email="dup@example.com", password_hash="y"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_unique_role_assignment_constraint(database: Database) -> None:
    with database.session_factory() as db:
        user = User(full_name="One", email="role@example.com", password_hash="x")
        role = Role(role_name="Temp", description="", is_system_role=False)
        db.add_all([user, role])
        db.commit()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.commit()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        with pytest.raises(IntegrityError):
            db.commit()


def test_transaction_rollback_discards_changes(database: Database) -> None:
    with database.session_factory() as db:
        db.add(User(full_name="Rollback", email="rollback@example.com", password_hash="x"))
        db.flush()
        db.rollback()

    with database.session_factory() as db:
        assert db.query(User).filter(User.email == "rollback@example.com").first() is None


def test_database_persists_across_restart(config, admin) -> None:
    admin.database.dispose()

    reopened = Database(config)
    reopened.initialize()
    try:
        from app.core.application import ApplicationContext

        context = ApplicationContext.build(config, reopened)
        assert context.auth_service.needs_initial_setup() is False
        result = context.auth_service.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert result.principal.email == ADMIN_EMAIL
    finally:
        reopened.dispose()


def test_initialisation_is_idempotent(config, database: Database) -> None:
    database.initialize()  # second call must not fail or wipe data
    assert "users" in database.table_names()


def test_integrity_check_passes(database: Database) -> None:
    ok, detail = database.integrity_check()
    assert ok is True
    assert detail == "ok"


def test_connection_check(database: Database) -> None:
    ok, detail = database.check_connection()
    assert ok is True
    assert "bizpilot_ai.db" in detail


def test_wal_mode_is_enabled(database: Database) -> None:
    with database.engine.connect() as connection:
        mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert str(mode).lower() == "wal"


def test_backup_and_restore_round_trip(admin) -> None:
    from tests.conftest import create_user

    create_user(admin, "Employee", "before-backup@bizpilot.test")
    backup = admin.backup_service.create_backup()
    assert backup.path.exists()
    assert backup.size_bytes > 0

    create_user(admin, "Employee", "after-backup@bizpilot.test")
    emails = {user.email for user in admin.user_service.list_users()}
    assert "after-backup@bizpilot.test" in emails

    admin.backup_service.restore_backup(backup.path)
    admin.auth_service.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    emails_after = {user.email for user in admin.user_service.list_users()}
    assert "before-backup@bizpilot.test" in emails_after
    assert "after-backup@bizpilot.test" not in emails_after


def test_restore_rejects_invalid_file(admin, tmp_path) -> None:
    bogus = tmp_path / "not-a-backup.db"
    bogus.write_text("this is not a sqlite database", encoding="utf-8")
    with pytest.raises(BackupError):
        admin.backup_service.restore_backup(bogus)


def test_backup_listing(admin) -> None:
    admin.backup_service.create_backup()
    backups = admin.backup_service.list_backups()
    assert len(backups) == 1
    assert backups[0].name.endswith(".db")


def test_migrations_match_models(database: Database) -> None:
    """The Alembic schema and the SQLAlchemy models must not drift apart."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], f"schema drift detected: {differences}"


def test_seeded_reference_data(admin) -> None:
    with admin.database.session_factory() as db:
        role_count = db.execute(text("SELECT COUNT(*) FROM roles")).scalar()
        permission_count = db.execute(text("SELECT COUNT(*) FROM permissions")).scalar()
    assert role_count == 6
    assert permission_count >= 30
