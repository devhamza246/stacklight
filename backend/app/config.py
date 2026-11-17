from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Built frontend served at "/" (copied into the image at /srv/static). Absent in dev/tests: nothing is mounted.
    static_dir: str = "/srv/static"
    # Shipped corpus: the repo's corpus/ when running from source, /srv/corpus in the image (env).
    # Stored document sources are relative to its parent ("corpus/handbook/x.md").
    corpus_dir: str = str(Path(__file__).resolve().parents[2] / "corpus")
    # Seed the corpus in the background on first start (empty `documents` table).
    auto_seed: bool = True
    database_url: str = "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
    redis_url: str = "redis://127.0.0.1:16379/0"
    llm_model: str = "claude-haiku-5-5"
    llm_timeout_s: float = 60
    # "local" = sentence-transformers; "litellm" = hosted model named by embedding_model
    embedding_provider: str = "local"
    # Local sentence-transformers model; embedding_dim must match its output size.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Abstain when the top hit scores below this. Cross-encoder logits, so only meaningful
    # for reranked hits. None = disabled until T7's eval harness calibrates a value.
    min_retrieval_score: float | None = None
    # Public-demo safety (app.safety): spend cap, per-IP limits, scheduled KB reset.
    daily_spend_cap_usd: float = 2.0
    # Flat USD charged per run today that had unpriced LLM calls (so unknown pricing cannot
    # bypass the cap).
    unknown_cost_per_run_usd: float = 0.02
    rate_limit_per_min: int = 20
    max_streams_per_ip: int = 4
    # Trust CF-Connecting-IP / X-Forwarded-For for the client IP. Only enable behind a proxy
    # that sets them (the Cloudflare tunnel deployment); otherwise they are spoofable.
    trust_proxy_headers: bool = False
    # Hours between automatic demo-KB resets; 0 disables.
    demo_reset_interval_h: float = 6.0
    # Seconds before retrying a reset that was skipped because runs were in flight.
    demo_reset_retry_s: float = 60.0
    # Curator: cap on document pairs sent to the conflict judge per run; a document is
    # considered stale when its "Last reviewed" date is older than this many months.
    curator_max_pairs: int = 20
    curator_stale_months: int = 18
    # Bounds (characters; also >= 3 words) on the find/replace quotes of a proposed edit.
    curator_min_quote_chars: int = 20
    curator_max_quote_chars: int = 500
    # Tracing DB writes run on the event loop: keep waits short and back off after a failure.
    trace_db_timeout_s: float = 2.0
    trace_breaker_cooldown_s: float = 30.0
    # Runs execute in the API process; extra runs wait with status "queued".
    max_concurrent_runs: int = 4
    # Pause between streamed answer chunks (a verified answer is replayed word by word).
    stream_chunk_delay_ms: int = 15
    sse_keepalive_s: float = 15.0
    run_buffer_max_events: int = 500
    run_retention_s: float = 600.0
    # Admission control: queued + running runs above this are refused with HTTP 429.
    max_pending_runs: int = 12
    max_run_buffers: int = 200
    # Retry-After advertised when a second audit is refused while one is queued or running.
    curate_retry_after_s: int = 15
    run_timeout_s: float = 120.0
    run_cleanup_interval_s: float = 60.0
    # Seconds between the two attempts of a node that hit LLMUnavailable.
    graph_retry_interval_s: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
