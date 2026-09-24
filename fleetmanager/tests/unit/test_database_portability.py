from sqlalchemy.dialects import mssql, postgresql

from fleetmanager.model.trip_generator import create_query


class _Engine:
    def __init__(self, dialect):
        self.dialect = dialect


def test_postgresql_trip_duration_uses_extract_epoch():
    query = create_query([1], _Engine(postgresql.dialect()))

    sql = str(query.statement.compile(dialect=postgresql.dialect()))

    assert "EXTRACT(epoch FROM" in sql
    assert "datediff" not in sql.lower()


def test_mssql_trip_duration_keeps_datediff():
    query = create_query([1], _Engine(mssql.dialect()))

    sql = str(query.statement.compile(dialect=mssql.dialect()))

    assert "datediff(SECOND" in sql
