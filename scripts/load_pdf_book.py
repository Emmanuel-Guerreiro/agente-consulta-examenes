"""
Script para cargar el libro de Arquitectura de Computadoras desde PDF a Neo4j.
Lee el PDF, lo divide en secciones lógicas, crea documentos y secciones,
y los vectoriza con Ollama.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional

from pypdf import PdfReader
from tqdm import tqdm

# Ensure project root is on sys.path for 'app' imports when running as a script
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from app.config import get_config
from app.db.neo4j_client import run_query
from app.embeddings.ollama_embeddings import OllamaEmbeddingClient
from app.agent.tools import ensure_vector_indexes


# Configuración
TOPIC_ID = "topic_arquitectura"
TOPIC_NAME = "Arquitectura de Computadoras"
PDF_PATH = os.path.join(_ROOT, "vector", "Libro Arquitectura de Computadoras Santiago Perez 061022 (1).pdf")

# Tamaño máximo de sección (caracteres)
MAX_SECTION_SIZE = 1000
MIN_SECTION_SIZE = 100

# Tamaño de batch para vectorización
BATCH_SIZE = 10

# Configuración para ejercicios
EXERCISE_PATTERNS = [
	r'Ejercicio\s+\d+[.:]',
	r'Ejercitaci[oó]n\s*\d*[.:]?',
	r'\d+[.:]\s+(?:Ejercicio|Ejercicio)',
	r'EJERCICIO\s+\d+[.:]',
]
MIN_EXERCISE_LENGTH = 20


def extract_text_from_pdf(pdf_path: str) -> str:
	"""Extrae todo el texto del PDF."""
	print(f"Leyendo PDF: {pdf_path}")
	if not os.path.exists(pdf_path):
		raise FileNotFoundError(f"PDF no encontrado: {pdf_path}")
	
	reader = PdfReader(pdf_path)
	text_parts = []
	
	for page_num, page in enumerate(tqdm(reader.pages, desc="Extrayendo páginas")):
		try:
			text = page.extract_text()
			if text.strip():
				text_parts.append(text)
		except Exception as e:
			print(f"Error extrayendo página {page_num + 1}: {e}", file=sys.stderr)
	
	full_text = "\n\n".join(text_parts)
	print(f"Texto extraído: {len(full_text)} caracteres")
	return full_text


def split_text_into_chunks(text: str, chunk_size: int = MAX_SECTION_SIZE, overlap: int = 100) -> List[str]:
	"""
	Divide el texto en chunks con overlap para mantener contexto.
	"""
	chunks = []
	start = 0
	text_length = len(text)
	
	while start < text_length:
		end = min(start + chunk_size, text_length)
		
		# Si no es el último chunk, intentar cortar en un punto lógico (final de oración, párrafo, etc.)
		if end < text_length:
			# Buscar el último punto, signo de exclamación, o pregunta en el último 20% del chunk
			search_start = max(start, end - (chunk_size // 5))
			for i in range(end - 1, search_start - 1, -1):
				if text[i] in '.!?\n':
					end = i + 1
					break
				# Si encontramos un salto de línea doble (párrafo), también es un buen punto de corte
				if i > 0 and text[i] == '\n' and text[i-1] == '\n':
					end = i + 1
					break
		
		chunk = text[start:end].strip()
		if chunk and len(chunk) >= MIN_SECTION_SIZE:
			chunks.append(chunk)
		
		# Si llegamos al final, terminar
		if end >= text_length:
			break
		
		# Mover start con overlap para mantener contexto
		# El overlap solo aplica si no estamos cerca del final
		if end < text_length - overlap:
			start = end - overlap
		else:
			# Cerca del final, no usar overlap
			start = end
		
		# Evitar bucles infinitos
		if start <= 0:
			start = end
	
	return chunks


def split_into_sections(text: str) -> List[Dict[str, Any]]:
	"""
	Divide el texto en secciones lógicas.
	Intenta detectar capítulos y luego divide en documentos y secciones más pequeñas.
	"""
	print("Dividiendo texto en secciones...")
	
	# Limpiar el texto
	text = re.sub(r'\n{3,}', '\n\n', text)  # Normalizar saltos de línea múltiples
	text = re.sub(r'[ \t]+', ' ', text)  # Normalizar espacios
	
	# Detectar posibles capítulos (patrones comunes)
	chapter_patterns = [
		r'CAP[ÍI]TULO\s+\d+[.:]?\s*([^\n]+)',
		r'Capítulo\s+\d+[.:]?\s*([^\n]+)',
		r'^(\d+[.:]\s+[A-ZÁÉÍÓÚÑ][^\n]{10,})(?=\n)',
	]
	
	# Intentar encontrar capítulos
	chapters = []
	chapter_positions = []
	
	for pattern in chapter_patterns:
		matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
		if matches and len(matches) > 2:  # Si encontramos más de 2 capítulos, es probable que sea correcto
			for match in matches:
				chapter_title = match.group(1) if match.groups() else f"Capítulo {len(chapters) + 1}"
				chapter_positions.append((match.start(), match.group(0)))
			break
	
	# Si encontramos capítulos, dividir por ellos
	if chapter_positions:
		print(f"Encontrados {len(chapter_positions)} posibles capítulos")
		documents = []
		section_counter = 0
		
		for i, (pos, title_match) in enumerate(chapter_positions):
			# Determinar el rango de texto para este capítulo
			start_pos = pos
			end_pos = chapter_positions[i + 1][0] if i + 1 < len(chapter_positions) else len(text)
			chapter_text = text[start_pos:end_pos].strip()
			
			# Extraer el título del capítulo
			title_match_obj = re.search(r'CAP[ÍI]TULO\s+\d+[.:]?\s*(.+?)(?:\n|$)', title_match, re.IGNORECASE)
			if title_match_obj:
				chapter_title = title_match_obj.group(1).strip()
			else:
				title_match_obj = re.search(r'\d+[.:]\s*(.+?)(?:\n|$)', title_match)
				if title_match_obj:
					chapter_title = title_match_obj.group(1).strip()
				else:
					chapter_title = f"Capítulo {i + 1}"
			
			# Dividir el capítulo en chunks
			chunks = split_text_into_chunks(chapter_text, MAX_SECTION_SIZE, overlap=50)
			
			if chunks:
				doc_id = f"doc_arquitectura_{i+1:03d}"
				doc_sections = []
				
				for chunk in chunks:
					if len(chunk) >= MIN_SECTION_SIZE:
						section_counter += 1
						section_id = f"sec_arquitectura_{section_counter:03d}"
						doc_sections.append({
							"id": section_id,
							"content": chunk
						})
				
				if doc_sections:
					# Crear resumen del documento (primeros 500 caracteres)
					doc_content = chunks[0][:500] + ("..." if len(chunks[0]) > 500 else "")
					documents.append({
						"id": doc_id,
						"nombre": f"Arquitectura de Computadoras - {chapter_title}",
						"content": doc_content,
						"sections": doc_sections
					})
		
		if documents:
			print(f"Dividido en {len(documents)} documentos con {sum(len(doc['sections']) for doc in documents)} secciones")
			return documents
	
	# Si no se encontraron capítulos, dividir el texto completo en documentos y secciones
	print("No se encontraron capítulos claros, dividiendo por chunks...")
	
	# Dividir el texto completo en chunks
	chunks = split_text_into_chunks(text, MAX_SECTION_SIZE, overlap=50)
	
	if not chunks:
		print("Error: No se pudieron crear chunks del texto", file=sys.stderr)
		return []
	
	# Agrupar chunks en documentos (cada documento tiene ~5-10 secciones)
	sections_per_doc = 7
	documents = []
	section_counter = 0
	doc_counter = 0
	
	for i in range(0, len(chunks), sections_per_doc):
		doc_chunks = chunks[i:i+sections_per_doc]
		doc_sections = []
		
		for chunk in doc_chunks:
			if len(chunk) >= MIN_SECTION_SIZE:
				section_counter += 1
				section_id = f"sec_arquitectura_{section_counter:03d}"
				doc_sections.append({
					"id": section_id,
					"content": chunk
				})
		
		if doc_sections:
			doc_counter += 1
			doc_id = f"doc_arquitectura_{doc_counter:03d}"
			
			# Crear resumen del documento
			doc_content = doc_sections[0]["content"][:500] + ("..." if len(doc_sections[0]["content"]) > 500 else "")
			
			documents.append({
				"id": doc_id,
				"nombre": f"Arquitectura de Computadoras - Parte {doc_counter}",
				"content": doc_content,
				"sections": doc_sections
			})
	
	print(f"Dividido en {len(documents)} documentos con {sum(len(doc['sections']) for doc in documents)} secciones")
	return documents


def create_topic() -> None:
	"""Crea el tema de Arquitectura de Computadoras en Neo4j."""
	print(f"Creando tema: {TOPIC_NAME}")
	run_query(
		"MERGE (t:Topic {id: $id}) SET t.nombre = $nombre",
		{"id": TOPIC_ID, "nombre": TOPIC_NAME}
	)


def delete_topic_data() -> None:
	"""Elimina todos los datos del tema (documentos, secciones, ejercicios) antes de recargar."""
	print("Eliminando datos existentes del tema...")
	# Eliminar relaciones y nodos en el orden correcto
	run_query(
		"""
		MATCH (t:Topic {id: $topic_id})
		OPTIONAL MATCH (d:Document)-[:BELONGS_TO]->(t)
		OPTIONAL MATCH (s:Section)<-[:HAS_SECTION]-(d)
		OPTIONAL MATCH (e:Exercise)-[:BELONGS_TO]->(t)
		OPTIONAL MATCH (a:Answer)-[:ANSWERS]->(e)
		DETACH DELETE d, s, e, a
		""",
		{"topic_id": TOPIC_ID}
	)
	print("✅ Datos eliminados")


def load_documents_and_sections(sections: List[Dict[str, Any]], embed_client: OllamaEmbeddingClient) -> None:
	"""Carga documentos y secciones en Neo4j y los vectoriza."""
	print("Cargando documentos y secciones en Neo4j...")
	
	# Crear documentos y secciones
	for doc in tqdm(sections, desc="Creando documentos"):
		# Crear documento
		run_query(
			"""
			MATCH (t:Topic {id: $topic_id})
			MERGE (d:Document {id: $doc_id})
			SET d.nombre = $nombre, d.content = $content
			MERGE (d)-[:BELONGS_TO]->(t)
			""",
			{
				"topic_id": TOPIC_ID,
				"doc_id": doc["id"],
				"nombre": doc["nombre"],
				"content": doc["content"]
			}
		)
		
		# Crear secciones
		for section in doc["sections"]:
			run_query(
				"""
				MATCH (d:Document {id: $doc_id})
				MERGE (s:Section {id: $section_id})
				SET s.content = $content
				MERGE (d)-[:HAS_SECTION]->(s)
				""",
				{
					"doc_id": doc["id"],
					"section_id": section["id"],
					"content": section["content"]
				}
			)
	
	# Vectorizar temas
	# IMPORTANTE: Usar el mismo modelo de embeddings (mxbai-embed-large) para mantener consistencia
	print("Vectorizando temas...")
	topic_text = TOPIC_NAME
	topic_vector = embed_client.embed(topic_text)
	run_query(
		"MATCH (t:Topic {id: $id}) SET t.vector = $vec",
		{"id": TOPIC_ID, "vec": topic_vector}
	)
	print(f"  ✅ Tema vectorizado con modelo: {embed_client.model}")
	
	# Vectorizar documentos
	# IMPORTANTE: Mismo modelo de embeddings para consistencia en búsquedas
	print("Vectorizando documentos...")
	documents = run_query(
		"MATCH (d:Document)-[:BELONGS_TO]->(t:Topic {id: $topic_id}) RETURN d.id AS id, d.nombre AS nombre, d.content AS content",
		{"topic_id": TOPIC_ID}
	)
	
	for doc in tqdm(documents, desc="Vectorizando documentos"):
		doc_text = f"{doc['nombre']}\n\n{doc['content']}"
		doc_vector = embed_client.embed(doc_text)
		run_query(
			"MATCH (d:Document {id: $id}) SET d.vector = $vec",
			{"id": doc["id"], "vec": doc_vector}
		)
	
	# Vectorizar secciones
	# IMPORTANTE: Mismo modelo de embeddings para consistencia en búsquedas
	print("Vectorizando secciones...")
	sections_list = run_query(
		"""
		MATCH (s:Section)<-[:HAS_SECTION]-(d:Document)-[:BELONGS_TO]->(t:Topic {id: $topic_id})
		RETURN s.id AS id, s.content AS content
		""",
		{"topic_id": TOPIC_ID}
	)
	
	# Vectorizar en batches
	for i in tqdm(range(0, len(sections_list), BATCH_SIZE), desc="Procesando secciones"):
		batch = sections_list[i:i+BATCH_SIZE]
		for section in batch:
			section_text = section["content"]
			section_vector = embed_client.embed(section_text)
			run_query(
				"MATCH (s:Section {id: $id}) SET s.vector = $vec",
				{"id": section["id"], "vec": section_vector}
			)
	
	print(f"Vectorización completa: {len(documents)} documentos, {len(sections_list)} secciones")


def extract_exercises_from_text(text: str) -> List[Dict[str, Any]]:
	"""
	Extrae ejercicios del texto del PDF.
	Busca patrones como "Ejercicio 1:", "Ejercitación", etc.
	NO busca respuestas - solo extrae el enunciado (task).
	"""
	print("Extrayendo ejercicios del texto...")
	exercises = []
	exercise_counter = 0
	
	# Buscar secciones de ejercicios
	exercise_section_patterns = [
		r'Ejercitaci[oó]n\s*\d*[.:]?\s*([^\n]*)',
		r'EJERCITACI[OÓ]N\s*\d*[.:]?\s*([^\n]*)',
	]
	
	# Buscar ejercicios individuales
	for pattern in EXERCISE_PATTERNS:
		matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
		if matches:
			print(f"Encontrados {len(matches)} ejercicios con patrón: {pattern}")
			
			for i, match in enumerate(matches):
				# Determinar el rango de texto para este ejercicio
				start_pos = match.end()
				# Buscar el siguiente ejercicio o final de sección
				next_match = matches[i + 1] if i + 1 < len(matches) else None
				if next_match:
					end_pos = next_match.start()
				else:
					# Buscar el final buscando patrones de final de ejercicio
					# o tomar un límite razonable (2000 caracteres)
					end_pos = min(start_pos + 2000, len(text))
					# Intentar encontrar un punto de corte lógico
					for j in range(start_pos + 500, end_pos):
						if j >= len(text):
							break
						# Buscar el siguiente "Ejercicio" o número grande que indique fin
						if text[j:j+10].strip().startswith(('Ejercicio', 'EJERCICIO', '\n\n\n')):
							end_pos = j
							break
				
				exercise_text = text[start_pos:end_pos].strip()
				
				# Limpiar el texto del ejercicio
				exercise_text = re.sub(r'\s+', ' ', exercise_text)
				exercise_text = re.sub(r'\n{3,}', '\n\n', exercise_text)
				
				# Verificar que el ejercicio tenga contenido válido
				if len(exercise_text) >= MIN_EXERCISE_LENGTH:
					# Extraer el número del ejercicio si existe
					exercise_num_match = re.search(r'\d+', match.group(0))
					exercise_num = exercise_num_match.group(0) if exercise_num_match else str(i + 1)
					
					# NO buscar respuestas - solo extraer el enunciado
					# Limpiar el texto del ejercicio (remover posibles restos de respuestas)
					# Pero no buscamos activamente respuestas
					
					exercises.append({
						"task": exercise_text,
						"exercise_num": exercise_num
					})
					exercise_counter += 1
			
			# Si encontramos ejercicios, salir del loop
			if exercises:
				break
	
	print(f"Extraídos {len(exercises)} ejercicios del PDF")
	return exercises


def estimate_difficulty(task: str) -> float:
	"""
	Estima la dificultad de un ejercicio basándose en características del texto.
	Retorna un valor entre 0.0 (muy fácil) y 1.0 (muy difícil).
	"""
	difficulty = 0.3  # Base
	
	# Indicadores de dificultad baja (0.2-0.4)
	if any(word in task.lower() for word in ['qué es', 'define', 'explica qué', 'nombra']):
		difficulty = 0.2
	# Indicadores de dificultad media (0.4-0.6)
	elif any(word in task.lower() for word in ['represente', 'complete', 'indique', 'muestra']):
		difficulty = 0.5
	# Indicadores de dificultad alta (0.6-0.8)
	elif any(word in task.lower() for word in ['calcule', 'diseñe', 'implemente', 'analice', 'resuelva']):
		difficulty = 0.7
	# Si tiene tablas o datos numéricos complejos
	elif re.search(r'\d{4,}', task):  # Números largos (como códigos hexadecimales)
		difficulty = 0.6
	
	# Ajustar por longitud (ejercicios largos suelen ser más difíciles)
	if len(task) > 500:
		difficulty = min(0.9, difficulty + 0.2)
	elif len(task) > 200:
		difficulty = min(0.8, difficulty + 0.1)
	
	return round(difficulty, 2)


def find_best_topic_for_exercise(task: str, embed_client: OllamaEmbeddingClient, default_topic_id: str) -> str:
	"""
	Encuentra el tema más relevante para un ejercicio basándose en su contenido.
	Si no encuentra un tema relevante, usa el tema por defecto.
	"""
	from app.agent.tools import find_topic_by_text
	
	# Buscar el tema más relevante usando vectorización
	# Usamos un umbral más bajo (0.7) para permitir más flexibilidad
	topic = find_topic_by_text(task, min_similarity=0.7)
	
	if topic and topic.get("id"):
		return topic["id"]
	
	# Si no encuentra un tema, usar el tema por defecto
	return default_topic_id


def load_exercises(exercises: List[Dict[str, Any]], embed_client: OllamaEmbeddingClient) -> None:
	"""
	Carga ejercicios en Neo4j y los vectoriza.
	Los ejercicios NO tienen respuestas - solo el enunciado (task).
	Asocia cada ejercicio al tema más relevante según su contenido.
	"""
	print(f"Cargando {len(exercises)} ejercicios en Neo4j...")
	
	exercise_counter = 0
	topic_stats: Dict[str, int] = {}  # Estadísticas de asociación por tema
	
	for exercise in tqdm(exercises, desc="Creando ejercicios"):
		task = exercise["task"]
		
		# Estimar dificultad
		difficulty = estimate_difficulty(task)
		
		# Encontrar el tema más relevante para este ejercicio
		topic_id = find_best_topic_for_exercise(task, embed_client, TOPIC_ID)
		
		# Actualizar estadísticas
		topic_stats[topic_id] = topic_stats.get(topic_id, 0) + 1
		
		# Crear ID del ejercicio
		exercise_counter += 1
		exercise_id = f"ex_arquitectura_{exercise_counter:03d}"
		
		# Crear ejercicio en Neo4j SIN respuesta (solo task y difficulty)
		# NOTA: No establecemos la propiedad 'answer' - el ejercicio no tiene respuesta
		run_query(
			"""
			MATCH (t:Topic {id: $topic_id})
			MERGE (e:Exercise {id: $exercise_id})
			SET e.task = $task, e.difficulty = $difficulty
			MERGE (e)-[:BELONGS_TO]->(t)
			""",
			{
				"topic_id": topic_id,
				"exercise_id": exercise_id,
				"task": task,
				"difficulty": difficulty
			}
		)
	
	# Mostrar estadísticas de asociación
	print("\n📊 Estadísticas de asociación de ejercicios:")
	for topic_id, count in sorted(topic_stats.items(), key=lambda x: x[1], reverse=True):
		topic_name = run_query(
			"MATCH (t:Topic {id: $id}) RETURN t.nombre AS nombre",
			{"id": topic_id}
		)
		if topic_name:
			print(f"   - {topic_name[0]['nombre']}: {count} ejercicios")
	
	# Vectorizar ejercicios (todos, sin importar el tema)
	# IMPORTANTE: Mismo modelo de embeddings (mxbai-embed-large) para consistencia en búsquedas
	print("\nVectorizando ejercicios...")
	exercises_list = run_query(
		"""
		MATCH (e:Exercise)
		RETURN e.id AS id, e.task AS task
		"""
	)
	
	for exercise in tqdm(exercises_list, desc="Vectorizando ejercicios"):
		# Vectorizar solo usando task (sin answer)
		# NOTA: Usa el mismo modelo de embeddings que el resto del sistema
		exercise_text = exercise['task']
		exercise_vector = embed_client.embed(exercise_text)
		run_query(
			"MATCH (e:Exercise {id: $id}) SET e.vector = $vec",
			{"id": exercise["id"], "vec": exercise_vector}
		)
	
	print(f"✅ {len(exercises_list)} ejercicios cargados y vectorizados con modelo: {embed_client.model}")


def main() -> None:
	"""Función principal."""
	cfg = get_config()
	if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
		print("Error: Faltan credenciales de Neo4j. Configura NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD", file=sys.stderr)
		sys.exit(1)
	
	# Verificar que el PDF existe
	if not os.path.exists(PDF_PATH):
		print(f"Error: PDF no encontrado: {PDF_PATH}", file=sys.stderr)
		sys.exit(1)
	
	# Inicializar cliente de embeddings
	# IMPORTANTE: Usar el mismo modelo de embeddings (mxbai-embed-large) para todo
	embed_client = OllamaEmbeddingClient()
	print(f"✅ Usando modelo de embeddings: {embed_client.model}")
	
	# Asegurar índices vectoriales
	print("Asegurando índices vectoriales...")
	ensure_vector_indexes()
	
	# Eliminar datos existentes del tema "Arquitectura de Computadoras" para evitar duplicados
	# Esto elimina documentos, secciones y ejercicios asociados a este tema
	delete_topic_data()
	
	# IMPORTANTE: También eliminar ejercicios mal asociados que puedan tener el prefijo "ex_arquitectura_"
	# Estos son ejercicios del PDF que pueden estar asociados a otros temas incorrectamente
	print("Limpiando ejercicios del PDF mal asociados...")
	run_query(
		"""
		MATCH (e:Exercise)
		WHERE e.id STARTS WITH 'ex_arquitectura_'
		OPTIONAL MATCH (a:Answer)-[:ANSWERS]->(e)
		DETACH DELETE e, a
		"""
	)
	print("✅ Ejercicios del PDF limpiados")
	
	# Extraer texto del PDF
	text = extract_text_from_pdf(PDF_PATH)
	
	# Dividir en secciones
	sections = split_into_sections(text)
	
	if not sections:
		print("Error: No se pudieron crear secciones del PDF", file=sys.stderr)
		sys.exit(1)
	
	# Crear tema
	create_topic()
	
	# Cargar documentos y secciones
	load_documents_and_sections(sections, embed_client)
	
	# Extraer y cargar ejercicios
	exercises = extract_exercises_from_text(text)
	if exercises:
		load_exercises(exercises, embed_client)
	else:
		print("⚠️ No se encontraron ejercicios en el PDF")
	
	print("\n✅ Proceso completado exitosamente!")
	print(f"   - Tema creado: {TOPIC_NAME}")
	print(f"   - Documentos creados: {len(sections)}")
	print(f"   - Secciones creadas: {sum(len(doc['sections']) for doc in sections)}")
	print(f"   - Ejercicios creados: {len(exercises)}")
	print("\n💡 Ejecuta el servidor para usar el nuevo contenido vectorizado.")


if __name__ == "__main__":
	main()

