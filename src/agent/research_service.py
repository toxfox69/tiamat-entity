#!/usr/bin/env python3
"""
TIAMAT Research Analysis Service — FastAPI async queue-based API
================================================================
POST /research/submit     → { job_id, status, eta_seconds, poll_url }  (202 Accepted)
GET  /research/status/{job_id}  → { job_id, status, result? }
GET  /research/list        → [ { job_id, status, title, created_at } ]

Analysis pipeline (per job):
  1. Fetch content  — arXiv PDF / Semantic Scholar abstract / HTML fallback
  2. Groq extract   — llama-3.3-70b structured JSON (claims, methods, results)
  3. gpu_infer      — RTX 3090 relevance scoring against Ringbound/TIAMAT context
  4. SurrealDB      — persist job record (replaces SQLite)

LLM tier routing:
  quick  → Groq llama-3.3-70b   (~5-8s)
  full   → Groq llama-3.3-70b   (~15s, more tokens)
  deep   → Claude Haiku 4.5     (~25s, nuanced Ringbound fit)
  expert → Claude Sonnet 4.6    (~60s, full synthesis)

Ringbound fit_score uses gpu_infer at quick/full depth (saves Haiku cost),
and then Haiku/Sonnet at deep/expert for narrative rationale on top.

─────────────────────────────────────────────────────────────────────────────
EXAMPLE API CALLS
─────────────────────────────────────────────────────────────────────────────

1. Submit an arXiv paper (full depth, default focus areas):

  curl -X POST https://tiamat.live/research/submit \\
    -H "Content-Type: application/json" \\
    -d '{"url": "https://arxiv.org/abs/2312.05230", "depth": "full"}'

  → 202 Accepted
  {
    "job_id": "a3f9c2d1-88b4-4e2a-9f01-1234567890ab",
    "status": "queued",
    "eta_seconds": 35,
    "poll_url": "/research/status/a3f9c2d1-88b4-4e2a-9f01-1234567890ab"
  }

2. Poll for status (returns immediately while running):

  curl https://tiamat.live/research/status/a3f9c2d1-88b4-4e2a-9f01-1234567890ab

  → 200 OK  (while in flight)
  {
    "job_id": "a3f9c2d1-88b4-4e2a-9f01-1234567890ab",
    "status": "running",
    "result": null,
    "error": null,
    "created_at": "2026-02-26T14:00:00.000Z",
    "updated_at": "2026-02-26T14:00:02.310Z"
  }

  → 200 OK  (when complete)
  {
    "job_id": "a3f9c2d1-88b4-4e2a-9f01-1234567890ab",
    "status": "complete",
    "result": {
      "title": "Attention Is All You Need",
      "authors": "Vaswani, Shazeer, Parmar, ...",
      "venue": "NeurIPS 2017",
      "year": "2017",
      "core_claims": [
        {
          "claim": "Self-attention replaces recurrence for sequence transduction",
          "confidence": 0.97,
          "evidence": "BLEU scores on WMT En-De/En-Fr benchmarks"
        }
      ],
      "methodology": [
        {"method": "Multi-head self-attention", "reproducibility": "high"}
      ],
      "results": [
        {"metric": "WMT En-De BLEU", "value": "28.4", "baseline": "ConvS2S 26.4"}
      ],
      "limitations": [
        {"limitation": "Quadratic attention complexity w.r.t. sequence length", "severity": "high"}
      ],
      "fit_score": 3,
      "fit_rationale": "Attention mechanisms tangentially relevant to beam scheduling AI...",
      "relevance_to_autonomous_systems": "Self-attention enables ...",
      "actionable_insights": [
        {"insight": "Apply sparse attention for beam schedule prediction", "priority": "medium", "effort": "weeks"}
      ],
      "hypothesis": "Sparse attention over spatial antenna grids will reduce beam-steering latency by 40%.",
      "novelty_score": 7,
      "gpu_relevance_score": 0.38,
      "gpu_relevance_tags": ["attention", "sequence modeling", "transformer"],
      "cost_estimate": {"model": "llama-3.3-70b-versatile", "tokens_in": 4120, "tokens_out": 982, "usd": 0.0},
      "cited_by": 102145,
      "fetch_method": "arxiv_pdf",
      "depth": "full",
      "processing_ms": 14320
    },
    "error": null,
    "created_at": "2026-02-26T14:00:00.000Z",
    "updated_at": "2026-02-26T14:00:14.320Z"
  }

3. Submit raw text (quick depth):

  curl -X POST https://tiamat.live/research/submit \\
    -H "Content-Type: application/json" \\
    -d '{
      "text": "We present a phased-array antenna system for directed wireless power transfer...",
      "depth": "quick",
      "focus_areas": ["claims", "methods"]
    }'

4. List recent jobs:

  curl https://tiamat.live/research/list?limit=5

  → 200 OK
  {
    "jobs": [
      {"job_id": "...", "status": "complete", "title": "Attention Is All You Need",
       "depth": "full", "created_at": "2026-02-26T14:00:00Z"},
      {"job_id": "...", "status": "running", "title": null, "depth": "quick",
       "created_at": "2026-02-26T14:02:11Z"}
    ],
    "total": 2
  }

5. Expert depth with Ringbound focus areas:

  curl -X POST https://tiamat.live/research/submit \\
    -H "Content-Type: application/json" \\
    -d '{
      "url": "https://arxiv.org/abs/2401.04321",
      "depth": "expert",
      "focus_areas": ["claims", "methods", "results", "implications"]
    }'

─────────────────────────────────────────────────────────────────────────────
SURREALDB SETUP (one-time)
─────────────────────────────────────────────────────────────────────────────
  # Install
  curl -sSf https://install.surrealdb.com | sh

  # Run (single-file RocksDB backend, daemon mode)
  surreal start --bind 127.0.0.1:8000 \\
    --user root --pass root \\
    --log info \\
    rocksdb:/root/api/research.db &

  # Or via systemd (see /etc/systemd/system/surrealdb.service)

  Schema is auto-created on first run (see _surreal_init_schema).

─────────────────────────────────────────────────────────────────────────────
GPU POD RELEVANCE API  (gpu_infer)
─────────────────────────────────────────────────────────────────────────────
  The GPU pod (RTX 3090 @ GPU_ENDPOINT) should expose:

  POST /infer/relevance
  Content-Type: application/json
  {
    "text": "<paper excerpt, ≤4096 chars>",
    "context": "<Ringbound/TIAMAT domain description>",
    "top_k": 5
  }
  → {
      "relevance_score": 0.72,          # cosine sim or cross-encoder score [0,1]
      "tags": ["beamforming", "MIMO"],  # top matched domain concepts
      "model": "bge-m3",               # or whatever embedding model is loaded
      "latency_ms": 180
    }

  If GPU pod is unavailable, gpu_infer falls back to a Groq-based zero-shot
  relevance classifier (set GPU_INFER_FALLBACK=groq in env).
"""

