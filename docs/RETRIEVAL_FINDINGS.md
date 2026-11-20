# Retrieval findings and goal

Status: hand-off, 2026-11-20. This document is self-contained: it records what was
observed, what was measured, what was changed, which hypotheses were refuted, and what the
next person (or model) is expected to achieve. It deliberately does not prescribe a
solution.

Everything below was measured against this repository's running stack on 2026-11-20. Where
a number is quoted, the reproduction command is given in §9.

## 0. Outcome (2026-11-20, afternoon)

Implemented as candidate direction 2 (re-score in our layer) together with direction 6
(a fixture-seeded evaluation project): DECISIONS.md D68, PROTOCOL §5.4. Against §3:

- off-corpus budget claim: 0 documents on the dpa corpus, 1 on the fixture corpus — met;
- `Köln Familien`: 1 document, the Cologne fact check — met;
- cross-lingual claims (FR/NL/EN against German documents and back) keep their target
  first on both corpora — met;
- `/retrieval`, checks and research share one `RelevantRetriever` — met;
- accuracy on a valid run: 3 runs before 0.560/0.640/0.720 (mean 0.640), 3 runs after
  0.600/0.600/0.680 (mean 0.627); no checkable statement lost all its passages —
  **within noise, but not demonstrably at or above 0.640**. The one systematic loss is
  `claim-044`, where the gate skips contradiction detection for an
  `insufficient_evidence` proposal; changing that is a gate rule and awaits a human
  decision (D68).

The sections below are the hand-off as written before the change.

## 1. The observation that started this

A user opened `/retrieval` (raw LightRAG retrieval, no fact check) and searched for
`Köln Familien`. The page returned **12 documents, 16 passages, 81 entities and 175
relations** in 4722 ms from a corpus of **18 documents**. Only one of the twelve was about
Cologne; the rest were fact checks about Rockefeller/Feminism, the Polish constitutional
crisis, the Crimea bridge, Pfizer, Spanish street vendors, sea level and a Cracow shooting.

The complaint is not that the page is wrong — it shows exactly what LightRAG returns — but
that retrieval is not relevance-aware: for virtually any query it returns most of the
corpus.

## 2. What the system does today

Stack: FastAPI backend, worker, Postgres 16 (pgvector 0.8.0 + AGE), Redis, stock LightRAG
v1.5.0 in its own database, Caddy edge. Prompt/verdict logic lives in our code; LightRAG is
used strictly as a retrieval service through documented HTTP endpoints (`/query/data`,
never `/query`).

- Corpus: **18 approved documents**, all imported dpa fact checks (German, French and Dutch
  content, all tagged `de`), **27 indexed chunks** after the footer removal described in §6.
- Embeddings: `bge-m3` through the internal gateway, 1024 dimensions.
- Vector index: pgvector HNSW, `m=16`, `ef_construction=64`. `hnsw.ef_search` was raised to
  200 (§6, D64); pgvector's default 40 lost chunks (§5.1).
- Entity/relation graph: ~513 entities, ~773 relations (was 543/862 before the re-index).
- Query defaults: checks and research use `top_k=40`, `chunk_top_k=20`; `/retrieval` uses
  its own `top_k=10`, `chunk_top_k=20` (D65).
- Relevance floor: LightRAG's `COSINE_THRESHOLD`, **stock default 0.2**, applied to the
  chunk, entity and relation vector stores alike.

### Why "many documents" is the expected behaviour today

1. `chunk_top_k=20` is a **count**, not a relevance cut. The corpus has 27 chunks.
2. The floor is 0.2. For `Köln Familien` the worst of the 28 (then) chunks scored **0.240**.
   Nothing is filtered.
3. `mix` mode merges the vector leg with a graph leg (`local` + `global`) into one 30 000
   token context; graph candidates and passages compete for that budget, so a large
   `top_k` *removes* passages from the response (§5.3).
4. The graph retrieval is keyword-driven and its entities are merged across documents
   (`Facebook`, `Meta`, `DPA`, `X`, `Poland`, `Warsaw`), so one hop reaches much of the
   corpus.

## 3. Goal

