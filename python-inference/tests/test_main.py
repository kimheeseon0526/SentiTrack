def test_health_check_model_loaded(client_with_model):
    response = client_with_model.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_loaded": True}
 

def test_predict_positive_review(client_with_model):
    response = client_with_model.post(
        "/predict", json={"text": "이 제품 정말 마음에 들어요!"}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["label"] == "POSITIVE"
    assert 0.0 <= body["score"] <= 1.0
    assert body["model_version"] == "jaehyeong/koelectra-base-v3-generalized-sentiment-analysis"
    assert "latency_ms" in body


def test_predict_empty_text_returns_422(client_with_model):
    response = client_with_model.post("/predict", json={"text": ""})

    assert response.status_code == 422


def test_predict_text_too_long_returns_422(client_with_model):
    response = client_with_model.post("/predict", json={"text": "a" * 2001})

    assert response.status_code == 422


def test_predict_model_not_loaded_returns_503(client_without_model):
    response = client_without_model.post(
        "/predict", json={"text": "Will this fail gracefully?"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Model is not loaded yet"


def test_predict_logs_to_mlflow(client_with_model):
    client_with_model.post("/predict", json={"text": "배송이 빠르고 품질이 좋아요."})

    logged_keys = [call.args[0] for call in client_with_model.mock_log_metric.call_args_list]

    assert "confidence_score" in logged_keys
    assert "latency_ms" in logged_keys


def test_normalize_label_handles_numeric_strings(client_with_model, monkeypatch):
    import main

    assert main.normalize_label("1") == "POSITIVE"
    assert main.normalize_label("0") == "NEGATIVE"
    assert main.normalize_label("LABEL_1") == "POSITIVE"
    assert main.normalize_label("LABEL_0") == "NEGATIVE"
    assert main.normalize_label("POSITIVE") == "POSITIVE"
    assert main.normalize_label("NEGATIVE") == "NEGATIVE"


def test_normalize_clause_text_applies_simple_declarative_normalization():
    import main

    assert main._normalize_clause_text("향은 정말 좋았지만") == "향은 정말 좋았다."
    assert main._normalize_clause_text("지속력이 별로예요.") == "지속력이 별로예요."