from __future__ import annotations

import asyncio
import datetime
from datetime import timezone
_UTC = timezone.utc
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [RESEARCH] %(message)s")
log = logging.getLogger("research")

# ── Config ───────────────────────────────────────────────────────────────────

GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GPU_ENDPOINT       = os.environ.get("GPU_ENDPOINT", "http://213.192.2.118:40080").rstrip("/")
GPU_INFER_FALLBACK = os.environ.get("GPU_INFER_FALLBACK", "groq")   # "groq" | "skip"

# SurrealDB connection
SURREAL_URL        = os.environ.get("SURREAL_URL", "http://127.0.0.1:8000")
SURREAL_USER       = os.environ.get("SURREAL_USER", "root")
SURREAL_PASS       = os.environ.get("SURREAL_PASS", "root")
SURREAL_NS         = "tiamat"
SURREAL_DB         = "research"

GROQ_MODEL         = "llama-3.3-70b-versatile"
HAIKU_MODEL        = "claude-haiku-4-5-20251001"
SONNET_MODEL       = "claude-sonnet-4-6"

MAX_TEXT_CHARS     = 20_000
JOB_TTL_HOURS      = 48

# Ringbound domain context fed to both LLM and gpu_infer
RINGBOUND_CONTEXT = """
Project Ringbound is a 7G Wireless Power Mesh system using:
- Phased-array antenna beamforming for directed energy transfer
- AI-driven beam scheduling and interference avoidance
- Metamaterial resonators for near-field coupling efficiency
- Distributed mesh topology (autonomous, no human-in-the-loop)
- Continuous optimization loops for real-time beam steering
Patent 63/749,552. ENERGENAI LLC. NAICS 541715, 541519.
""".strip()

# ── Enums + Schemas ───────────────────────────────────────────────────────────


class AnalysisDepth(str, Enum):
    quick  = "quick"
    full   = "full"
    deep   = "deep"
    expert = "expert"


class JobStatus(str, Enum):
    queued   = "queued"
    running  = "running"
    complete = "complete"
    failed   = "failed"
    cached   = "cached"


class ResearchSubmitRequest(BaseModel):
    url:         Optional[str] = Field(None, description="arXiv / DOI / GitHub / blog URL")
    text:        Optional[str] = Field(None, description="Raw paper text (alternative to url)")
    depth:       AnalysisDepth = Field(AnalysisDepth.full)
    focus_areas: list[str]     = Field(
        default=["claims", "methods", "results", "limitations"],
        description="Sections to analyse"
    )

    @model_validator(mode="after")
    def _xor_url_text(self) -> "ResearchSubmitRequest":
        if not self.url and not self.text:
            raise ValueError('Provide "url" or "text"')
        if self.url and self.text:
            raise ValueError('Provide "url" OR "text", not both')
        if self.text and len(self.text) > 100_000:
            raise ValueError("text exceeds 100,000 character limit")
        return self

    @field_validator("focus_areas")
    @classmethod
    def _validate_focus(cls, v: list[str]) -> list[str]:
        valid = {"claims", "methods", "results", "limitations", "implications"}
        return [f for f in v if f in valid] or list(valid)


class Claim(BaseModel):
    claim:      str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence:   str


class Method(BaseModel):
    method:          str
    reproducibility: str


