from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def mock_pipeline():
    mock = MagicMock()
    mock.return_value = [{"label": "POSITIVE", "score": 0.9987}]
    return mock


@pytest.fixture
def client_with_model(mock_pipeline):
    main.sentiment_pipeline = mock_pipeline
    main.app.router.lifespan_context = _noop_lifespan

    with patch("main.mlflow.start_run"), \
         patch("main.mlflow.log_param"), \
         patch("main.mlflow.log_metric") as mock_log_metric, \
         patch("main.mlflow.set_tag"):
        with TestClient(main.app) as test_client:
            test_client.mock_log_metric = mock_log_metric
            yield test_client

    main.sentiment_pipeline = None


@pytest.fixture
def client_without_model():
    main.sentiment_pipeline = None
    main.app.router.lifespan_context = _noop_lifespan

    with TestClient(main.app) as test_client:
        yield test_client