**Make retrieval relevance-aware on a small, topically diverse corpus: a query should
return the documents that actually cover it, not most of the corpus, without losing genuine
matches — especially paraphrased claims and cross-lingual ones — and without touching the
verdict or gate rules.**

Concretely, for this corpus and query set:

- An off-corpus query (`Der Bundeshaushalt 2026 beträgt 900 Milliarden Euro`) returns
  **0–2 documents**, not 13–15 as today.
- `Köln Familien` returns the Cologne fact check first and a handful of documents at most,
  not 15 of 18.
- Every labelled claim in a *valid* evaluation run keeps at least one correct evidence
  passage; accuracy does not fall below the recorded baseline of **0.640**.
- A cross-lingual claim (French or Dutch claim against German documents, or the reverse)
  keeps its document.
- `/retrieval` and the check pipeline use the same retrieval semantics, so the diagnostic
  page keeps telling the truth about what a check would see.

Non-goals: changing verdict rules, the gate or the evidence contract; adding a second
retrieval endpoint; editing LightRAG's source.

## 4. Constraints (hard)

From `AGENTS.md`, these are load-bearing and were not relaxed during the investigation:

- **LightRAG stays stock** (invariant 7): documented HTTP API and documented configuration
  only, no forks or patches, and never its answer generation.
- **Verdicts, the gate and contradiction detection are computed by code** (invariant 2).
  Retrieval changes may move *which* evidence exists, never how verdicts are computed.
- **`/query/data` returns no similarity scores.** The chunk dicts carry `reference_id`,
  `content`, `file_path`, `created_at`; our API therefore reports `"score": null`. Any
  score-based cut has to happen inside LightRAG or be recomputed in our layer.
- **One `COSINE_THRESHOLD` for three stores.** Chunks, entities and relations share it, and
  their score distributions are not comparable (§5.5).
- **Every LLM call goes through the gateway** and is budgeted; live evaluations cost money.
- Repository conventions: English documents, `DECISIONS.md` entry for every non-obvious
  decision, tests that state the guarantee they protect.

## 5. Measurements

### 5.1 The vector index was losing chunks (fixed, D64)

With pgvector's default `hnsw.ef_search=40`, the vector query returned **17 of 28** rows,
independent of the query; random query vectors with an open threshold returned 10–26 of 28.
A sequential scan returned 28. At `ef_search=100` and `200` the scan returns all 28 with an
unchanged top-10 order.

Effect: a chunk outside the HNSW beam could never become evidence — invisible to checks as
well as to `/retrieval`. Fixed by `ALTER DATABASE lightrag SET hnsw.ef_search = 200`
(committed in `deploy/postgres/init/01-databases.sh`).

### 5.2 The similarity landscape is flat

Cosine similarity of `Köln Familien` against all 28 chunks:

| rank | similarity | document |
| --- | --- | --- |
| 1 | 0.547 | Cologne women's swimming |
| 2 | 0.364 | Rockefeller/Feminism |
| 3 | 0.358 | Rockefeller/Feminism (second chunk) |
| 4 | 0.348 | Warsaw police convoy |
| 5 | 0.340 | Heiko von der Leyen/Pfizer |
| … | … | … |
| 17 | 0.297 | British vaccine study |

All 28 chunks lie between **0.240 and 0.547**, i.e. everything passes the 0.2 floor. Eight
hand-written claim-style queries against their target document scored 0.547–0.695 while the
best unrelated chunk scored 0.349–0.631.

The flat band is *not* caused by shared boilerplate: see §6.

### 5.3 The graph leg competes with the passages for one budget

LightRAG's `DEFAULT_MAX_TOTAL_TOKENS` is 30 000. In `mix` mode the serialised entity and
relation context is charged against the same budget as the passages:

| `top_k` (graph) | passages | documents | entities/relations |
| --- | --- | --- | --- |
| 5 | 20 | 15 | 12 / 18 |
| 10 | 20 | 16 | 24 / 36 |
| 40 | 16 | 12 | 81 / 175 |

A wider graph therefore *reduced* the number of passages and documents on the diagnostic
page. `/retrieval` now defaults to `top_k=10` (D65); checks keep 40 and were not changed.

### 5.4 At a 0.35 floor the graph still leaks

Off-corpus query at `COSINE_THRESHOLD=0.35`:

