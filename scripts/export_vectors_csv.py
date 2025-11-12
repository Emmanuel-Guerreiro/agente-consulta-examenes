from __future__ import annotations

import os
import sys
from typing import List, Tuple

import pandas as pd
import typer

# Ensure project root is on sys.path for 'app' imports when running as a script
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from app.db.neo4j_client import run_query


app = typer.Typer(add_completion=False)


def _ensure_out_dir(out_dir: str) -> None:
	if not os.path.isdir(out_dir):
		os.makedirs(out_dir, exist_ok=True)


def _rows_for_document() -> List[Tuple[str, str]]:
	cypher = """
	MATCH (d:Document)
	RETURN d.id AS id, d.nombre AS nombre, d.content AS content
	"""
	rows: List[Tuple[str, str]] = []
	for r in run_query(cypher, {}):
		_id = r["id"]
		nombre = r.get("nombre") or ""
		content = r.get("content") or ""
		text = (nombre + ("\n\n" if nombre and content else "") + content).strip()
		if _id and text:
			rows.append((_id, text))
	return rows


def _rows_for_section() -> List[Tuple[str, str]]:
	cypher = """
	MATCH (s:Section)
	RETURN s.id AS id, s.content AS content
	"""
	rows: List[Tuple[str, str]] = []
	for r in run_query(cypher, {}):
		_id = r["id"]
		content = (r.get("content") or "").strip()
		if _id and content:
			rows.append((_id, content))
	return rows


def _rows_for_exercise() -> List[Tuple[str, str]]:
	cypher = """
	MATCH (e:Exercise)
	RETURN e.id AS id, e.task AS task
	"""
	rows: List[Tuple[str, str]] = []
	for r in run_query(cypher, {}):
		_id = r["id"]
		task = (r.get("task") or "").strip()
		if _id and task:
			rows.append((_id, task))
	return rows


def _rows_for_topic() -> List[Tuple[str, str]]:
	cypher = """
	MATCH (t:Topic)
	RETURN t.id AS id, t.nombre AS nombre
	"""
	rows: List[Tuple[str, str]] = []
	for r in run_query(cypher, {}):
		_id = r["id"]
		nombre = (r.get("nombre") or "").strip()
		if _id and nombre:
			rows.append((_id, nombre))
	return rows


def _write_csv(rows: List[Tuple[str, str]], out_path: str) -> None:
	df = pd.DataFrame(rows, columns=["id", "content"])
	df.to_csv(out_path, index=False)


@app.command()
def main(
	out_dir: str = typer.Option("data", help="Output directory for CSV files"),
	labels: List[str] = typer.Option(
		None,
		"--label",
		help="Labels to export: Document, Section, Exercise, Topic (repeatable). Defaults to all.",
	),
) -> None:
	"""
	Export current nodes that can be vectorized into CSV files with columns: id, content.
	File names: <label>.csv (lowercase), e.g., document.csv
	"""
	labels_to_export = [l.strip() for l in labels] if labels else ["Document", "Section", "Exercise", "Topic"]
	label_set = {l.lower() for l in labels_to_export}

	_ensure_out_dir(out_dir)

	if "document".lower() in label_set:
		rows = _rows_for_document()
		_write_csv(rows, os.path.join(out_dir, "document.csv"))
	if "section".lower() in label_set:
		rows = _rows_for_section()
		_write_csv(rows, os.path.join(out_dir, "section.csv"))
	if "exercise".lower() in label_set:
		rows = _rows_for_exercise()
		_write_csv(rows, os.path.join(out_dir, "exercise.csv"))
	if "topic".lower() in label_set:
		rows = _rows_for_topic()
		_write_csv(rows, os.path.join(out_dir, "topic.csv"))

	typer.echo(f"Export completed to: {out_dir}")


if __name__ == "__main__":
	typer.run(main)