class Result(BaseModel):
    metric:   str
    value:    str
    baseline: Optional[str] = None


class Limitation(BaseModel):
    limitation: str
    severity:   str   # "low" | "medium" | "high"


class ActionableInsight(BaseModel):
    insight:  str
    priority: str
    effort:   Optional[str] = None


class CostEstimate(BaseModel):
    model:      str
    tokens_in:  int
    tokens_out: int
    usd:        float


class GpuRelevance(BaseModel):
    relevance_score: float = Field(ge=0.0, le=1.0)
    tags:            list[str]    = Field(default_factory=list)
    model:           str          = "unknown"
    latency_ms:      Optional[int] = None
    fallback_used:   bool         = False


class ResearchResult(BaseModel):
    title:    str = ""
    authors:  str = ""
    venue:    str = ""
    year:     Optional[str] = None

    core_claims:  list[Claim]           = Field(default_factory=list)
    methodology:  list[Method]          = Field(default_factory=list)
    results:      list[Result]          = Field(default_factory=list)
    limitations:  list[Limitation]      = Field(default_factory=list)

    fit_score:                       int  = Field(0, ge=0, le=10)
    fit_rationale:                   str  = ""
    relevance_to_autonomous_systems: str  = ""

    gpu_relevance_score: Optional[float] = None
    gpu_relevance_tags:  list[str]        = Field(default_factory=list)

    actionable_insights: list[ActionableInsight] = Field(default_factory=list)
    hypothesis:          str = ""
    novelty_score:       int = Field(5, ge=0, le=10)

    cost_estimate:  Optional[CostEstimate] = None
    cited_by:       Optional[int]          = None
    fetch_method:   str                    = "unknown"
    depth:          str                    = "full"
    processing_ms:  Optional[int]          = None


class JobResponse(BaseModel):
    job_id:     str
    status:     JobStatus
    result:     Optional[Any] = None
    error:      Optional[str] = None
    created_at: str
    updated_at: str


class SubmitResponse(BaseModel):
    job_id:      str
    status:      JobStatus = JobStatus.queued
    eta_seconds: int
    poll_url:    str


class ListItem(BaseModel):
    job_id:     str
    status:     str
    title:      Optional[str] = None
    depth:      Optional[str] = None
    paper_id:   Optional[str] = None
    created_at: str


class ListResponse(BaseModel):
    jobs:  list[ListItem]
    total: int


# ── SurrealDB async client ────────────────────────────────────────────────────
#
# Uses SurrealDB's HTTP REST API ( POST /sql ) — no SDK required.
# Auth: HTTP Basic via Authorization header.
# Namespace + database passed as NS / DB headers.
#
# SurrealQL cheatsheet used here:
#   CREATE research_jobs:⟨uuid⟩ CONTENT { ... };
#   SELECT * FROM research_jobs WHERE id = research_jobs:⟨uuid⟩;
#   UPDATE research_jobs:⟨uuid⟩ MERGE { status: "running" };
#   SELECT job_id, status, title, depth, created_at
#     FROM research_jobs ORDER BY created_at DESC LIMIT ⟨n⟩;


def _surreal_headers() -> dict:
    import base64
    cred = base64.b64encode(f"{SURREAL_USER}:{SURREAL_PASS}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "NS":            SURREAL_NS,
        "DB":            SURREAL_DB,
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }


async def _surreal_sql(sql: str) -> list:
    """Execute raw SurrealQL and return the result list."""
    payload = sql
    headers = _surreal_headers()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{SURREAL_URL}/sql",
            headers=headers,
            content=payload.encode(),
        )
    r.raise_for_status()
    data = r.json()
    # SurrealDB returns a list of statement results
    if isinstance(data, list) and data:
        last = data[-1]
        if isinstance(last, dict) and last.get("status") == "OK":
            return last.get("result", [])
    return []


async def _surreal_init_schema() -> None:
    """
    Define the research_jobs table schema.
    SCHEMAFULL enforces field definitions. Called once on startup.
    """
    schema_sql = """
        DEFINE NAMESPACE IF NOT EXISTS tiamat;
        USE NAMESPACE tiamat;
        DEFINE DATABASE IF NOT EXISTS research;
        USE DATABASE research;

        DEFINE TABLE research_jobs SCHEMAFULL;

        DEFINE FIELD job_id     ON research_jobs TYPE string;
        DEFINE FIELD status     ON research_jobs TYPE string
            ASSERT $value IN ["queued","running","complete","failed","cached"];
        DEFINE FIELD paper_id   ON research_jobs TYPE option<string>;
        DEFINE FIELD depth      ON research_jobs TYPE string;
        DEFINE FIELD result     ON research_jobs TYPE option<object>;
        DEFINE FIELD error      ON research_jobs TYPE option<string>;
        DEFINE FIELD created_at ON research_jobs TYPE datetime;
        DEFINE FIELD updated_at ON research_jobs TYPE datetime;

        DEFINE INDEX idx_job_id ON research_jobs COLUMNS job_id UNIQUE;
        DEFINE INDEX idx_status ON research_jobs COLUMNS status;
        DEFINE INDEX idx_paper  ON research_jobs COLUMNS paper_id;

        DEFINE TABLE research_cache SCHEMAFULL;
        DEFINE FIELD paper_id   ON research_cache TYPE string;
        DEFINE FIELD depth      ON research_cache TYPE string;
        DEFINE FIELD result     ON research_cache TYPE object;
        DEFINE FIELD created_at ON research_cache TYPE datetime;
        DEFINE INDEX idx_cache  ON research_cache COLUMNS paper_id, depth UNIQUE;
    """
    try:
        await _surreal_sql(schema_sql)
        log.info("SurrealDB schema initialized")
    except Exception as exc:
        log.warning(f"SurrealDB schema init failed (will retry on next use): {exc}")


