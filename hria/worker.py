from __future__ import annotations

from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings
from prometheus_client import Gauge, start_http_server

from hria.agent.pipeline import AgentPipeline
from hria.config import get_settings
from hria.db import SessionLocal

QUEUE_READY = Gauge("hria_arq_ready_jobs", "Jobs ready to run", ["queue"])


async def analyze_question(ctx: dict, question: str) -> dict:
    del ctx
    with SessionLocal() as session:
        return AgentPipeline().run(question, session).model_dump(mode="json")


async def startup(ctx: dict) -> None:
    del ctx
    start_http_server(8001)


async def update_queue_depth(ctx: dict) -> None:
    redis = ctx["redis"]
    queue_name = WorkerSettings.queue_name
    now_ms = __import__("time").time_ns() // 1_000_000
    ready = await redis.zcount(queue_name, "-inf", now_ms)
    QUEUE_READY.labels(queue=queue_name).set(ready)


class WorkerSettings:
    functions: ClassVar = [analyze_question]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    queue_name = "arq:queue"
    max_jobs = 10
    job_timeout = 300
    health_check_interval = 30
    on_startup = startup
    cron_jobs: ClassVar = [cron(update_queue_depth, second=set(range(0, 60, 10)))]
