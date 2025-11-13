# IA Study Agent (Neo4j + LangChain + Ollama)

Minimal agent using **Neo4j Aura**, **LangChain** with Ollama (configurable model), and embeddings from `mxbai-embed-large`.

---

## Prerequisites

- Python 3.10+
- Neo4j Aura DB (URI, user, password)
- Ollama running locally
  - `ollama pull qwen2.5:7b-instruct` (recomendado) o `qwen2.5:3b` (mínimo)
  - `ollama pull mxbai-embed-large`

### Requisitos de Hardware

- **RAM**: Mínimo 8GB (recomendado 16GB+)
- **GPU**: Opcional pero recomendada para mejor rendimiento
  - NVIDIA GPU con 4GB+ VRAM para modelos 7B
  - NVIDIA GPU con 8GB+ VRAM para modelos 14B
- **Almacenamiento**: 10GB+ libres para modelos

Ver `MODELOS_RECOMENDADOS.md` para más detalles sobre modelos y requisitos.

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
ollama run qwen2.5:7b-instruct
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

## Scripts de Mantenimiento

### Limpiar Base de Datos

**Limpiar toda la base de datos:**
```bash
python scripts/clean_database.py
```
Elimina todos los datos: ejercicios, documentos, secciones, temas, respuestas, estudiantes, sesiones. Útil para empezar desde cero.

**Limpiar solo ejercicios:**
```bash
python scripts/clean_exercises.py
```
Elimina todos los ejercicios y respuestas, pero mantiene temas, documentos y secciones. Útil cuando solo necesitas recargar ejercicios.

### Cargar PDF y Vectorizar Contenido

**Cargar libro PDF y vectorizar:**
```bash
python scripts/load_pdf_book.py
```
- Extrae texto del PDF ubicado en `vector/Libro Arquitectura de Computadoras Santiago Perez 061022 (1).pdf`
- Crea documentos, secciones y ejercicios
- Asocia automáticamente cada ejercicio al tema más relevante según su contenido
- Vectoriza todo usando `mxbai-embed-large`
- Elimina datos existentes del tema "Arquitectura de Computadoras" antes de cargar (evita duplicados)

**Ver documentación detallada:**
```bash
# Ver scripts/README_LOAD_PDF.md para más detalles
```

### Vectorizar y Reasociar Ejercicios Existentes

**Reasociar ejercicios a temas correctos:**
```bash
python scripts/revectorize_exercises.py
```
- Vectoriza todos los ejercicios existentes usando `mxbai-embed-large`
- Busca el tema más relevante para cada ejercicio
- Reasocia ejercicios al tema correcto si es necesario
- Útil cuando los ejercicios están mal asociados o necesitas actualizar las asociaciones

---

## Run Agent

### Web Interface (Recommended)

```bash
python run_server.py
```

Then open your browser at `http://localhost:8000` to access the chat interface.

The web interface provides:
- Clean, modern chat UI
- Real-time message exchange
- Session management per legajo
- All agent capabilities in a user-friendly interface

### CLI Interface

```bash
python -m app.agent.agent
```

The agent will:

- Ask for your `legajo` (creates the `Student` if not exists)
- Answer questions via hybrid RAG (vector search on documents + sections)
- Optionally grade answers for exercises and update knowledge level in the background

### Agent commands

The agent now uses tools automatically. Just write in natural Spanish; it will select tools as needed:

- **Preguntas conceptuales (búsqueda + respuesta):**
  - `¿Qué es una CPU?`
  - `Explica qué es la memoria RAM`
  - `¿Cómo funciona un procesador?`

- **Ejercicios:**
  - `Dame un ejercicio de RAM` - Busca ejercicios sobre el tema solicitado (incluso si el término no es un tema exacto)
  - `Dame un ejercicio de Arquitectura de Computadoras`
  - `Quiero practicar CPU`
  - El agente buscará ejercicios por contenido si no encuentra el tema directamente

- **Nivel de conocimiento:**
  - `¿Cuál es mi nivel en CPU?`
  - `Muéstrame mis niveles en todos los temas`

- **Resúmenes por tema:**
  - `Resúmeme mi actividad en Algoritmos`
  - `Dame un resumen de mis sesiones`

- **Calificar respuesta de ejercicio:**
  - Simplemente responde al ejercicio cuando el agente te lo propone
  - El agente detectará automáticamente que es una respuesta y la calificará

- **Resumir un tema (búsqueda + validación + regeneración opcional):**
  - `Hazme un resumen sobre arquitectura de procesadores 8086`
  - El agente recupera hasta 5 secciones/documentos relevantes, redacta un resumen, lo valida y, si es necesario, lo regenera. Si se requirió regeneración, añade una nota de precaución a la respuesta final.

---

## Conversational Context

The agent uses a short in-memory context (last 6 interactions) to improve tool selection and follow-ups. Each context item stores:

- user_prompt
- agent_response (trimmed)
- tool_used

This context is injected into the routing prompt so follow-ups like "y ahora sobre SQL" are understood in the current flow without restating the intent.

---

## Notes

- **Embedding model:** `mxbai-embed-large` ([Ollama page](https://ollama.com/library/mxbai-embed-large))
  - Usado consistentemente para vectorizar todos los contenidos (temas, documentos, secciones, ejercicios)
- **LLM model:** Configurable via `OLLAMA_MODEL` en `.env`
  - Default en código: `qwen2.5:0.5b` (se recomienda configurar explícitamente en `.env`)
  - Recomendado: `qwen2.5:7b-instruct` para mejor calidad
  - Ver `MODELOS_RECOMENDADOS.md` para opciones y requisitos

## Modelos Disponibles

El modelo de LLM se configura en el archivo `.env`:

```env
OLLAMA_MODEL=qwen2.5:7b-instruct
```

**Modelos recomendados:**
- `qwen2.5:7b-instruct` - Mejor equilibrio calidad/velocidad (recomendado)
- `qwen2.5:14b` - Máxima calidad (requiere 8GB+ VRAM)
- `qwen2.5:3b` - Mínimo, más rápido pero menos preciso

Ver `MODELOS_RECOMENDADOS.md` para detalles completos sobre requisitos de hardware.
