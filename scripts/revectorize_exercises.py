"""
Script para vectorizar ejercicios existentes y reasociarlos a los temas correctos.
Busca ejercicios sin vector o con asociaciones incorrectas y los reasocia al tema más relevante.
"""

from __future__ import annotations

import sys
import os
from typing import Dict, Any, List

# Ensure project root is on sys.path for 'app' imports when running as a script
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from app.config import get_config
from app.db.neo4j_client import run_query
from app.embeddings.ollama_embeddings import OllamaEmbeddingClient
from app.agent.tools import ensure_vector_indexes, find_topic_by_text
from tqdm import tqdm


def find_best_topic_for_exercise(task: str, embed_client: OllamaEmbeddingClient, default_topic_id: str = "topic_arquitectura") -> str:
	"""
	Encuentra el tema más relevante para un ejercicio basándose en su contenido.
	Si no encuentra un tema relevante, usa el tema por defecto.
	"""
	# Buscar el tema más relevante usando vectorización
	# Usamos un umbral más bajo (0.7) para permitir más flexibilidad
	topic = find_topic_by_text(task, min_similarity=0.7)
	
	if topic and topic.get("id"):
		return topic["id"]
	
	# Si no encuentra un tema, usar el tema por defecto
	return default_topic_id


def revectorize_and_reassign_exercises() -> None:
	"""
	Vectoriza todos los ejercicios y los reasocia al tema más relevante.
	"""
	cfg = get_config()
	embed_client = OllamaEmbeddingClient()
	
	print(f"✅ Usando modelo de embeddings: {embed_client.model}")
	
	# Asegurar índices vectoriales
	print("Asegurando índices vectoriales...")
	ensure_vector_indexes()
	
	# Obtener todos los ejercicios
	print("\n📋 Obteniendo todos los ejercicios...")
	exercises = run_query(
		"""
		MATCH (e:Exercise)-[r:BELONGS_TO]->(t:Topic)
		RETURN e.id AS id, e.task AS task, t.id AS current_topic_id, t.nombre AS current_topic_nombre
		ORDER BY e.id
		""",
		{}
	)
	
	if not exercises:
		print("⚠️  No se encontraron ejercicios en la base de datos.")
		return
	
	print(f"   Encontrados {len(exercises)} ejercicios")
	
	# Estadísticas
	topic_stats: Dict[str, int] = {}
	reassigned_count = 0
	revectorized_count = 0
	
	# Procesar cada ejercicio
	print("\n🔄 Procesando ejercicios...")
	for exercise in tqdm(exercises, desc="Reasociando ejercicios"):
		exercise_id = exercise["id"]
		task = exercise["task"]
		current_topic_id = exercise["current_topic_id"]
		
		# Encontrar el tema más relevante para este ejercicio
		best_topic_id = find_best_topic_for_exercise(task, embed_client)
		
		# Actualizar estadísticas
		topic_stats[best_topic_id] = topic_stats.get(best_topic_id, 0) + 1
		
		# Vectorizar el ejercicio (si no está vectorizado o actualizar)
		exercise_text = task
		exercise_vector = embed_client.embed(exercise_text)
		revectorized_count += 1
		
		# Actualizar el vector del ejercicio
		run_query(
			"MATCH (e:Exercise {id: $id}) SET e.vector = $vec",
			{"id": exercise_id, "vec": exercise_vector}
		)
		
		# Si el tema cambió, reasociar el ejercicio
		if best_topic_id != current_topic_id:
			# Eliminar la relación antigua
			run_query(
				"""
				MATCH (e:Exercise {id: $id})-[r:BELONGS_TO]->(t:Topic)
				DELETE r
				""",
				{"id": exercise_id}
			)
			
			# Crear la nueva relación
			run_query(
				"""
				MATCH (e:Exercise {id: $id})
				MATCH (t:Topic {id: $topic_id})
				MERGE (e)-[:BELONGS_TO]->(t)
				""",
				{"id": exercise_id, "topic_id": best_topic_id}
			)
			
			reassigned_count += 1
			if sys.stdout.isatty():
				tqdm.write(f"   🔄 Ejercicio {exercise_id}: {exercise.get('current_topic_nombre', 'Desconocido')} -> {best_topic_id}")
	
	# Mostrar estadísticas
	print("\n📊 Estadísticas de reasociación:")
	print(f"   - Ejercicios procesados: {len(exercises)}")
	print(f"   - Ejercicios reasociados: {reassigned_count}")
	print(f"   - Ejercicios vectorizados: {revectorized_count}")
	
	print("\n📊 Ejercicios por tema después de la reasociación:")
	for topic_id, count in sorted(topic_stats.items(), key=lambda x: x[1], reverse=True):
		topic_name = run_query(
			"MATCH (t:Topic {id: $id}) RETURN t.nombre AS nombre",
			{"id": topic_id}
		)
		if topic_name:
			print(f"   - {topic_name[0]['nombre']}: {count} ejercicios")
	
	print("\n✅ Proceso completado exitosamente!")


def main() -> None:
	"""Función principal."""
	cfg = get_config()
	if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
		print("Error: Faltan credenciales de Neo4j. Configura NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD", file=sys.stderr)
		sys.exit(1)
	
	# Mostrar estadísticas antes
	print("📊 Estadísticas ANTES de reasociar:")
	exercises_before = run_query("MATCH (e:Exercise)-[:BELONGS_TO]->(t:Topic) RETURN t.nombre AS tema, count(e) AS count ORDER BY count DESC", {})
	if exercises_before:
		print("   Ejercicios por tema:")
		for r in exercises_before:
			print(f"      - {r['tema']}: {r['count']} ejercicios")
	else:
		print("   No hay ejercicios")
	
	# Revectorizar y reasociar
	print("\n" + "="*60)
	revectorize_and_reassign_exercises()
	
	# Mostrar estadísticas después
	print("\n📊 Estadísticas DESPUÉS de reasociar:")
	exercises_after = run_query("MATCH (e:Exercise)-[:BELONGS_TO]->(t:Topic) RETURN t.nombre AS tema, count(e) AS count ORDER BY count DESC", {})
	if exercises_after:
		print("   Ejercicios por tema:")
		for r in exercises_after:
			print(f"      - {r['tema']}: {r['count']} ejercicios")
	else:
		print("   No hay ejercicios")


if __name__ == "__main__":
	main()

