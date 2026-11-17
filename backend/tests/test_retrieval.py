import os

import psycopg
import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://stacklight:stacklight@127.0.0.1:15432/stacklight"
)

from app.config import get_settings  # noqa: E402
from app.db import migrate  # noqa: E402
from app.retrieval import hybrid, keyword, rerank, vector  # noqa: E402

DB = os.environ["DATABASE_URL"]
DIM = 384


def onehot(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def lit(v: list[float]) -> str:
    return "[" + ",".join(map(str, v)) + "]"


# (title, status, chunk text, embedding axis)
KB = [
    ("Refund runbook", "active", "Ticket T-1010 describes the refund escalation steps.", 0),
    ("Billing FAQ", "active", "How to update your credit card billing details.", 1),
    ("Rate limits", "active", "ERR_429 means too many requests so back off and retry.", 2),
    ("Office life", "active", "Office plants watering schedule for the third floor.", 3),
    ("Old runbook", "archived", "Ticket T-1010 obsolete refund steps, billing details.", 1),
]
QUERY_AXIS: dict[str, int] = {}


@pytest.fixture(autouse=True)
def _kb(monkeypatch):
    get_settings.cache_clear()
    migrate()
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents cascade")
        for n, (title, status, text, axis) in enumerate(KB):
            did = c.execute(
                "insert into documents (title, source, content_hash, status) "
                "values (%s,%s,%s,%s) returning id",
                (title, f"kb/{n}.md", f"h{n}", status),
            ).fetchone()[0]
            c.execute(
                "insert into chunks (document_id, ord, text, embedding) values (%s,0,%s,%s::vector)",
                (did, text, lit(onehot(axis))),
            )

    async def fake_embed(texts):
        # Queries not in the map point at an unused axis (matches nothing well).
        return [onehot(QUERY_AXIS.get(t, 100)) for t in texts]

    QUERY_AXIS.clear()
    monkeypatch.setattr(vector, "embed", fake_embed)

    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(DB, open=False)
    for mod in (vector, keyword):
        monkeypatch.setattr(mod, "get_pool", lambda: pool)
    yield pool
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _open_pool(_kb):
    await _kb.open()
    yield
    await _kb.close()


class FakeCE:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def predict(self, pairs):
        self.calls.append(list(pairs))
        return [self.fn(q, t) for q, t in pairs]


async def test_vector_search_ranks_by_similarity_and_skips_archived():
    QUERY_AXIS["cards"] = 1
    hits = await vector.vector_search("cards", 5)
    assert hits[0].title == "Billing FAQ" and hits[0].score == pytest.approx(1.0)
    assert "Old runbook" not in {h.title for h in hits}
    assert hits[0].source == "kb/1.md" and hits[0].ord == 0


async def test_keyword_finds_exact_term_vector_misses():
    QUERY_AXIS["T-1010"] = 1  # embedding points at the billing chunk, not the runbook
    vec = await vector.vector_search("T-1010", 1)
    kw = await keyword.keyword_search("T-1010", 5)
    assert vec[0].title != "Refund runbook"
    assert [h.title for h in kw] == ["Refund runbook"]  # archived copy excluded


async def test_keyword_finds_underscore_identifier():
    kw = await keyword.keyword_search("ERR_429", 5)
    assert [h.title for h in kw] == ["Rate limits"]


@pytest.mark.parametrize("q", ['"unterminated', "(& | !", "a'b:c*", "!!!"])
async def test_keyword_survives_punctuation(q):
    assert isinstance(await keyword.keyword_search(q, 5), list)


async def test_hybrid_beats_vector_on_exact_id_query():
    QUERY_AXIS["T-1010"] = 1
    vec = await vector.vector_search("T-1010", 1)
    hyb = await hybrid.hybrid_search("T-1010", 1, rerank=False)
    assert vec[0].title == "Billing FAQ"
    assert hyb[0].title == "Refund runbook"


async def test_hybrid_dedupes_chunks():
    QUERY_AXIS["refund"] = 0
    hits = await hybrid.hybrid_search("refund", 10, rerank=False)
    ids = [h.chunk_id for h in hits]
    assert len(ids) == len(set(ids))


async def test_rerank_reorders_by_cross_encoder_score(monkeypatch):
    QUERY_AXIS["T-1010"] = 1
    fused = await hybrid.hybrid_search("T-1010", 3, rerank=False)
    ce = FakeCE(lambda q, t: 5.0 if "plants" in t else (1.0 if "billing" in t else 0.0))
    monkeypatch.setattr(rerank, "load_reranker", lambda: ce)
    out = await hybrid.hybrid_search("T-1010", 3)
    assert out[0].title == "Office life" and out[0].score == 5.0
    assert [h.title for h in out] != [h.title for h in fused]
    assert [h.score for h in out] == sorted((h.score for h in out), reverse=True)
    assert all(q == "T-1010" for q, _ in ce.calls[0])


async def test_rerank_false_never_loads_model(monkeypatch):
    def boom():
        raise AssertionError("model loaded")

    monkeypatch.setattr(rerank, "load_reranker", boom)
    QUERY_AXIS["refund"] = 0
    assert await hybrid.hybrid_search("refund", 3, rerank=False)


async def test_no_results_returns_empty_list(monkeypatch):
    monkeypatch.setattr(rerank, "load_reranker", lambda: FakeCE(lambda q, t: 0.0))
    # nothing matches keyword-wise; vector (axis 100) is orthogonal but still returns rows,
    # so use the empty-DB path for the true no-results case.
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("truncate documents cascade")
    for fn in (vector.vector_search, keyword.keyword_search):
        assert await fn("anything", 5) == []
    assert await hybrid.hybrid_search("anything") == []


async def test_blank_query_returns_empty_without_embedding(monkeypatch):
    async def boom(texts):
        raise AssertionError("embed called")

    monkeypatch.setattr(vector, "embed", boom)
    for q in ("", "   \n"):
        assert await vector.vector_search(q, 5) == []
        assert await keyword.keyword_search(q, 5) == []
        assert await hybrid.hybrid_search(q) == []


@pytest.mark.slow
async def test_real_cross_encoder_prefers_relevant_passage():
    try:
        ce = rerank.get_cross_encoder()
    except Exception as e:  # no network / not installed
        pytest.skip(f"reranker unavailable: {e}")
    good, bad = ce.predict(
        [
            ("how do I reset my password?", "To reset your password, open Settings and click Reset."),
            ("how do I reset my password?", "The cafeteria serves lunch from noon until two."),
        ]
    )
    assert good > bad


async def test_vector_ties_break_by_chunk_id():
    # Two chunks with identical embeddings must come back in a stable (id) order.
    with psycopg.connect(DB, autocommit=True) as c:
        did = c.execute("select id from documents where source = 'kb/3.md'").fetchone()[0]
        c.execute(
            "insert into chunks (document_id, ord, text, embedding) values (%s,1,%s,%s::vector)",
            (did, "Second office plants chunk.", lit(onehot(3))),
        )
        # Rewriting the first chunk moves its heap tuple after the second, so an
        # unordered tie would come back second-then-first.
        c.execute("update chunks set text = text || ' ' where document_id = %s and ord = 0", (did,))
    QUERY_AXIS["plants"] = 3
    hits = await vector.vector_search("plants", 5)
    tied = [h for h in hits if h.score == pytest.approx(1.0)]
    assert len(tied) == 2
    assert [h.chunk_id for h in tied] == sorted(h.chunk_id for h in tied)


LONG_Q = (
    "Hello team, our refund escalation is stuck and the billing details look wrong. "
    "Please advise on the plants schedule too, thanks!"
)


async def test_keyword_and_mode_misses_long_query_or_mode_finds_it():
    assert await keyword.keyword_search(LONG_Q, 5) == []
    kw = await keyword.keyword_search(LONG_Q, 5, mode="or")
    assert {h.title for h in kw} >= {"Refund runbook", "Billing FAQ", "Office life"}
    assert "Old runbook" not in {h.title for h in kw}  # archived still excluded


@pytest.mark.parametrize("q", ['"unterminated', "(& | !", "a'b:c*", "!!!", "   ", "the a an of", "|||refund|||"])
async def test_keyword_or_mode_is_safe(q):
    assert isinstance(await keyword.keyword_search(q, 5, mode="or"), list)


def test_or_terms_and_pick_terms_cap_drop_stopwords_and_sanitise():
    words = [f"term{i:02d}x" for i in range(200)]
    terms = keyword.or_terms("the " + " ".join(words) + " it's \"; drop--")
    assert terms[0] == "term00x" and len(terms) == keyword.MAX_CANDIDATES == len(set(terms))
    assert "the" not in terms and keyword.or_terms("!!! the of") == []
    assert set("".join(keyword.or_terms("a'b:c* (x) drop; |&!"))) <= set("abcdefghijklmnopqrstuvwxyz0123456789")
    df = {t: 200 - i for i, t in enumerate(terms)}  # later terms are rarer
    picked = keyword.pick_terms(terms, df).split(" | ")
    assert len(picked) == keyword.MAX_OR_TERMS and picked[0] == terms[-1]
    assert keyword.pick_terms(terms, {}) == ""  # nothing occurs in the KB


async def test_hybrid_threads_keyword_mode():
    h = await hybrid.hybrid_search(LONG_Q, 8, rerank=False, keyword_mode="or")
    assert "Refund runbook" in {x.title for x in h}
