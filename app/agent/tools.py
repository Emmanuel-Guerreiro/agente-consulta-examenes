from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
from datetime import date

from neo4j.exceptions import Neo4jError

from app.config import get_config
from app.db.neo4j_client import run_query
from app.embeddings.ollama_embeddings import OllamaEmbeddingClient
from app.background.knowledge import update_student_topic_level
import json

_embed = OllamaEmbeddingClient()


def _cosine(a: List[float], b: List[float]) -> float:
	dot = sum(x * y for x, y in zip(a, b))
	norm_a = math.sqrt(sum(x * x for x in a))
	norm_b = math.sqrt(sum(y * y for y in b))
	if norm_a == 0 or norm_b == 0:
		return 0.0
	return dot / (norm_a * norm_b)


def ensure_vector_indexes() -> None:
	"""
	Create vector indexes if supported by the DB. Uses detected embedding dimension.
	Tries Aura-style key names first; falls back to legacy config keys if needed.
	"""
	dimension = _embed.detect_dimension()
	indexes = [
		("topic_vector", "Topic", "vector"),
		("document_vector", "Document", "vector"),
		("section_vector", "Section", "vector"),
		("exercise_vector", "Exercise", "vector"),
	]
	for name, label, prop in indexes:
		# Aura-style config
		cypher = f"""
		CREATE VECTOR INDEX {name} IF NOT EXISTS FOR (n:{label})
		ON (n.{prop})
		OPTIONS {{
			indexConfig: {{
				`vector.dimensions`: $dim,
				`vector.similarity_function`: 'cosine'
			}}
		}}
		"""
		try:
			run_query(cypher, {"dim": dimension})
			continue
		except Neo4jError:
			# fallback to legacy key names
			legacy_cypher = f"""
			CREATE VECTOR INDEX {name} IF NOT EXISTS FOR (n:{label})
			ON (n.{prop})
			OPTIONS {{
				indexConfig: {{
					dimension: $dim,
					similarityFunction: 'cosine'
				}}
			}}
			"""
			try:
				run_query(legacy_cypher, {"dim": dimension})
			except Neo4jError:
				# Ignore if not supported; the app will fall back to in-app similarity.
				pass


def vector_search_documents(question: str, top_k: int = 5) -> List[Dict[str, Any]]:
	"""
	Returns a list of documents with optional sections:
	[{id, nombre, content, score, sections: [{id, content}]}]
	"""
	cfg = get_config()
	q_vec = _embed.embed(question)

	results: List[Tuple[str, float]] = []

	use_index = cfg.use_vector_index
	if use_index is None:
		# Auto-detect by attempting a vector query
		use_index = True

	if use_index:
		try:
			cypher = """
			CALL db.index.vector.queryNodes('document_vector', $k, $vec)
			YIELD node, score
			RETURN node.id AS id, score
			"""
			records = run_query(cypher, {"k": top_k, "vec": q_vec})
			results = [(r["id"], r["score"]) for r in records]
		except Neo4jError:
			# Fallback to in-app similarity
			results = []

	if not results:
		# in-app similarity: fetch docs with vectors and compute
		cypher = """
		MATCH (d:Document)
		WHERE exists(d.vector) AND d.vector IS NOT NULL
		RETURN d.id AS id, d.vector AS vec
		"""
		records = run_query(cypher, {})
		candidates: List[Tuple[str, float]] = []
		for r in records:
			doc_id = r["id"]
			vec = r["vec"]
			sim = _cosine(q_vec, vec)
			candidates.append((doc_id, sim))
		candidates.sort(key=lambda x: x[1], reverse=True)
		results = candidates[:top_k]

	if not results:
		return []

	doc_ids = [doc_id for doc_id, _ in results]
	cypher = """
	MATCH (d:Document) WHERE d.id IN $ids
	OPTIONAL MATCH (d)-[:HAS_SECTION]->(s:Section)
	RETURN d.id AS id, d.nombre AS nombre, d.content AS content, collect({id: s.id, content: s.content}) AS sections
	"""
	records = run_query(cypher, {"ids": doc_ids})
	doc_map: Dict[str, Dict[str, Any]] = {}
	for r in records:
		doc_map[r["id"]] = {
			"id": r["id"],
			"nombre": r.get("nombre") or "",
			"content": r.get("content") or "",
			"sections": [s for s in r["sections"] if s["id"] is not None],
		}

	# attach scores preserving order
	out: List[Dict[str, Any]] = []
	for doc_id, score in results:
		if doc_id in doc_map:
			item = doc_map[doc_id]
			item["score"] = float(score)
			out.append(item)
	return out