async def _job_create(job_id: str, depth: str, paper_id: Optional[str]) -> None:
    now = datetime.datetime.now(_UTC).isoformat()
    sql = f"""
        CREATE research_jobs CONTENT {{
            job_id:     "{job_id}",
            status:     "queued",
            depth:      "{depth}",
            paper_id:   {json.dumps(paper_id)},
            result:     NONE,
            error:      NONE,
            created_at: d"{now}",
            updated_at: d"{now}"
        }};
    """
    await _surreal_sql(sql)


async def _job_update(
    job_id: str,
    status: str,
    result: Optional[dict] = None,
    error:  Optional[str]  = None,
) -> None:
    now = datetime.datetime.now(_UTC).isoformat()
    result_val = json.dumps(result) if result is not None else "NONE"
    error_val  = json.dumps(error)  if error  is not None else "NONE"
    sql = f"""
        UPDATE research_jobs
        SET status     = "{status}",
            result     = {result_val},
            error      = {error_val},
            updated_at = d"{now}"
        WHERE job_id   = "{job_id}";
    """
    await _surreal_sql(sql)


async def _job_get(job_id: str) -> Optional[dict]:
    sql = f'SELECT * FROM research_jobs WHERE job_id = "{job_id}" LIMIT 1;'
    rows = await _surreal_sql(sql)
    if not rows:
        return None
    r = rows[0]
    return {
        "job_id":     r.get("job_id"),
        "status":     r.get("status"),
        "result":     r.get("result"),
        "error":      r.get("error"),
        "depth":      r.get("depth"),
        "paper_id":   r.get("paper_id"),
        "created_at": _surreal_ts(r.get("created_at", "")),
        "updated_at": _surreal_ts(r.get("updated_at", "")),
    }


async def _job_list(limit: int = 20, status_filter: Optional[str] = None) -> list[dict]:
    where = f'WHERE status = "{status_filter}"' if status_filter else ""
    sql = f"""
        SELECT job_id, status, depth, paper_id, created_at,
               result.title AS title
        FROM research_jobs
        {where}
        ORDER BY created_at DESC
        LIMIT {limit};
    """
    rows = await _surreal_sql(sql)
    return [
        {
            "job_id":     r.get("job_id"),
            "status":     r.get("status"),
            "depth":      r.get("depth"),
            "paper_id":   r.get("paper_id"),
            "title":      r.get("title"),
            "created_at": _surreal_ts(r.get("created_at", "")),
        }
        for r in rows
    ]


