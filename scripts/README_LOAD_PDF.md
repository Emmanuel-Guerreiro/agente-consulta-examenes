# Script para Cargar PDF de Arquitectura de Computadoras

Este script lee el libro de Arquitectura de Computadoras desde un PDF, lo divide en secciones lógicas, y lo carga en Neo4j con vectorización usando Ollama.

## Requisitos

1. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Asegurar que Ollama esté corriendo:**
   ```bash
   ollama serve
   ```

3. **Verificar que el modelo de embeddings esté disponible:**
   ```bash
   ollama list
   # Debe incluir: mxbai-embed-large
   ```

4. **Configurar variables de entorno:**
   Asegúrate de tener configurado el archivo `.env` con:
   ```
   NEO4J_URI=neo4j+s://...
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=...
   OLLAMA_BASE_URL=http://localhost:11434
   ```

## Uso

Ejecuta el script desde la raíz del proyecto:

```bash
python scripts/load_pdf_book.py
```

## Qué hace el script

1. **Extrae texto del PDF:**
   - Lee el PDF desde `vector/Libro Arquitectura de Computadoras Santiago Perez 061022 (1).pdf`
   - Extrae todo el texto de todas las páginas

2. **Divide en secciones:**
   - Intenta detectar capítulos automáticamente
   - Si encuentra capítulos, los usa para dividir el contenido
   - Si no, divide el texto en chunks de ~1000 caracteres con overlap
   - Crea documentos (capítulos o partes) y secciones (chunks más pequeños)

3. **Crea el tema:**
   - Crea un Topic "Arquitectura de Computadoras" en Neo4j

4. **Carga en Neo4j:**
   - Crea documentos vinculados al tema
   - Crea secciones vinculadas a los documentos
   - Vectoriza todo el contenido usando Ollama (mxbai-embed-large)

5. **Vectoriza:**
   - Vectoriza el tema
   - Vectoriza cada documento
   - Vectoriza cada sección

## Estructura creada

```
Topic (topic_arquitectura)
  └─ Document (doc_arquitectura_001, doc_arquitectura_002, ...)
       └─ Section (sec_arquitectura_001, sec_arquitectura_002, ...)
```

## Configuración

Puedes ajustar los siguientes parámetros en el script:

- `MAX_SECTION_SIZE = 1000`: Tamaño máximo de cada sección (caracteres)
- `MIN_SECTION_SIZE = 100`: Tamaño mínimo de cada sección (caracteres)
- `BATCH_SIZE = 10`: Tamaño de batch para vectorización
- `TOPIC_ID = "topic_arquitectura"`: ID del tema
- `TOPIC_NAME = "Arquitectura de Computadoras"`: Nombre del tema

## Notas

- El proceso puede tardar varios minutos dependiendo del tamaño del PDF
- Asegúrate de tener suficiente espacio en Neo4j
- El script muestra progreso con barras de progreso (tqdm)
- Si el script falla, puedes ejecutarlo de nuevo (usa MERGE, así que no duplicará datos)

## Solución de problemas

1. **Error: PDF no encontrado**
   - Verifica que el PDF esté en `vector/Libro Arquitectura de Computadoras Santiago Perez 061022 (1).pdf`

2. **Error: Ollama no disponible**
   - Verifica que Ollama esté corriendo: `ollama serve`
   - Verifica que el modelo de embeddings esté instalado: `ollama pull mxbai-embed-large`

3. **Error: Neo4j no disponible**
   - Verifica las credenciales en `.env`
   - Verifica que Neo4j esté corriendo y accesible

4. **Error: No se pudieron crear secciones**
   - Verifica que el PDF tenga texto (algunos PDFs son solo imágenes)
   - Intenta ajustar `MIN_SECTION_SIZE` o `MAX_SECTION_SIZE`

