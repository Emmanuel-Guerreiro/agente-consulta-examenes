from __future__ import annotations

from typing import Any, Dict, List

from app.config import get_config
from app.db.neo4j_client import run_query
from app.agent.tools import ensure_vector_indexes


def apply_constraints() -> None:
	with open("app/db/schema.cypher", "r", encoding="utf-8") as f:
		cypher = f.read()
	for stmt in [s.strip() for s in cypher.split(";") if s.strip()]:
		run_query(stmt)


def seed() -> None:
	topics: List[Dict[str, Any]] = [
		{"id": "topic_cpu", "nombre": "CPU"},
		{"id": "topic_alg", "nombre": "Algoritmos"},
		{"id": "topic_db", "nombre": "Bases de Datos"},
	]

	docs: List[Dict[str, Any]] = [
		{
			"id": "doc_cpu_intro",
			"nombre": "Introducción a la CPU",
			"content": "La CPU es la unidad central de procesamiento que ejecuta instrucciones de programas.",
			"topic_id": "topic_cpu",
		},
		{
			"id": "doc_alg_intro",
			"nombre": "Qué es un algoritmo",
			"content": "Un algoritmo es un conjunto finito de pasos para resolver un problema específico.",
			"topic_id": "topic_alg",
		},
		{
			"id": "doc_db_intro",
			"nombre": "Introducción a Bases de Datos",
			"content": "Una base de datos organiza datos de forma estructurada y permite consultas eficientes.",
			"topic_id": "topic_db",
		},
	]

	sections: List[Dict[str, Any]] = [
		{"id": "sec_cpu_1", "doc_id": "doc_cpu_intro", "content": "La CPU contiene la ALU y la unidad de control."},
		{"id": "sec_cpu_2", "doc_id": "doc_cpu_intro", "content": "Los registros almacenan datos temporales."},
		{"id": "sec_alg_1", "doc_id": "doc_alg_intro", "content": "Complejidad: analiza tiempo y espacio."},
		{"id": "sec_db_1", "doc_id": "doc_db_intro", "content": "Modelo relacional y SQL como lenguaje declarativo."},
	]

	exercises: List[Dict[str, Any]] = [
		{
			"id": "ex_cpu_1",
			"task": "¿Qué es una CPU?",
			"answer": "Es la unidad central de procesamiento que ejecuta instrucciones.",
			"difficulty": 0.2,
			"topic_id": "topic_cpu",
		},
		{
			"id": "ex_cpu_2",
			"task": "Nombra dos componentes principales de la CPU.",
			"answer": "La ALU y la unidad de control.",
			"difficulty": 0.4,
			"topic_id": "topic_cpu",
		},
		{
			"id": "ex_alg_1",
			"task": "Define algoritmo.",
			"answer": "Conjunto finito de pasos para resolver un problema.",
			"difficulty": 0.2,
			"topic_id": "topic_alg",
		},
		{
			"id": "ex_db_1",
			"task": "¿Qué es SQL?",
			"answer": "Un lenguaje declarativo para gestionar datos en bases de datos relacionales.",
			"difficulty": 0.3,
			"topic_id": "topic_db",
		},
	]

	# Upsert topics
	for t in topics:
		run_query(
			"MERGE (x:Topic {id: $id}) SET x.nombre = $nombre",
			t,
		)

	# Upsert documents and relationships
	for d in docs:
		run_query(
			"""
			MATCH (t:Topic {id: $topic_id})
			MERGE (d:Document {id: $id})
			SET d.nombre = $nombre, d.content = $content
			MERGE (d)-[:BELONGS_TO]->(t)
			""",
			d,
		)

	# Upsert sections
	for s in sections:
		run_query(
			"""
			MATCH (d:Document {id: $doc_id})
			MERGE (s:Section {id: $id})
			SET s.content = $content
			MERGE (d)-[:HAS_SECTION]->(s)
			""",
			s,
		)

	# Upsert exercises
	for e in exercises:
		run_query(
			"""
			MATCH (t:Topic {id: $topic_id})
			MERGE (e:Exercise {id: $id})
			SET e.task = $task, e.answer = $answer, e.difficulty = $difficulty
			MERGE (e)-[:BELONGS_TO]->(t)
			""",
			e,
		)


def main() -> None:
	cfg = get_config()
	if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
		raise SystemExit("Missing Neo4j config in environment")
	apply_constraints()
	ensure_vector_indexes()
	seed()
	print("Seeding complete.")


if __name__ == "__main__":
	main()