| mode | passages | documents |
| --- | --- | --- |
| `naive` | 0 | 0 |
| `local` | 8 | 8 |
| `global` | 17 | 14 |
| `mix` | 15 | 11 |

The vector leg is clean at 0.35; the graph leg still produces passages for a topic the
corpus does not cover, because entities that match the extracted keywords bring their
source chunks along. In the check pipeline this keeps `any_matching` true for off-corpus
claims (`backend/app/pipeline/runner.py`), so the deterministic "no matching document" path
never fires on this corpus.

### 5.5 The threshold cannot be raised globally

Entities (543) and relations (862) surviving the floor, per keyword, at four thresholds
(measured before the D67 re-index; the table is about the distributions, not the totals):

| threshold | entities | relations |
| --- | --- | --- |
| 0.20 (today) | 169–535 | 240–852 |
| 0.35 | 2–92 | 4–121 |
| 0.45 | 0–11 | 0–21 |
| 0.50 | 0–2 | 0–1 |

At 0.5 the graph retrieval is effectively empty and `mix` degenerates to `naive`. The
distributions differ because entity/relation similarity compares a *short keyword* with a
*one-sentence description*, while chunk similarity compares a *claim* with a *passage*.

### 5.6 The evaluation set does not match this corpus (blocks calibration)

`tests/eval/claims.jsonl` (25 cases) is labelled against `tests/fixtures/corpus`. This
instance holds the 18 imported dpa documents and **no fixture document at all**. The
committed baseline `tests/eval/predictions.baseline.jsonl` was recorded on 2026-11-18 at
08:57; the dpa corpus was approved that day at 22:28.

Consequence: a live run on this stack measures a corpus mismatch, not a retrieval setting.
A run at `COSINE_THRESHOLD=0.35` produced accuracy **0.280** vs the recorded **0.640**, with
21 of 25 claims becoming `insufficient_evidence` — the target documents simply do not exist.
The only evidence passage that run produced for `claim-001` was a publisher footer from an
unrelated document.

The 25 claims score 0.360–0.520 against their best chunk in the current corpus, and 2–27
chunks per claim sit above 0.35 — i.e. the floor itself is not what breaks them.

## 6. What was changed, and what it did

| change | effect | kept? |
| --- | --- | --- |
| D64 `hnsw.ef_search=200` | HNSW recall 17/28 → 28/28, order unchanged | yes |
| D65 `/retrieval` defaults 10/20 | passages 16 → 20, graph block 81/175 → 24/36, 4722 → 214 ms | yes |
| 0.35 floor experiment | page 16 → 6 documents; eval collapsed for corpus reasons | **reverted** (D66) |
| D67 publisher footer stripped before indexing | 19 of 28 chunks carried the dpa footer; now 0 of 27 | yes |
| Re-index of the 18 documents | corpus rebuilt from cleaned text | done |

**Refuted hypothesis:** the flat similarity band was *not* caused by the shared dpa footer.
After removing it, `Köln Familien` scored 0.540 against the Cologne document (was 0.547) and
0.370 against the best unrelated chunk (was 0.364); `/retrieval` still returned 15 of 18
documents. The footer sat inside chunks that are mostly substance, so its effect on the
embedding is small. The footer removal is kept because indexed text should not carry the
publisher's contact block, not because it improves retrieval.

**Also refuted:** "the requested k exceeds the corpus" alone. It is true (`chunk_top_k=20`
against 27 chunks) but raising or lowering k did not change the fundamental picture; HNSW
recall and the 0.2 floor did.

Spend: the instance had spent **$1.69 of its $15 monthly budget** at hand-off (336 checks,
1660 LightRAG calls). That includes two full re-index passes and the invalid live
evaluation. The changes from D64–D67 are in the working tree, uncommitted at hand-off.

## 7. What a solution has to reckon with

- A single global floor cannot serve chunks, entities and relations at once (§5.5).
- `/query/data` exposes no scores, so our layer cannot cut after the fact without
  recomputing similarity itself.
- At 0.2 the vector leg returns everything; at 0.35 the graph leg still returns most of the
  corpus. Both legs need a relevance notion, or the graph leg must stop contributing
  passages that the vector leg would reject.
