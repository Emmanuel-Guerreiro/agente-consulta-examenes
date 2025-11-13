"""
Script para limpiar completamente la base de datos Neo4j.
Elimina todos los ejercicios, documentos, secciones y temas (opcional).
"""

from __future__ import annotations

import sys
import os

# Ensure project root is on sys.path for 'app' imports when running as a script
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from app.config import get_config
from app.db.neo4j_client import run_query


def clean_all_exercises() -> None:
	"""Elimina todos los ejercicios y sus respuestas."""
	print("Eliminando todos los ejercicios...")
	run_query(
		"""
		MATCH (e:Exercise)
		OPTIONAL MATCH (a:Answer)-[:ANSWERS]->(e)
		DETACH DELETE e, a
		"""
	)
	print("✅ Ejercicios eliminados")


def clean_topic_data(topic_id: str) -> None:
	"""Elimina todos los datos de un tema específico."""
	print(f"Eliminando datos del tema {topic_id}...")
	run_query(
		"""
		MATCH (t:Topic {id: $topic_id})
		OPTIONAL MATCH (d:Document)-[:BELONGS_TO]->(t)
		OPTIONAL MATCH (s:Section)<-[:HAS_SECTION]-(d)
		OPTIONAL MATCH (e:Exercise)-[:BELONGS_TO]->(t)
		OPTIONAL MATCH (a:Answer)-[:ANSWERS]->(e)
		DETACH DELETE d, s, e, a
		"""
	)
	print(f"✅ Datos del tema {topic_id} eliminados")


def clean_all_topics() -> None:
	"""Elimina todos los temas y sus datos relacionados."""
	print("Eliminando todos los temas...")
	run_query(
		"""
		MATCH (t:Topic)
		OPTIONAL MATCH (d:Document)-[:BELONGS_TO]->(t)
		OPTIONAL MATCH (s:Section)<-[:HAS_SECTION]-(d)
		OPTIONAL MATCH (e:Exercise)-[:BELONGS_TO]->(t)
		OPTIONAL MATCH (a:Answer)-[:ANSWERS]->(e)
		DETACH DELETE t, d, s, e, a
		"""
	)
	print("✅ Todos los temas eliminados")


def clean_all_data() -> None:
	"""
	Elimina TODOS los datos de la base de datos.
	Elimina: ejercicios, documentos, secciones, temas, respuestas, estudiantes, sesiones de estudio, y todas las relaciones.
	"""
	print("⚠️  ELIMINANDO TODOS LOS DATOS DE LA BASE DE DATOS...")
	
	# Eliminar todo en orden para evitar problemas de referencias
	# DETACH DELETE elimina los nodos y todas sus relaciones automáticamente
	
	print("   - Eliminando respuestas (Answer)...")
	run_query("MATCH (a:Answer) DETACH DELETE a")
	
	print("   - Eliminando ejercicios (Exercise)...")
	run_query("MATCH (e:Exercise) DETACH DELETE e")
	
	print("   - Eliminando secciones (Section)...")
	run_query("MATCH (s:Section) DETACH DELETE s")
	
	print("   - Eliminando documentos (Document)...")
	run_query("MATCH (d:Document) DETACH DELETE d")
	
	print("   - Eliminando sesiones de estudio (StudySession)...")
	run_query("MATCH (ss:StudySession) DETACH DELETE ss")
	
	print("   - Eliminando estudiantes (Student)...")
	run_query("MATCH (s:Student) DETACH DELETE s")
	
	print("   - Eliminando temas (Topic)...")
	run_query("MATCH (t:Topic) DETACH DELETE t")
	
	# Eliminar cualquier relación residual (por si acaso)
	print("   - Limpiando relaciones residuales...")
	run_query("MATCH ()-[r:KNOWS]->() DELETE r")
	run_query("MATCH ()-[r:HAS_SESSION]->() DELETE r")
	run_query("MATCH ()-[r:CONSULTED_TOPIC]->() DELETE r")
	run_query("MATCH ()-[r:USED_DOCUMENT]->() DELETE r")
	run_query("MATCH ()-[r:HAS_ANSWER]->() DELETE r")
	run_query("MATCH ()-[r:ANSWERS]->() DELETE r")
	run_query("MATCH ()-[r:BELONGS_TO]->() DELETE r")
	run_query("MATCH ()-[r:HAS_SECTION]->() DELETE r")
	
	print("✅ Todos los datos eliminados completamente")


def show_stats() -> None:
	"""Muestra estadísticas de la base de datos."""
	print("\n📊 Estadísticas de la base de datos:")
	
	# Contar temas
	result = run_query("MATCH (t:Topic) RETURN count(t) AS count", {})
	print(f"   - Temas: {result[0]['count']}")
	
	# Contar documentos
	result = run_query("MATCH (d:Document) RETURN count(d) AS count", {})
	print(f"   - Documentos: {result[0]['count']}")
	
	# Contar secciones
	result = run_query("MATCH (s:Section) RETURN count(s) AS count", {})
	print(f"   - Secciones: {result[0]['count']}")
	
	# Contar ejercicios
	result = run_query("MATCH (e:Exercise) RETURN count(e) AS count", {})
	print(f"   - Ejercicios: {result[0]['count']}")
	
	# Contar estudiantes
	result = run_query("MATCH (s:Student) RETURN count(s) AS count", {})
	print(f"   - Estudiantes: {result[0]['count']}")
	
	# Contar sesiones de estudio
	result = run_query("MATCH (ss:StudySession) RETURN count(ss) AS count", {})
	print(f"   - Sesiones de estudio: {result[0]['count']}")
	
	# Contar respuestas
	result = run_query("MATCH (a:Answer) RETURN count(a) AS count", {})
	print(f"   - Respuestas: {result[0]['count']}")
	
	# Contar ejercicios por tema
	result = run_query(
		"""
		MATCH (e:Exercise)-[:BELONGS_TO]->(t:Topic)
		RETURN t.nombre AS tema, count(e) AS count
		ORDER BY count DESC
		""",
		{}
	)
	if result:
		print("\n   Ejercicios por tema:")
		for r in result:
			print(f"      - {r['tema']}: {r['count']} ejercicios")


def main() -> None:
	"""Función principal."""
	cfg = get_config()
	if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
		print("Error: Faltan credenciales de Neo4j. Configura NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD", file=sys.stderr)
		sys.exit(1)
	
	# Mostrar estadísticas actuales
	print("📊 Estadísticas ANTES de limpiar:")
	show_stats()
	
	# Limpiar TODOS los datos
	print("\n⚠️  ELIMINANDO TODOS LOS DATOS DE LA BASE DE DATOS...")
	clean_all_data()
	
	# Mostrar estadísticas finales
	print("\n📊 Estadísticas DESPUÉS de la limpieza:")
	show_stats()
	
	print("\n✅ Limpieza completada. La base de datos está vacía.")
	print("💡 Ahora puedes ejecutar: python scripts/load_pdf_book.py")


if __name__ == "__main__":
	main()

