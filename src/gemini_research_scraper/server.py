"""HTTP service wrapper.

One browser profile can only run one research at a time, so jobs are queued
and executed sequentially by a single worker thread (Playwright's sync API in
a thread also sidesteps Windows asyncio-subprocess issues under uvicorn).

    POST /research                {"query": "..."}        -> {"job_id": ...}
    GET  /research/{job_id}                               -> status + metadata
    GET  /research/{job_id}/document?format=md|html       -> the report
"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .config import Settings
from .output import save_result
from .research import ResearchResult, extract_from_chat, run_research

log = logging.getLogger(__name__)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"


@dataclass
class Job:
    id: str
    query: str
    kind: str = "research"  # "research" | "extract"
    chat_url: Optional[str] = None  # for kind="extract"
    status: JobStatus = JobStatus.queued
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    result: Optional[ResearchResult] = None
    document_files: list[str] = field(default_factory=list)


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=3, description="The research question.")


class ExtractRequest(BaseModel):
    chat_url: str = Field(
        ..., min_length=4,
        description="Gemini chat URL (or bare chat id) holding a finished "
                    "Deep Research report.",
    )
    label: Optional[str] = Field(
        None, description="Recorded as the query in the document header."
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Gemini Deep Research Scraper", version="0.1.0")

    jobs: dict[str, Job] = {}
    work_queue: "queue.Queue[Job]" = queue.Queue()

    def worker() -> None:
        while True:
            job = work_queue.get()
            job.status = JobStatus.running
            log.info("Job %s (%s) started: %r", job.id, job.kind, job.query)
            try:
                if job.kind == "extract":
                    job.result = extract_from_chat(
                        job.chat_url, settings, job.query
                    )
                else:
                    job.result = run_research(job.query, settings)
                # Persist to the output directory too, so reports survive a
                # container restart (job state itself is in-memory only).
                try:
                    paths = save_result(
                        job.result, settings.output_dir, formats=("md", "html")
                    )
                    job.document_files = [str(p.resolve()) for p in paths]
                except OSError:
                    log.exception("Job %s: could not write report files.", job.id)
                job.status = JobStatus.complete
                log.info("Job %s complete.", job.id)
            except Exception as exc:  # report any failure through the API
                job.status = JobStatus.failed
                job.error = str(exc)
                log.exception("Job %s failed.", job.id)
            finally:
                work_queue.task_done()

    threading.Thread(target=worker, name="research-worker", daemon=True).start()

    def job_view(job: Job) -> dict:
        view = {
            "job_id": job.id,
            "kind": job.kind,
            "status": job.status,
            "query": job.query,
            "created_at": job.created_at.isoformat(),
            "error": job.error,
        }
        if job.result is not None:
            view["title"] = job.result.title
            view["chat_url"] = job.result.chat_url
            view["finished_at"] = job.result.finished_at.isoformat()
            view["document_url"] = f"/research/{job.id}/document"
            view["document_files"] = job.document_files
        return view

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "queued": work_queue.qsize()}

    @app.post("/research", status_code=202)
    def submit(req: ResearchRequest) -> dict:
        job = Job(id=uuid.uuid4().hex[:12], query=req.query)
        jobs[job.id] = job
        work_queue.put(job)
        return job_view(job)

    @app.post("/extract", status_code=202)
    def submit_extract(req: ExtractRequest) -> dict:
        job = Job(
            id=uuid.uuid4().hex[:12],
            query=req.label or f"extracted from {req.chat_url}",
            kind="extract",
            chat_url=req.chat_url,
        )
        jobs[job.id] = job
        work_queue.put(job)
        return job_view(job)

    @app.get("/research/{job_id}")
    def status(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job id.")
        return job_view(job)

    @app.get("/research/{job_id}/document")
    def document(job_id: str, format: str = "md"):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job id.")
        if job.status is not JobStatus.complete or job.result is None:
            raise HTTPException(409, f"Job is {job.status.value}, not complete.")
        if format == "html":
            return HTMLResponse(job.result.html)
        if format == "md":
            return PlainTextResponse(
                job.result.markdown, media_type="text/markdown; charset=utf-8"
            )
        if format == "compact":
            from .output import compact_markdown

            return PlainTextResponse(
                compact_markdown(job.result.markdown),
                media_type="text/markdown; charset=utf-8",
            )
        if format == "sources":
            if not job.result.sources_markdown:
                raise HTTPException(404, "No sources were captured for this job.")
            return PlainTextResponse(
                job.result.sources_markdown,
                media_type="text/markdown; charset=utf-8",
            )
        raise HTTPException(422, "format must be 'md', 'compact', 'sources', or 'html'.")

    return app
