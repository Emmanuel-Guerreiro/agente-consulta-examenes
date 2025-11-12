from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterable, Optional

from neo4j import GraphDatabase, Driver, Session

from app.config import get_config


_driver: Optional[Driver] = None


def get_driver() -> Driver:
	global _driver
	if _driver is None:
		cfg = get_config()
		_driver = GraphDatabase.driver(
			cfg.neo4j_uri,
			auth=(cfg.neo4j_user, cfg.neo4j_password),
		)
	return _driver


@contextmanager
def get_session(database: Optional[str] = None) -> Iterable[Session]:
	driver = get_driver()
	session = driver.session(database=database) if database else driver.session()
	try:
		yield session
	finally:
		session.close()


def run_query(cypher: str, parameters: Optional[Dict[str, Any]] = None) -> Any:
	with get_session() as session:
		result = session.run(cypher, parameters or {})
		# Materialize results before closing the session to avoid ResultConsumedError
		return list(result)


def close_driver() -> None:
	global _driver
	if _driver is not None:
		_driver.close()
		_driver = None


