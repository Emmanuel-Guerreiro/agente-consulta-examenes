"""
Script para limpiar solo los ejercicios de la base de datos.
Elimina todos los ejercicios y sus respuestas, pero mantiene temas, documentos y secciones.
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
	print("⚠️  ELIMINANDO TODOS LOS EJERCICIOS...")
	
	# Eliminar respuestas primero (tienen relaciones con ejercicios)
	print("   - Eliminando respuestas (Answer)...")
	run_query("MATCH (a:Answer) DETACH DELETE a")
	
	# Eliminar ejercicios
	print("   - Eliminando ejercicios (Exercise)...")
	run_query("MATCH (e:Exercise) DETACH DELETE e")
	
	# Limpiar relaciones residuales
	print("   - Limpiando relaciones residuales...")
	run_query("MATCH ()-[r:ANSWERS]->() DELETE r")
	run_query("MATCH ()-[r:HAS_ANSWER]->() DELETE r")
	
	print("✅ Todos los ejercicios eliminados")


def show_stats() -> None:
	"""Muestra estadísticas de ejercicios en la base de datos."""
	print("📊 Estadísticas de ejercicios:")
	
	# Contar ejercicios
	result = run_query("MATCH (e:Exercise) RETURN count(e) AS count", {})
	print(f"   - Ejercicios: {result[0]['count']}")
	
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
	else:
		print("\n   No hay ejercicios asociados a temas")


def main() -> None:
	"""Función principal."""
	cfg = get_config()
	if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
		print("Error: Faltan credenciales de Neo4j. Configura NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD", file=sys.stderr)
		sys.exit(1)
	
	# Mostrar estadísticas actuales
	print("📊 Estadísticas ANTES de limpiar:")
	show_stats()
	
	# Limpiar todos los ejercicios
	print("\n⚠️  ELIMINANDO TODOS LOS EJERCICIOS...")
	clean_all_exercises()
	
	# Mostrar estadísticas finales
	print("\n📊 Estadísticas DESPUÉS de la limpieza:")
	show_stats()
	
	print("\n✅ Limpieza completada. Todos los ejercicios han sido eliminados.")
	print("💡 Los temas, documentos y secciones se mantienen intactos.")


if __name__ == "__main__":
	main()