- The check pipeline consumes the same call (`backend/app/pipeline/runner.py`), so any
  change to `/retrieval` semantics either must be mirrored there or must be explicitly
  split — and the split needs a reason better than "the page looks nicer".
- `mix`'s single 30 000-token budget couples graph breadth and passage count (§5.3).
- Verdict changes are only measurable on a stack seeded with `tests/fixtures/corpus`.

## 8. Candidate directions (not decisions)

Listed with the trade-offs already measured or known; none was implemented.

1. **Rerank** (`enable_rerank=true` plus a rerank model in the gateway/registry): separates
   topic clusters where cosine does not. Costs latency and a new model capability; still
   returns top-k, so it needs a cut or a much smaller k.
2. **Re-score in our layer**: retrieve wide with LightRAG, embed the candidates through the
   existing gateway and cut at a calibrated score. No LightRAG change, but adds calls and a
   second notion of relevance that the check pipeline must share.
3. **Mode split**: use `naive` where a missing document must be detectable, `mix` where
   graph context helps. Changes what `any_matching` means; needs a decision.
4. **Per-store floors**: not expressible in stock LightRAG (one env var for three stores).
   Would need two LightRAG instances or an upstream feature — out of bounds under
   invariant 7.
5. **Corpus-side deduplication / chunk shaping**: the footer removal is done; near-duplicate
   link blocks remain in some chunks.
6. **Rebuild the evaluation first**: a separate Compose project seeded with
   `make seed-fixtures`, so a threshold or model change is measurable at all. Without this,
   any tuning is guesswork.

## 9. Reproduction

```bash
# Corpus and index size (the LightRAG credentials come from .env)
set -a; . ./.env; set +a
docker compose exec -T postgres psql -U "$LIGHTRAG_DB_USER" -d "$LIGHTRAG_DB_NAME" -c "
  select count(*) from lightrag_vdb_chunks_fs_embedding_1024d;"

# Similarity of a query against every chunk (embeds through the gateway)
#   see the scripts used on 2026-11-20: embed the query with model fs-embedding at
#   http://backend:8000/internal/llm/v1/embeddings, then
#   1 - (content_vector <=> $1::vector) over lightrag_vdb_chunks_fs_embedding_1024d

# What /retrieval returns, end to end (needs a key from .local/api-key)
curl -sk -X POST https://localhost:8443/v1/retrieval \
  -H "Authorization: Bearer $(cat .local/api-key)" \
  -H "Content-Type: application/json" -d '{"query":"Köln Familien"}'

# Mode comparison at the current floor
#   POST /query/data with {"query": ..., "mode": "naive|local|global|mix",
#                          "top_k": 10, "chunk_top_k": 20, "only_need_context": true}

# Evaluation (only meaningful on a stack seeded with tests/fixtures/corpus)
make eval-recorded   # offline replay of the committed baseline
make eval-live       # live, costs money, rewrites the baseline
```

Operational traps encountered on 2026-11-20:

- `docker compose restart worker` keeps the old image; use `docker compose up -d worker`
  after a rebuild, or the re-index silently runs the previous code.
- LightRAG v1.5.0 logged `Error while deleting records from text_chunks: 'set' object is
  not subscriptable` during re-index; one document stalled in `processing` and had to be
  repaired by deleting and re-inserting its `doc@v` source.
- `strip_publisher_footer` matches the heading in the last 40 % of the text only; a heading
  earlier in the document is treated as content.

## 10. Where the truth lives

- `DECISIONS.md` D63–D67: the decisions and their rejected alternatives.
- `backend/app/services/raw_retrieval.py`: the diagnostic surface.
- `backend/app/retrieval/lightrag.py`: the stock client, the query parameters.
- `backend/app/pipeline/runner.py`: how checks consume retrieval, `any_matching`.
- `backend/app/services/text_cleanup.py`: the footer rule.
- `deploy/lightrag/lightrag.env`: the model bindings; `COSINE_THRESHOLD` is deliberately
  absent (stock 0.2).
- `deploy/postgres/init/01-databases.sh`: the database-level retrieval settings.
- `docs/OPERATING.md` §Retrieval, `docs/EVALUATION.md` §Baseline.
