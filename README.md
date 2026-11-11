# local-llm: internal AI service (text-to-SQL, visuals, chat)

A small Python (FastAPI) service. Your Node API calls it; it never touches your database.

```
React ──► Node API ──► Python AI service ──► OpenAI  (now)  or  local model (Ollama, later)
              │              returns SQL / chart spec
              └─► validates SQL ─► runs it on HANA ─► rows back to React
```

**Privacy rule:** only table names, column names, descriptions and the user's question go to the model.
Rows never do. `/visual` accepts column names/types only and rejects a request that contains `rows`.

## Run it

```bash
cd local-llm
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then edit it
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
python -m pytest                                       # tests (no API key needed)
```
Interactive docs: http://127.0.0.1:8001/docs

## Providers and automatic fallback

`DEFAULT_PROVIDER=auto` tries `PROVIDER_ORDER` in sequence (Gemini, Groq, Cerebras, Mistral, OpenRouter, local).
Providers without a key are skipped. If one is rate-limited or down, the next one answers; the response
tells you which one did (`provider`, `model`). Send `"provider": "groq"` to force one. `GET /providers` shows what is configured.
Add a vendor: one line in `_REGISTRY` in `app/providers.py`.

## Switch to a local model (later)

```bash
# install Ollama from ollama.com, then:
ollama pull qwen2.5-coder:7b          # 14b or 32b is much better at SQL if your GPU/RAM allows
```
Then set `DEFAULT_PROVIDER=local` (or put `local` first in `PROVIDER_ORDER`), or send `"provider": "local"` per request.
Any OpenAI-compatible server works (llama.cpp, vLLM, LM Studio): change `LOCAL_BASE_URL` and `LOCAL_MODEL`.

## Endpoints (all need header `X-API-Key`)

| Endpoint | Input | Output |
|---|---|---|
| `POST /sql` | `question`, optional `previous_sql`, `provider`, `model`, `schema_override` | `sql`, `explanation`, `clarifying_question`, `tables_used` |
| `POST /sql/fix` | `sql`, `error` (DB error), optional `question` | corrected `sql` |
| `POST /visual` | `question`, `columns:[{name,type}]`, `format: spec\|tsx\|html\|js` | chart spec (JSON) or code |
| `POST /chat` | `messages:[{role,content}]` | `reply` |
| `GET /providers`, `GET /health` | | |

```bash
curl -X POST http://127.0.0.1:8001/sql -H "X-API-Key: change-me" -H "Content-Type: application/json" \
  -d '{"question":"top 5 customers by total order amount this year","provider":"openai"}'
```

## Files (read in this order)

| File | What it does |
|---|---|
| `app/main.py` | HTTP endpoints + API-key check |
| `app/service.py` | Calls the model, validates, retries with feedback |
| `app/providers.py` | OpenAI / local switch (one class, different URL) |
| `app/prompts.py` | All prompt text. Tune the AI here |
| `app/schema_store.py` | Holds schema, picks relevant tables, few-shot examples |
| `app/sql_guard.py` | Blocks anything that is not a single safe SELECT; unknown tables; adds LIMIT |
| `app/code_guard.py` | Blocks obvious dangerous patterns in AI-written UI code |
| `schema/schema.json` | YOUR tables/columns/descriptions/glossary (edit this) |
| `schema/examples.json` | Question → correct SQL pairs (biggest accuracy boost) |
| `node-integration/` | Ready-to-paste Node client + `/ai/report` route + React chart |

## What you still need to do

1. Replace `schema/schema.json` with your real schema (generate it from your existing `/schema` route, then add descriptions).
2. Add 20–50 real question→SQL pairs to `schema/examples.json`.
3. Create a **read-only HANA user** for AI-generated queries.
4. Paste `node-integration/*` into your Node app; set `AI_SERVICE_URL` and `AI_SERVICE_KEY`.
5. Render generated html/js only inside a sandboxed iframe (see `Visual.example.tsx`).