def _surreal_ts(raw: Any) -> str:
    """Normalize SurrealDB datetime to ISO string."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict) and "secs_since_epoch" in raw:
        # Older SurrealDB versions return an object
        dt = datetime.datetime.fromtimestamp(raw["secs_since_epoch"], tz=timezone.utc)
        return dt.isoformat()
    return str(raw)


async def _cache_get(paper_id: str, depth: str) -> Optional[dict]:
    sql = f"""
        SELECT result FROM research_cache
        WHERE paper_id = "{paper_id}" AND depth = "{depth}"
        LIMIT 1;
    """
    try:
        rows = await _surreal_sql(sql)
        return rows[0]["result"] if rows else None
    except Exception:
        return None


async def _cache_set(paper_id: str, depth: str, result: dict) -> None:
    now = datetime.datetime.now(_UTC).isoformat()
    sql = f"""
        UPDATE research_cache
        SET result     = {json.dumps(result)},
            created_at = d"{now}"
        WHERE paper_id = "{paper_id}" AND depth = "{depth}";

        IF (SELECT count() FROM research_cache
            WHERE paper_id = "{paper_id}" AND depth = "{depth}") = 0 THEN
            CREATE research_cache CONTENT {{
                paper_id:   "{paper_id}",
                depth:      "{depth}",
                result:     {json.dumps(result)},
                created_at: d"{now}"
            }};
        END;
    """
    try:
        await _surreal_sql(sql)
    except Exception as exc:
        log.warning(f"cache_set failed: {exc}")


# ── URL / Content helpers ─────────────────────────────────────────────────────


def _extract_paper_id(url: str) -> Optional[str]:
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", url, re.I)
    if m:
        return f"arxiv:{m.group(1)}"
    m = re.search(r"(?:dx\.)?doi\.org/(10\.\S+)", url, re.I)
    if m:
        return f"doi:{m.group(1).rstrip('/')}"
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)", url, re.I)
    if m:
        return f"github:{m.group(1).rstrip('/')}"
    return f"url:{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def _arxiv_pdf_url(url: str) -> str:
    return re.sub(r"arxiv\.org/abs/", "arxiv.org/pdf/", url)


async def _fetch_content(url: str) -> tuple[str, str, dict]:
    """
    Download and extract text. Returns (text, fetch_method, semantic_meta).
    Strategy:  Semantic Scholar abstract  →  PDF  →  HTML
    """
    text   = ""
    method = "failed"
    meta   = {}

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True,
        headers={"User-Agent": "TIAMAT/1.0 (tiamat.live)"}
    ) as client:
        # ── 1. Semantic Scholar metadata ──────────────────────────────
        arxiv_m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d+)", url)
        doi_m   = re.search(r"doi\.org/(.+?)(?:\s|$|#|\?)", url)
        ss_id   = None
        if arxiv_m:
            ss_id = f"arXiv:{arxiv_m.group(1).split('v')[0]}"
        elif doi_m:
            ss_id = doi_m.group(1).rstrip("/")

        if ss_id:
            try:
                r = await client.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/{ss_id}",
                    params={"fields": "title,abstract,citationCount,year,authors,venue"},
                    timeout=8,
                )
                if r.status_code == 200:
                    d = r.json()
                    meta = {
                        "title":    d.get("title", ""),
                        "authors":  ", ".join(a.get("name", "") for a in d.get("authors", [])),
                        "venue":    d.get("venue", ""),
                        "year":     str(d.get("year", "")),
                        "cited_by": d.get("citationCount"),
                        "abstract": d.get("abstract", ""),
                    }
                    text   = meta.get("abstract", "")
                    method = "semantic_abstract"
            except Exception:
                pass

        # ── 2. PDF (arXiv preferred) ──────────────────────────────────
        pdf_url = (
            _arxiv_pdf_url(url) if re.search(r"arxiv\.org/abs/", url)
            else (url if url.lower().endswith(".pdf") else None)
        )
        if pdf_url:
            try:
                r = await client.get(pdf_url, timeout=25)
                if r.status_code == 200 and b"%PDF" in r.content[:8]:
                    text   = await asyncio.get_event_loop().run_in_executor(
                        None, _extract_pdf_bytes, r.content
                    )
                    method = "arxiv_pdf"
            except Exception:
                pass

        # ── 3. HTML fallback ──────────────────────────────────────────
        if not text:
            try:
                r = await client.get(url, timeout=15)
                if r.status_code == 200:
                    text   = _strip_html(r.text)
                    method = "html"
            except Exception:
                pass

    return text[:MAX_TEXT_CHARS], method, meta


def _extract_pdf_bytes(raw: bytes) -> str:
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        parts  = [p.extract_text() for p in reader.pages[:30] if p.extract_text()]
        return "\n".join(parts)
    except Exception:
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>",   " ", text,  flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>",  " ", text)
    text = re.sub(r"&nbsp;",   " ", text)
    text = re.sub(r"&amp;",    "&", text)
    text = re.sub(r"&lt;",     "<", text)
    text = re.sub(r"&gt;",     ">", text)
    return re.sub(r"\s{3,}", "\n\n", text).strip()


# ── gpu_infer — GPU pod relevance scoring ─────────────────────────────────────
#
# Calls POST GPU_ENDPOINT/infer/relevance with the paper excerpt and
# the Ringbound domain context.  If the pod is offline or returns an error,
# falls back to a Groq zero-shot classifier (GPU_INFER_FALLBACK=groq)
# or returns a null score (GPU_INFER_FALLBACK=skip).
#
# Expected pod response schema:
#   { "relevance_score": float,  # 0.0–1.0
#     "tags":            list[str],
#     "model":           str,
#     "latency_ms":      int }


async def gpu_infer_relevance(text: str) -> GpuRelevance:
    """
    Score paper text against Ringbound domain context using GPU pod.
    Returns GpuRelevance with fallback_used=True if pod was unavailable.
    """
    excerpt = text[:4096]   # hard cap — embedding models choke on more

    # ── Primary: GPU pod ─────────────────────────────────────────────
    if GPU_ENDPOINT:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                t0 = time.monotonic()
                r  = await client.post(
                    f"{GPU_ENDPOINT}/infer/relevance",
                    json={
                        "text":    excerpt,
                        "context": RINGBOUND_CONTEXT,
                        "top_k":   5,
                    },
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                if r.status_code == 200:
                    d = r.json()
                    return GpuRelevance(
                        relevance_score=float(d.get("relevance_score", 0.0)),
                        tags=d.get("tags", []),
                        model=d.get("model", "gpu-pod"),
                        latency_ms=latency_ms,
                        fallback_used=False,
                    )
        except Exception as exc:
            log.warning(f"gpu_infer primary failed: {exc} — using fallback={GPU_INFER_FALLBACK}")

    # ── Fallback: Groq zero-shot classifier ──────────────────────────
    if GPU_INFER_FALLBACK == "groq" and GROQ_API_KEY:
        return await _gpu_infer_groq_fallback(excerpt)

    # ── Fallback: skip (null score) ───────────────────────────────────
    return GpuRelevance(relevance_score=0.0, tags=[], model="none", fallback_used=True)


async def _gpu_infer_groq_fallback(excerpt: str) -> GpuRelevance:
    """
    Zero-shot relevance scoring via Groq when GPU pod is offline.
    Classifies how relevant a paper excerpt is to the Ringbound domain.
    """
    system = (
        "You are a domain relevance classifier. "
        "Given a paper excerpt and a domain description, output ONLY valid JSON "
        "with keys: relevance_score (float 0.0-1.0), tags (array of ≤5 relevant concept strings). "
        "No prose, no markdown fences."
    )
    user = (
        f"Domain: {RINGBOUND_CONTEXT}\n\n"
        f"Paper excerpt:\n{excerpt[:2048]}\n\n"
        "Output JSON with relevance_score and tags."
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model":           GROQ_MODEL,
                    "messages":        [{"role": "system", "content": system},
                                        {"role": "user",   "content": user}],
                    "max_tokens":      120,
                    "temperature":     0.0,
                    "response_format": {"type": "json_object"},
                },
            )
        r.raise_for_status()
        d = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(d)
        return GpuRelevance(
            relevance_score=max(0.0, min(1.0, float(parsed.get("relevance_score", 0.0)))),
            tags=parsed.get("tags", [])[:5],
            model=f"groq/{GROQ_MODEL}/zero-shot",
            fallback_used=True,
        )
    except Exception as exc:
        log.warning(f"gpu_infer groq fallback failed: {exc}")
        return GpuRelevance(relevance_score=0.0, tags=[], model="groq-failed", fallback_used=True)


# ── LLM extraction ────────────────────────────────────────────────────────────

_DEPTH_CONFIG: dict[str, dict] = {
    "quick":  {"backend": "groq",   "max_tokens": 900,  "detail": "2-3 items per section"},
    "full":   {"backend": "groq",   "max_tokens": 1800, "detail": "3-5 items per section"},
    "deep":   {"backend": "haiku",  "max_tokens": 2500, "detail": "5+ items with evidence"},
    "expert": {"backend": "sonnet", "max_tokens": 4096, "detail": "exhaustive with citations"},
}

_ETA_SECONDS = {"quick": 15, "full": 35, "deep": 55, "expert": 90}


def _build_prompt(text: str, depth: str, focus_areas: list[str], meta: dict) -> tuple[str, str]:
    cfg    = _DEPTH_CONFIG.get(depth, _DEPTH_CONFIG["full"])
    detail = cfg["detail"]
    do_fit = depth in ("deep", "expert")

    system = (
        "You are a rigorous research analyst specializing in wireless power transfer, "
        "autonomous AI systems, and applied physics. "
        "Respond ONLY with a valid JSON object — no markdown fences, no prose outside JSON."
    )

    if do_fit:
        fit_block = (
            f'"fit_score": <int 0-10>,\n'
            f'"fit_rationale": "<why this paper is / is not relevant to Ringbound>",\n'
            f'"relevance_to_autonomous_systems": "<paragraph on AI/autonomy relevance>",'
        )
        ringbound_section = f"\n\nRingbound context:\n{RINGBOUND_CONTEXT}"
    else:
        fit_block = (
            '"fit_score": 5,\n'
            '"fit_rationale": "GPU-scored — upgrade to deep/expert for LLM rationale.",\n'
            '"relevance_to_autonomous_systems": "",'
        )
        ringbound_section = ""

    meta_hint = ""
    if meta.get("title"):
        meta_hint = (
            f"\n\nPre-fetched metadata (high trust):\n"
            f"Title: {meta.get('title','')}\n"
            f"Authors: {meta.get('authors','')}\n"
            f"Venue: {meta.get('venue','')}\n"
            f"Year: {meta.get('year','')}"
        )

    user = f"""Analyze the following paper. {detail}.
