import os
import time
from contextlib import asynccontextmanager

import mlflow
import mlflow.sklearn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import pipeline

MODEL_NAME = "jaehyeong/koelectra-base-v3-generalized-sentiment-analysis"
MODEL_REVISION = "370f325ce11aabd837b89bfb3ffdc26fde354689"

sentiment_pipeline = None


def normalize_label(raw_label: str) -> str:
    label = raw_label.strip().upper()
    if label in ("1", "LABEL_1", "POSITIVE"):
        return "POSITIVE"
    if label in ("0", "LABEL_0", "NEGATIVE"):
        return "NEGATIVE"
    raise ValueError(f"Unexpected label from model: {raw_label!r}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sentiment_pipeline
    sentiment_pipeline = pipeline(
        "sentiment-analysis",
        model=MODEL_NAME,
        revision=MODEL_REVISION,
    )
    yield
    sentiment_pipeline = None


app = FastAPI(title="SentiTrack Inference API", lifespan=lifespan)

mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "file:///app/mlruns"))
mlflow.set_experiment("review-sentiment-analysis")


class PredictRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class PredictResponse(BaseModel):
    label: str
    score: float
    model_version: str
    latency_ms: float


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": sentiment_pipeline is not None}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    if sentiment_pipeline is None:
        raise HTTPException(status_code=503, detail="Model is not loaded yet")

    start = time.perf_counter()
    result = sentiment_pipeline(request.text)[0]
    latency_ms = (time.perf_counter() - start) * 1000

    normalized_label = normalize_label(result["label"])
    confidence_score = float(result["score"])

    with mlflow.start_run():
        mlflow.log_param("model_name", MODEL_NAME)
        mlflow.log_param("input_text", request.text[:500])
        mlflow.log_metric("confidence_score", confidence_score)
        mlflow.log_metric("latency_ms", latency_ms)
        mlflow.set_tag("predicted_label", normalized_label)

    return PredictResponse(
        label=normalized_label,
        score=confidence_score,
        model_version=MODEL_NAME,
        latency_ms=latency_ms,
    )
