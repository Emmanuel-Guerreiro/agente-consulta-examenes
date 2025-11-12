from __future__ import annotations

from typing import Optional

from app.db.neo4j_client import run_query


def _clamp(value: float, min_value: float, max_value: float) -> float:
	return max(min_value, min(max_value, value))


def update_student_topic_level(legajo: str, topic_id: str, confidence: float) -> Optional[float]:
	"""
	Adjust Student-[:KNOWS]->Topic.level based on confidence.
	> 0.7 => +0.5, else -0.3, clamped to [0,1]
	Returns the updated level, if any.
	"""
	increment = 0.5 if confidence > 0.7 else -0.3
	cypher = """
	MERGE (s:Student {legajo: $legajo})
	WITH s
	MATCH (t:Topic {id: $topic_id})
	MERGE (s)-[r:KNOWS]->(t)
	ON CREATE SET r.level = 0.0
	WITH r
	SET r.level = CASE
		WHEN $confidence > 0.7 THEN r.level + 0.5
		ELSE r.level - 0.3
	END
	WITH r
	SET r.level = CASE
		WHEN r.level < 0.0 THEN 0.0
		WHEN r.level > 1.0 THEN 1.0
		ELSE r.level
	END
	RETURN r.level AS level
	"""
	res = run_query(
		cypher,
		{"legajo": legajo, "topic_id": topic_id, "confidence": float(confidence)},
	)
	record = res[0] if res else None
	return record["level"] if record else None