def cypher_query_tool(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
	records = run_query(query, params or {})
	return [dict(r) for r in records]

def vector_search_sections(question: str, top_k: int = 8) -> List[Dict[str, Any]]:
	"""
	Returns a list of sections and their parent document:
	[{id, content, parent_id, parent_nombre, score}]
	"""
	cfg = get_config()
	q_vec = _embed.embed(question)

	results: List[Tuple[str, float]] = []

	use_index = cfg.use_vector_index
	if use_index is None:
		use_index = True

	if use_index:
		try:
			cypher = """
			CALL db.index.vector.queryNodes('section_vector', $k, $vec)
			YIELD node, score
			RETURN node.id AS id, score
			"""
			records = run_query(cypher, {"k": top_k, "vec": q_vec})
			results = [(r["id"], r["score"]) for r in records]
		except Neo4jError:
			results = []

	if not results:
		cypher = """
		MATCH (s:Section)
		WHERE exists(s.vector) AND s.vector IS NOT NULL
		RETURN s.id AS id, s.vector AS vec
		"""
		records = run_query(cypher, {})
		candidates: List[Tuple[str, float]] = []
		for r in records:
			sec_id = r["id"]
			vec = r["vec"]
			sim = _cosine(q_vec, vec)
			candidates.append((sec_id, sim))
		candidates.sort(key=lambda x: x[1], reverse=True)
		results = candidates[:top_k]

	if not results:
		return []

	sec_ids = [sid for sid, _ in results]
	cypher = """
	MATCH (s:Section) WHERE s.id IN $ids
	OPTIONAL MATCH (d:Document)-[:HAS_SECTION]->(s)
	RETURN s.id AS id, s.content AS content, d.id AS parent_id, d.nombre AS parent_nombre
	"""
	records = run_query(cypher, {"ids": sec_ids})
	sec_map: Dict[str, Dict[str, Any]] = {}
	for r in records:
		sec_map[r["id"]] = {
			"id": r["id"],
			"content": r.get("content") or "",
			"parent_id": r.get("parent_id"),
			"parent_nombre": r.get("parent_nombre") or "",
		}
	out: List[Dict[str, Any]] = []
	for sec_id, score in results:
		if sec_id in sec_map:
			item = sec_map[sec_id]
			item["score"] = float(score)
			out.append(item)
	return out

def gather_sources_for_summary(query: str, k_docs: int = 5, k_sections: int = 8, max_sources: int = 5) -> List[Dict[str, Any]]:
	"""
	Gathers candidate sources from documents and sections, and deduplicates:
	- If both a section and its parent document match, keep the section and drop the doc.
	Returns entries: [{type, id, title, content, score}]
	"""
	doc_hits = vector_search_documents(query, top_k=k_docs)
	sec_hits = vector_search_sections(query, top_k=k_sections)

	# Build sets to drop parent docs when a section hit exists
	parent_doc_ids = set([s["parent_id"] for s in sec_hits if s.get("parent_id")])
	sources: List[Dict[str, Any]] = []

	# Include sections
	for s in sec_hits:
		if not s.get("content"):
			continue
		sources.append({
			"type": "section",
			"id": s["id"],
			"title": s.get("parent_nombre") or f"Sección {s['id']}",
			"content": s["content"],
			"score": float(s.get("score") or 0.0),
		})

	# Include documents except those that are parents of matched sections
	for d in doc_hits:
		if d["id"] in parent_doc_ids:
			continue
		content = (d.get("content") or "").strip()
		if not content:
			continue
		sources.append({
			"type": "document",
			"id": d["id"],
			"title": d.get("nombre") or f"Documento {d['id']}",
			"content": content,
			"score": float(d.get("score") or 0.0),
		})

	# Rank by score desc and truncate
	sources.sort(key=lambda x: x["score"], reverse=True)
	return sources[:max_sources]

def find_topic_by_text(text: str) -> Optional[Dict[str, Any]]:
	"""
	Find the most relevant Topic for the given text using vector search (index if available, else in-app).
	Returns {id, nombre, score} or None.
	"""
	cfg = get_config()
	q_vec = _embed.embed(text)
	use_index = cfg.use_vector_index
	if use_index is None:
		use_index = True
	# Try vector index
	if use_index:
		try:
			cypher = """
			CALL db.index.vector.queryNodes('topic_vector', 1, $vec)
			YIELD node, score
			RETURN node.id AS id, node.nombre AS nombre, score
			"""
			records = run_query(cypher, {"vec": q_vec})
			first = records[0] if records else None
			if first:
				return {"id": first["id"], "nombre": first.get("nombre") or "", "score": float(first["score"])}
		except Neo4jError:
			pass
	# Fallback in-app cosine
	cypher = """
	MATCH (t:Topic)
	WHERE exists(t.vector) AND t.vector IS NOT NULL
	RETURN t.id AS id, t.nombre AS nombre, t.vector AS vec
	"""
	candidates: List[Tuple[str, float, str]] = []
	for r in run_query(cypher, {}):
		vec = r["vec"]
		sim = _cosine(q_vec, vec)
		candidates.append((r["id"], sim, r.get("nombre") or ""))
	if not candidates:
		return None
	candidates.sort(key=lambda x: x[1], reverse=True)
	top = candidates[0]
	return {"id": top[0], "nombre": top[2], "score": float(top[1])}


def get_student_knowledge(legajo: str, topic_term: Optional[str] = None) -> List[Dict[str, Any]]:
	"""
	Returns knowledge levels for topics where the student has a KNOWS relation.
	Optional topic_term can match by exact id or case-insensitive nombre.
	"""
	cypher = """
	MATCH (s:Student {legajo: $legajo})-[r:KNOWS]->(t:Topic)
	WHERE $term IS NULL OR t.id = $term OR toLower(t.nombre) = toLower($term)
	RETURN t.id AS topic_id, t.nombre AS nombre, r.level AS level
	ORDER BY level DESC
	"""
	records = run_query(cypher, {"legajo": legajo, "term": topic_term})
	return [dict(r) for r in records]

def recommend_exercises(legajo: str, topic_text: str, limit: int = 5) -> Dict[str, Any]:
	"""
	Recommend exercises for a topic near the student's knowledge level (±0.3).
	Fallback to above-level exercises if none in range.
	Returns {ok, topic_id, topic_nombre, level, exercises: [{id, task, difficulty}]}
	"""
	topic = find_topic_by_text(topic_text)
	if not topic:
		return {"ok": False, "error": "No se encontró un tema relacionado."}
	topic_id = topic["id"]
	topic_nombre = topic.get("nombre") or ""

	# Fetch student level; default to 0.0 if no relation
	cypher_level = """
	OPTIONAL MATCH (s:Student {legajo: $legajo})-[r:KNOWS]->(t:Topic {id: $tid})
	RETURN coalesce(r.level, 0.0) AS level
	"""
	records = run_query(cypher_level, {"legajo": legajo, "tid": topic_id})
	level = float(records[0]["level"]) if records else 0.0

	min_level = max(0.0, level - 0.4)
	max_level = min(1.0, level + 0.4)

	print(f"Will find exercises for topic {topic_id} with level within {min_level} to {max_level} and level {level}")
    
	# Primary: within ±0.3
	cypher_primary = """
	MATCH (t:Topic {id: $tid})<-[:BELONGS_TO]-(e:Exercise)
	WITH e, $level AS lvl, toFloat(e.difficulty) AS diff
	WHERE diff >= $min AND diff <= $max
	RETURN e.id AS id, e.task AS task, diff AS difficulty
	ORDER BY abs(diff - lvl) ASC
	LIMIT toInteger($limit)
	"""
	exercises = [
		dict(r)
		for r in run_query(
			cypher_primary,
			{"tid": topic_id, "min": min_level, "max": max_level, "level": level, "limit": int(limit)},
		)
	]

	# Fallback: strictly above student level
	if not exercises:
		cypher_fallback = """
		MATCH (t:Topic {id: $tid})<-[:BELONGS_TO]-(e:Exercise)
		WITH e, toFloat(e.difficulty) AS diff
		WHERE diff > $level
		RETURN e.id AS id, e.task AS task, diff AS difficulty
		ORDER BY diff ASC
		LIMIT toInteger($limit)
		"""
		exercises = [
			dict(r)
			for r in run_query(cypher_fallback, {"tid": topic_id, "level": level, "limit": int(limit)})
		]

	return {
		"ok": True,
		"topic_id": topic_id,
		"topic_nombre": topic_nombre,
		"level": level,
		"exercises": exercises,
	}

def build_summarizer_prompt(query: str, sources: List[Dict[str, Any]]) -> str:
	parts = [
		"Eres un asistente docente. Redacta un resumen claro y conciso en español (150–250 palabras).",
		"Usa exclusivamente la información de las fuentes proporcionadas; no inventes datos.",
		"Incluye: breve definición/contexto, puntos clave, y 1–2 ejemplos si están presentes.",
		"Cita los títulos de las fuentes entre paréntesis cuando corresponda.",
		"",
		f"Tema de la solicitud: {query}",
		"",
		"Fuentes:",
	]
	for i, s in enumerate(sources, start=1):
		title = s.get("title") or (s["type"].title() + " " + s["id"])
		content = s.get("content") or ""
		parts.append(f"[{i}] {title}\n{content}")
	parts.append("")
	parts.append("Escribe el resumen ahora, en un bloque coherente.")
	return "\n".join(parts)

def build_validator_prompt(query: str, sources: List[Dict[str, Any]], draft: str) -> str:
	parts = [
		"Eres un verificador estricto. Evalúa si el resumen es relevante, fiel a las fuentes y claro.",
		"Responde SOLO en JSON con el formato: {\"valid\": true|false, \"feedback\": \"...\"}",
		"Evalúa: relevancia al tema, fundamentación en fuentes, coherencia/claridad, longitud (150–250 palabras).",
		"",
		f"Tema: {query}",
		"",
		"Fuentes (para verificación):",
	]
	for i, s in enumerate(sources, start=1):
		title = s.get("title") or (s["type"].title() + " " + s["id"])
		content = s.get("content") or ""
		parts.append(f"[{i}] {title}\n{content}")
	parts += ["", "Resumen propuesto:", draft, "", "JSON:"]
	return "\n".join(parts)

def build_regenerator_prompt(query: str, sources: List[Dict[str, Any]], draft: str, feedback: str) -> str:
	parts = [
		"Eres un asistente docente. Regenera el resumen corrigiendo los problemas señalados.",
		"Usa SOLO la información de las fuentes, manteniendo 150–250 palabras y claridad.",
		"Incluye citas breves con los títulos entre paréntesis cuando apoyen afirmaciones específicas.",
		"",
		f"Tema: {query}",
		"",
		"Feedback del validador:",
		feedback,
		"",
		"Fuentes:",
	]
	for i, s in enumerate(sources, start=1):
		title = s.get("title") or (s["type"].title() + " " + s["id"])
		content = s.get("content") or ""
		parts.append(f"[{i}] {title}\n{content}")
	parts += ["", "Borrador original:", draft, "", "Regenera el resumen:"]
	return "\n".join(parts)

def summarize_with_validation(llm, query: str, max_sources: int = 5) -> str:
	sources = gather_sources_for_summary(query, max_sources=max_sources)
	if not sources:
		return "No encontré material suficiente para un resumen."
	# Draft
	p_sum = build_summarizer_prompt(query, sources)
	draft = llm.invoke(p_sum)
	# Validate
	p_val = build_validator_prompt(query, sources, draft)
	review = llm.invoke(p_val)
	valid = True
	feedback = ""
	try:
		start = review.find("{")
		end = review.rfind("}")
		obj = json.loads(review[start : end + 1]) if start != -1 and end != -1 else {}
		if isinstance(obj.get("valid"), bool):
			valid = obj["valid"]
		feedback = str(obj.get("feedback") or "").strip()
	except Exception:
		# If parsing fails, assume valid and return first draft
		valid = True
	if valid:
		sources_str = ", ".join([s.get("title") or s["id"] for s in sources])
		return f"{draft}\n\nFuentes: {sources_str}"
	# Regenerate
	p_reg = build_regenerator_prompt(query, sources, draft, feedback or "Mejora claridad y grounding.")
	draft2 = llm.invoke(p_reg)
	sources_str = ", ".join([s.get("title") or s["id"] for s in sources])
	return f"{draft2}\n\nFuentes: {sources_str}\nNota: este resumen se regeneró tras una verificación adicional; podría contener imprecisiones."


def get_topic_summaries(legajo: str, topic_term: Optional[str] = None) -> List[Dict[str, Any]]:
	"""
	Aggregates per-topic session stats for the student:
	sessions count, answers count, avg_conf, correctness_rate, last_activity.
	"""
	cypher = """
	MATCH (s:Student {legajo:$legajo})-[:HAS_SESSION]->(ss:StudySession)
	MATCH (ss)-[:CONSULTED_TOPIC]->(t:Topic)
	WHERE $term IS NULL OR t.id = $term OR toLower(t.nombre) = toLower($term)
	OPTIONAL MATCH (ss)-[:HAS_ANSWER]->(a:Answer)-[:ANSWERS]->(:Exercise)-[:BELONGS_TO]->(t)
	RETURN t.id AS topic_id, t.nombre AS nombre,
	       count(DISTINCT ss) AS sessions,
	       count(a) AS answers,
	       coalesce(avg(a.confidence),0.0) AS avg_conf,
	       coalesce(avg(CASE WHEN a.confidence>0.7 THEN 1.0 ELSE 0.0 END),0.0) AS correctness_rate,
	       toString(coalesce(max(ss.startedAt), datetime())) AS last_activity
	ORDER BY sessions DESC, answers DESC
	"""
	records = run_query(cypher, {"legajo": legajo, "term": topic_term})
	return [dict(r) for r in records]

def grade_answer(legajo: str, exercise_id: str, user_answer: str) -> Dict[str, Any]:
	"""
	Grades an answer via embedding similarity to the stored gold answer.
	Creates Answer node and relation, updates knowledge level.
	"""
	# Fetch exercise, its topic, and gold answer
	cypher = """
	MATCH (e:Exercise {id: $eid})-[:BELONGS_TO]->(t:Topic)
	RETURN e.id AS id, e.answer AS gold, t.id AS topic_id
	"""
	records = run_query(cypher, {"eid": exercise_id})
	rec = records[0] if records else None
	if not rec:
		return {"ok": False, "error": "Exercise not found"}
	gold = rec["gold"] or ""
	topic_id = rec["topic_id"]

	u_vec = _embed.embed(user_answer)
	g_vec = _embed.embed(gold) if gold else []

	confidence = 0.0
	if g_vec:
		confidence = max(0.0, min(1.0, _cosine(u_vec, g_vec)))

	# Store Answer
	cypher_create = """
	MERGE (s:Student {legajo: $legajo})
	WITH s
	MATCH (e:Exercise {id: $eid})-[:BELONGS_TO]->(t:Topic)
	CREATE (a:Answer {id: randomUUID(), content: $content, confidence: $confidence})
	CREATE (a)-[:ANSWERS]->(e)
	MERGE (s)-[:HAS_SESSION]->(ss:StudySession {id: $sid})
	ON CREATE SET ss.startedAt = datetime()
	MERGE (ss)-[:CONSULTED_TOPIC]->(t)
	CREATE (ss)-[:HAS_ANSWER]->(a)
	RETURN a.id AS id
	"""
	run_query(
		cypher_create,
		{
			"legajo": legajo,
			"eid": exercise_id,
			"content": user_answer,
			"confidence": float(confidence),
			"sid": f"{date.today().isoformat()}-{legajo}",
		},
	)

	# Update knowledge level in background (synchronous call here)
	new_level = update_student_topic_level(legajo, topic_id, float(confidence))

	return {"ok": True, "confidence": float(confidence), "new_level": new_level, "topic_id": topic_id}