Focus areas: {', '.join(focus_areas)}{ringbound_section}{meta_hint}

Paper text:
---
{text}
---

Return a JSON object with EXACTLY these keys:
{{
  "title": "<string>",
  "authors": "<comma-separated>",
  "venue": "<journal / conference / arXiv / blog>",
  "year": "<YYYY>",
  "core_claims": [
    {{"claim": "<finding>", "confidence": <0.0-1.0>, "evidence": "<how supported>"}}
  ],
  "methodology": [
    {{"method": "<technique>", "reproducibility": "<high|medium|low>"}}
  ],
  "results": [
    {{"metric": "<measured>", "value": "<result>", "baseline": "<comparison or null>"}}
  ],
  "limitations": [
    {{"limitation": "<text>", "severity": "<low|medium|high>"}}
  ],
  "actionable_insights": [
    {{"insight": "<action>", "priority": "<high|medium|low>", "effort": "<days|weeks|months>"}}
  ],
  "hypothesis": "<one testable hypothesis>",
  "novelty_score": <int 0-10>,
  {fit_block}
  "notes": "<any other useful observation>"
}}"""

    return system, user


async def _call_groq(system: str, user: str, max_tokens: int) -> tuple[dict, int, int]:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type":  "application/json"},
            json={
                "model":           GROQ_MODEL,
                "messages":        [{"role": "system", "content": system},
                                    {"role": "user",   "content": user}],
                "max_tokens":      max_tokens,
                "temperature":     0.2,
                "response_format": {"type": "json_object"},
            },
        )
    r.raise_for_status()
    body    = r.json()
    raw     = body["choices"][0]["message"]["content"].strip()
    tok     = body.get("usage", {})
    return json.loads(raw), tok.get("prompt_tokens", 0), tok.get("completion_tokens", 0)


async def _call_anthropic(system: str, user: str, max_tokens: int, model: str) -> tuple[dict, int, int]:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":    model,
                "max_tokens": max_tokens,
                "system":   system,
                "messages": [{"role": "user", "content": user}],
            },
        )
    r.raise_for_status()
    body = r.json()
    raw  = body["content"][0]["text"].strip()
    raw  = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    tok  = body.get("usage", {})
    return json.loads(raw), tok.get("input_tokens", 0), tok.get("output_tokens", 0)


def _model_usd(model: str, tok_in: int, tok_out: int) -> float:
    prices = {
        GROQ_MODEL:   (0.0,  0.0),
        HAIKU_MODEL:  (0.80, 4.00),
        SONNET_MODEL: (3.00, 15.00),
    }
    p_in, p_out = prices.get(model, (1.0, 5.0))
    return round((tok_in * p_in + tok_out * p_out) / 1_000_000, 6)


async def _run_extraction(
    text: str, depth: str, focus_areas: list[str], meta: dict
) -> tuple[dict, CostEstimate]:
    cfg        = _DEPTH_CONFIG[depth]
    backend    = cfg["backend"]
    max_tokens = cfg["max_tokens"]
    system, user = _build_prompt(text, depth, focus_areas, meta)

    if backend == "groq":
        model = GROQ_MODEL
        raw, tok_in, tok_out = await _call_groq(system, user, max_tokens)
    elif backend == "haiku":
        model = HAIKU_MODEL
        raw, tok_in, tok_out = await _call_anthropic(system, user, max_tokens, model)
    else:
        model = SONNET_MODEL
        raw, tok_in, tok_out = await _call_anthropic(system, user, max_tokens, model)

    cost = CostEstimate(
        model=model, tokens_in=tok_in, tokens_out=tok_out,
        usd=_model_usd(model, tok_in, tok_out),
    )
    return raw, cost


def _normalize(
    raw: dict,
    meta: dict,
    depth: str,
    cost: CostEstimate,
    fetch_method: str,
    processing_ms: int,
    gpu: GpuRelevance,
) -> dict:
    # Trust Semantic Scholar for bibliographic fields
    for k in ("title", "authors", "venue", "year"):
        if meta.get(k):
            raw[k] = meta[k]

    # Coerce lists
    for k in ("core_claims", "methodology", "results", "limitations", "actionable_insights"):
        if not isinstance(raw.get(k), list):
            raw[k] = []

    # Clamp integer scores
    raw["novelty_score"] = max(0, min(10, int(float(raw.get("novelty_score", 5) or 5))))
    if raw.get("fit_score") is not None:
        raw["fit_score"] = max(0, min(10, int(float(raw.get("fit_score", 0) or 0))))

    # Normalize confidence values
    _conf_map = {"high": 0.9, "medium": 0.7, "low": 0.4}
    for c in raw.get("core_claims", []):
        v = c.get("confidence", 0.7)
        c["confidence"] = _conf_map.get(str(v).lower(),
                                        max(0.0, min(1.0, float(v or 0.7))))

    # Normalize severity
    valid_sev = {"low", "medium", "high"}
    for lim in raw.get("limitations", []):
        sev = str(lim.get("severity", "medium")).lower()
        lim["severity"] = sev if sev in valid_sev else "medium"

    # Attach GPU relevance
    raw["gpu_relevance_score"] = gpu.relevance_score
    raw["gpu_relevance_tags"]  = gpu.tags

    # Meta fields
    raw["depth"]         = depth
    raw["fetch_method"]  = fetch_method
    raw["cost_estimate"] = cost.model_dump()
    raw["processing_ms"] = processing_ms
    if meta.get("cited_by") is not None:
        raw["cited_by"] = meta["cited_by"]

    raw.pop("notes", None)   # strip LLM scratchpad key
    return raw


# ── Background pipeline ───────────────────────────────────────────────────────


async def _process_job(
    job_id:   str,
    request:  ResearchSubmitRequest,
    paper_id: Optional[str],
) -> None:
    """
    Full async pipeline:
      fetch → Groq/Claude extraction → gpu_infer → SurrealDB persist
    """
    t0 = time.monotonic()
    await _job_update(job_id, "running")

    try:
        # ── 1. Fetch content ──────────────────────────────────────
        if request.url:
            text, fetch_method, meta = await _fetch_content(request.url)
        else:
            text         = (request.text or "")[:MAX_TEXT_CHARS]
            fetch_method = "direct_text"
            meta         = {}

        if not text.strip():
            await _job_update(job_id, "failed", error="Could not extract text from source")
            return

        # ── 2. LLM extraction (Groq / Haiku / Sonnet) ────────────
        # ── 3. gpu_infer (runs concurrently with LLM extraction) ──
        extraction_task = asyncio.create_task(
            _run_extraction(text, request.depth.value, request.focus_areas, meta)
        )
        gpu_task = asyncio.create_task(
            gpu_infer_relevance(text)
        )

        (raw, cost), gpu = await asyncio.gather(extraction_task, gpu_task)

        # ── 4. Normalize and persist ──────────────────────────────
        processing_ms = int((time.monotonic() - t0) * 1000)
        result = _normalize(raw, meta, request.depth.value,
                            cost, fetch_method, processing_ms, gpu)

        if paper_id:
            await _cache_set(paper_id, request.depth.value, result)

        await _job_update(job_id, "complete", result=result)

        log.info(
            f"job={job_id} depth={request.depth.value} ms={processing_ms} "
            f"model={cost.model} usd={cost.usd} "
            f"gpu_score={gpu.relevance_score:.3f} gpu_fallback={gpu.fallback_used}"
        )

    except Exception as exc:
        log.exception(f"job={job_id} pipeline failed: {exc}")
        await _job_update(job_id, "failed", error=str(exc))


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(application: Any):  # noqa: ARG001
    await _surreal_init_schema()
    yield


app = FastAPI(
    title="TIAMAT Research Analysis API",
    description=(
        "Async queue-based academic paper analysis. "
        "Groq extraction + GPU-pod relevance scoring + SurrealDB persistence."
    ),
    version="2.0.0",
    lifespan=_lifespan,
)


@app.post("/research/submit", response_model=SubmitResponse, status_code=202)
async def research_submit(
    req: ResearchSubmitRequest,
    background_tasks: BackgroundTasks,
) -> SubmitResponse:
    """
    Submit a URL or raw text for async deep analysis.

    Returns a job_id immediately (202 Accepted).
    Poll GET /research/status/{job_id} for results — typically ready in 15-90s
    depending on depth tier.

    Cache hit: if the same paper+depth was analysed before, status=cached and
    the result is attached immediately in the /status response.
    """
    depth    = req.depth.value
    paper_id = _extract_paper_id(req.url) if req.url else None

    # ── Cache hit ─────────────────────────────────────────────────
    if paper_id:
        cached = await _cache_get(paper_id, depth)
        if cached:
            fake_id = f"cached_{paper_id}_{depth}"
            log.info(f"cache hit paper_id={paper_id} depth={depth}")
            return SubmitResponse(
                job_id=fake_id,
                status=JobStatus.cached,
                eta_seconds=0,
                poll_url=f"/research/status/{fake_id}",
            )

    job_id = str(uuid.uuid4())
    await _job_create(job_id, depth, paper_id)
    background_tasks.add_task(_process_job, job_id, req, paper_id)

    return SubmitResponse(
        job_id=job_id,
        status=JobStatus.queued,
        eta_seconds=_ETA_SECONDS.get(depth, 45),
        poll_url=f"/research/status/{job_id}",
    )


@app.get("/research/status/{job_id}", response_model=JobResponse)
async def research_status(job_id: str) -> JobResponse:
    """
    Poll for job status and result.

    status:
      queued   — waiting to start
      running  — pipeline in progress
      complete — result attached
      failed   — error attached
      cached   — served from cache, result attached
    """
    # ── Cache-hit synthetic job IDs ───────────────────────────────
    if job_id.startswith("cached_"):
        parts    = job_id.split("_", 2)
        paper_id = parts[1] if len(parts) > 1 else ""
        depth    = parts[2] if len(parts) > 2 else "full"
        cached   = await _cache_get(paper_id, depth)
        if cached:
            now = datetime.datetime.now(_UTC).isoformat()
            return JobResponse(
                job_id=job_id, status=JobStatus.cached,
                result=cached, created_at=now, updated_at=now,
            )
        raise HTTPException(status_code=404, detail="Cache entry not found or expired")

    row = await _job_get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    return JobResponse(
        job_id=row["job_id"],
        status=JobStatus(row["status"]),
        result=row.get("result"),
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.get("/research/list", response_model=ListResponse)
async def research_list(
    limit:  int            = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status"),
) -> ListResponse:
    """
    List recent research jobs, newest first.
    Useful for browsing the analysis history or building a feed.
    """
    rows = await _job_list(limit=limit, status_filter=status)
    return ListResponse(
        jobs=[ListItem(**r) for r in rows],
        total=len(rows),
    )


@app.get("/research/health")
async def research_health() -> dict:
    """Quick liveness check — also pings SurrealDB and GPU pod."""
    results: dict[str, Any] = {"service": "TIAMAT Research API v2", "status": "ok"}

    # SurrealDB reachable?
    try:
        await _surreal_sql("SELECT 1;")
        results["surrealdb"] = "ok"
    except Exception as exc:
        results["surrealdb"] = f"error: {exc}"

    # GPU pod reachable?
    if GPU_ENDPOINT:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{GPU_ENDPOINT}/health")
            results["gpu_pod"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception as exc:
            results["gpu_pod"] = f"unreachable: {exc}"

    return results


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5002, log_level="info")
