import asyncio
import json
from unittest.mock import MagicMock

from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

import fleetmanager.api as api_module


def test_healthcheck_reports_api_is_alive():
    response = asyncio.run(api_module.healthcheck())

    assert response == {"status": "ok"}


def test_readiness_reports_database_is_available(monkeypatch):
    connection = MagicMock()
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    database_engine = MagicMock()
    database_engine.connect.return_value = connection_context
    monkeypatch.setattr(api_module, "engine", database_engine)

    response = api_module.readinesscheck()

    assert response == {"status": "ok", "checks": {"database": "ok"}}
    connection.execute.assert_called_once()


def test_readiness_reports_database_is_unavailable(monkeypatch):
    database_engine = MagicMock()
    database_engine.connect.side_effect = SQLAlchemyError("database unavailable")
    monkeypatch.setattr(api_module, "engine", database_engine)

    response = api_module.readinesscheck()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "not ready",
        "checks": {"database": "unavailable"},
    }
