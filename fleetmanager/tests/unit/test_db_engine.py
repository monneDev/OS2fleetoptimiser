import pytest

from fleetmanager.data_access.db_engine import engine_creator


DATABASE_VARIABLES = (
    "DB_NAME",
    "DB_PASSWORD",
    "DB_USER",
    "DB_URL",
    "DB_SERVER",
)


def clear_database_environment(monkeypatch):
    for variable in DATABASE_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("ALLOW_IN_MEMORY_DATABASE", raising=False)


def test_database_configuration_is_required_by_default(monkeypatch):
    clear_database_environment(monkeypatch)

    with pytest.raises(RuntimeError, match="Database configuration is required"):
        engine_creator()


def test_in_memory_database_requires_explicit_opt_in(monkeypatch):
    clear_database_environment(monkeypatch)
    monkeypatch.setenv("ALLOW_IN_MEMORY_DATABASE", "true")

    engine = engine_creator()

    assert engine.dialect.name == "sqlite"
    engine.dispose()


def test_partial_database_configuration_fails_even_with_local_opt_in(monkeypatch):
    clear_database_environment(monkeypatch)
    monkeypatch.setenv("ALLOW_IN_MEMORY_DATABASE", "true")
    monkeypatch.setenv("DB_NAME", "fleetoptimiser")

    with pytest.raises(RuntimeError, match="Incomplete database configuration"):
        engine_creator()
