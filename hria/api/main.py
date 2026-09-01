from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select, text

from hria.agent.pipeline import AgentPipeline
from hria.config import get_settings
from hria.data.models import Lot, Part, TestStation
from hria.db import SessionLocal
from hria.skills.store import result_store

logger = logging.getLogger("hria.api")
REQUEST_LATENCY = Histogram(
    "hria_request_latency_seconds", "HTTP request latency", ["method", "route", "status"]
)


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )
    yield


app = FastAPI(title="Hardware Reliability Insights Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
)
FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=__import__("hria.db", fromlist=["engine"]).engine)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", f"req-{uuid4().hex}")
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed request_id=%s path=%s", request_id, request.url.path)
        raise
    duration = time.perf_counter() - started
    trace_id = format(trace.get_current_span().get_span_context().trace_id, "032x")
    response.headers["X-Request-ID"] = request_id
    REQUEST_LATENCY.labels(
        method=request.method, route=request.url.path, status=str(response.status_code)
    ).observe(duration)
    logger.info(
        "request_completed request_id=%s trace_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        request_id,
        trace_id,
        request.method,
        request.url.path,
        response.status_code,
        duration * 1_000,
    )
    return response


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"failed:{type(exc).__name__}"
    try:
        Redis.from_url(get_settings().redis_url, socket_connect_timeout=1).ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"failed:{type(exc).__name__}"
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ok" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _run_query(question: str):
    with SessionLocal() as session:
        return AgentPipeline().run(question, session)


@app.post("/api/query")
async def query(payload: QueryRequest):
    answer = await asyncio.to_thread(_run_query, payload.question)
    return answer.model_dump(mode="json")


@app.post("/api/query/stream")
async def query_stream(payload: QueryRequest) -> StreamingResponse:
    async def stream():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        def run() -> None:
            def emit(name: str, body: dict) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, (name, body))

            try:
                with SessionLocal() as session:
                    answer = AgentPipeline().run(payload.question, session, on_event=emit)
                emit("done", answer.model_dump(mode="json"))
            except Exception as exc:
                emit("failed", {"error": f"{type(exc).__name__}: {exc}"})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(asyncio.to_thread(run))
        while True:
            item = await queue.get()
            if item is None:
                break
            name, body = item
            yield f"event: {name}\ndata: {json.dumps(body, default=str)}\n\n"
        await task

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@app.get("/api/results/{result_id}")
def result(result_id: str):
    value = result_store.get(result_id)
    if value is None:
        raise HTTPException(status_code=404, detail="result not found or expired")
    return value.model_dump(mode="json")


@app.get("/api/explorer/catalog")
def explorer_catalog() -> dict[str, list[str]]:
    with SessionLocal() as session:
        parts = list(
            session.scalars(
                select(Part.part_number).distinct().order_by(Part.part_number).limit(250)
            )
        )
        lots = list(session.scalars(select(Lot.lot_code).order_by(Lot.lot_code).limit(1_500)))
        stations = list(
            session.scalars(select(TestStation.name).order_by(TestStation.name).limit(250))
        )
    return {"parts": parts, "lots": lots, "stations": stations}


@app.get("/api/evals/latest")
def latest_eval_report() -> dict:
    report = Path(__file__).parents[1] / "evals" / "reports" / "latest.json"
    if not report.exists():
        raise HTTPException(status_code=404, detail="no evaluation report is committed")
    return json.loads(report.read_text())
