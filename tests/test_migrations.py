from alembic import command
from alembic.config import Config


def test_sqlite_migration_lifecycle(tmp_path):
    """Test full Alembic upgrade and downgrade lifecycle on SQLite."""
    test_db_path = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{test_db_path}"

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    # Upgrade to head
    command.upgrade(cfg, "head")

    # Downgrade to base
    command.downgrade(cfg, "base")

    # Re-upgrade to head
    command.upgrade(cfg, "head")


def test_postgresql_offline_sql_generation(capsys):
    """Test PostgreSQL offline SQL generation contains ENUM definitions."""
    cfg = Config("alembic.ini")
    cfg.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://user:pass@localhost:5432/testdb",
    )

    command.upgrade(cfg, "head", sql=True)
    captured = capsys.readouterr()
    sql_output = captured.out

    # Verify PostgreSQL ENUM types are created
    assert "CREATE TYPE questiontarget AS ENUM" in sql_output
    assert "CREATE TYPE gender AS ENUM" in sql_output
    assert "CREATE TYPE userstate AS ENUM" in sql_output
    assert "CREATE TYPE roomstate AS ENUM" in sql_output
    assert "CREATE TYPE playerrole AS ENUM" in sql_output
    assert "CREATE TYPE questionphase AS ENUM" in sql_output
    assert "CREATE TYPE participantstatus AS ENUM" in sql_output
    assert "CREATE TYPE oneononesessionstate AS ENUM" in sql_output
    assert "CREATE TYPE votechoice AS ENUM" in sql_output
    assert "CREATE TYPE matchstatus AS ENUM" in sql_output
    assert "CREATE TYPE matchroomstate AS ENUM" in sql_output

    # Verify PostgreSQL enum value additions
    assert "ALTER TYPE roomstate ADD VALUE IF NOT EXISTS 'ONE_ON_ONE'" in sql_output
    assert "ALTER TYPE roomstate ADD VALUE IF NOT EXISTS 'FINAL_SELECTION'" in sql_output
    assert "ALTER TYPE userstate ADD VALUE IF NOT EXISTS 'COMPLETED'" in sql_output
