# IA Study Agent (Neo4j + LangChain + Ollama)

Minimal agent using **Neo4j Aura**, **LangChain** with Ollama (`qwen2.5:0.5b`), and embeddings from `mxbai-embed-large`.

---

## Prerequisites

- Python 3.10+
- Neo4j Aura DB (URI, user, password)
- Ollama running locally
  - `ollama pull qwen2.5:0.5b`
  - `ollama pull mxbai-embed-large`

---

## Run Ollama and verify models

Start the Ollama service (one of the following):

```bash
# foreground (current shell)
ollama serve

# or as a system service (Linux)
sudo systemctl enable --now ollama
```

Verify the models are available:

```bash
ollama list
```

Quick LLM test (interactive shell):

```bash
ollama run qwen2.5:0.5b
# > Hola, ¿qué es una CPU?
```

Quick embeddings test (HTTP API):

```bash
curl -s http://localhost:11434/api/embeddings -d '{
  "model": "mxbai-embed-large",
  "prompt": "Represent this sentence for searching relevant passages: La CPU ejecuta instrucciones"
}' | jq .
```

- The app uses `OLLAMA_BASE_URL` (default `http://localhost:11434`). Adjust in `.env` if needed.
- Embedding model reference: https://ollama.com/library/mxbai-embed-large

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your Aura credentials
```

---

## .env

See `.env.example` for required environment variables.

---

## Initialize Schema and Seed Data

```bash
python seed/seed_mock.py
```

This script creates constraints and will attempt to create vector indexes with the correct dimension (auto-detected). If vector indexes are unavailable, the app falls back to in-app similarity.

---

## Vectorize CSV Content

```bash
python scripts/vectorize_csv.py \
  --label Document \
  --csv data/documents.csv \
  --id-field id \
  --text-field nombre --text-field content \
  --id-type property
```

- Supported labels: `Document`, `Section`, `Exercise`, `Topic`
- Use `--dry-run` to only print generated Cypher updates

---

## Export current nodes to CSV (for vectorization)

Export existing nodes into CSV files with the format `id,content`:

```bash
# Export all vectorizable labels to ./data
python scripts/export_vectors_csv.py

# Export specific labels to a custom directory
python scripts/export_vectors_csv.py --out-dir data/seed --label Document --label Exercise
```

This creates:

- `data/document.csv` (content = nombre + content)
- `data/section.csv` (content = Section.content)
- `data/exercise.csv` (content = Exercise.task)
- `data/topic.csv` (content = Topic.nombre)

Then vectorize any of them, for example Documents:

```bash
python scripts/vectorize_csv.py \
  --label Document \
  --csv data/document.csv \
  --id-field id \
  --text-field content \
  --id-type property
```

---

## Run Agent (CLI)

```bash
python -m app.agent.agent
```

The agent will:

- Ask for your `legajo` (creates the `Student` if not exists)
- Answer questions via hybrid RAG (vector search on documents + sections)
- Optionally grade answers for exercises and update knowledge level in the background

### Agent commands

The agent now uses tools automatically. Just write in natural Spanish; it will select tools as needed:

- Concept questions (retrieval + answer):
  - `¿Qué es una CPU?`
- Knowledge level:
  - `¿Cuál es mi nivel en CPU?`
  - `Muéstrame mis niveles en todos los temas`
- Per-topic summaries:
  - `Resúmeme mi actividad en Algoritmos`
  - `Dame un resumen de mis sesiones`
- Grade an exercise answer:
  - `Evalúa mi respuesta al ejercicio ex_cpu_1: "Es la unidad central que ejecuta instrucciones".`
- Summarize a topic (retrieval + validation + optional regeneration):
  - `Hazme un resumen sobre arquitectura de procesadores 8086`
  - The agent retrieves up to 5 relevant sections/documents, drafts a summary, validates it, and if needed regenerates it. If regeneration was required, it appends a caution note to the final response.

---

## Conversational Context

The agent uses a short in-memory context (last 6 interactions) to improve tool selection and follow-ups. Each context item stores:

- user_prompt
- agent_response (trimmed)
- tool_used

This context is injected into the routing prompt so follow-ups like “y ahora sobre SQL” are understood in the current flow without restating the intent.**_ End Patch_** }``` ?>

## Notes

- **Embedding model:** `mxbai-embed-large` ([Ollama page](https://ollama.com/library/mxbai-embed-large))
- **LLM model:** `qwen2.5:0.5b`
