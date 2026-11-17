# Evals

Compares naive vector RAG against hybrid (vector + keyword + RRF) with cross-encoder rerank.

> **Dataset status: drafted by Claude, pending author hand-check.** `dataset.meta.json` carries
> `"reviewed": false`. Every number produced from it is provisional until the author has
> checked each row and flipped the flag.

## Dataset (`dataset.jsonl`)

One row per line: `id, question, gold_sources, gold_snippets, gold_answer, answerable`.
Chunk ids differ between databases, so gold passages are identified by stable keys: a
corpus-relative file in `gold_sources` and an exact substring in the parallel `gold_snippets`.
A retrieval *hit* is any top-k chunk whose source file ends with a gold source and whose
(whitespace-normalised) text contains the matching snippet. `answerable: false` rows have no
gold passage; the correct behaviour is to abstain. The three refund rows are answerable but
the corpus holds two conflicting documents; both are listed as gold.

## Running

    make eval              # seeds the corpus if empty, runs both pipelines, prints the table
    make eval-retrieval    # retrieval-only (hit rate / MRR); no LLM key needed

`make seed` skips unchanged files, so it will not repair a dev database whose embeddings were
written by something else (for example the backend test suite, which uses the same database and stub
embedders). If retrieval numbers look implausibly low, empty the KB and reseed before evaluating:

    docker exec stacklight-dev-postgres-1 psql -U stacklight -d stacklight \
      -c "truncate documents, chunks restart identity cascade" && make eval-retrieval

`python evals/report.py` re-renders the table and the one-line summary from the committed JSON (retrieval-only
files get only the retrieval rows; it prints a provisional note while the dataset is unreviewed).

The LLM-dependent run needs a provider key visible to LiteLLM (for example
`ANTHROPIC_API_KEY`) and uses `LLM_MODEL` from settings (pinned in the results JSON).
Results land in `evals/results/<pipeline>.json`.
