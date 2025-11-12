from __future__ import annotations

import os
import sys
from typing import List, Optional

import pandas as pd
import typer
from tqdm import tqdm

# Ensure project root is on sys.path for 'app' imports when running as a script
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from app.db.neo4j_client import run_query
from app.embeddings.ollama_embeddings import OllamaEmbeddingClient
from app.config import get_config


app = typer.Typer(add_completion=False)
_embed = OllamaEmbeddingClient()


def _update_node_vector(label: str, node_id: str, vector: List[float], id_type: str, id_field: str, vector_prop: str) -> None:
	if id_type == "property":
		cypher = f"MATCH (n:{label} {{{id_field}: $id}}) SET n.{vector_prop} = $vec"
		run_query(cypher, {"id": node_id, "vec": vector})
	else:
		# internal id
		cypher = f"MATCH (n) WHERE id(n) = toInteger($id) AND '{label}' IN labels(n) SET n.{vector_prop} = $vec"
		run_query(cypher, {"id": node_id, "vec": vector})


@app.command()
def main(
	label: str = typer.Option(..., help="Target label: Document|Section|Exercise|Topic"),
	csv: str = typer.Option(..., help="Path to CSV file"),
	id_field: str = typer.Option("id", help="CSV column for node id (or internal id)"),
	text_field: Optional[List[str]] = typer.Option(None, help="CSV column(s) to concatenate as text", rich_help_panel="Text"),
	id_type: str = typer.Option("property", help="Identifier type: property|internal"),
	vector_prop: str = typer.Option("vector", help="Node property to store the vector"),
	batch_size: int = typer.Option(32, help="Client-side batch size for embedding calls"),
	dry_run: bool = typer.Option(False, help="Only print generated Cypher"),
) -> None:
	cfg = get_config()
	if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
		print("Missing Neo4j config. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD", file=sys.stderr)
		raise typer.Exit(code=1)
	if text_field is None or len(text_field) == 0:
		print("At least one --text-field is required", file=sys.stderr)
		raise typer.Exit(code=1)

	df = pd.read_csv(csv)
	if id_field not in df.columns:
		print(f"CSV is missing id_field '{id_field}'", file=sys.stderr)
		raise typer.Exit(code=1)
	for tf in text_field:
		if tf not in df.columns:
			print(f"CSV is missing text_field '{tf}'", file=sys.stderr)
			raise typer.Exit(code=1)

	def join_text(row) -> str:
		return "\n\n".join(str(row[tf]) for tf in text_field if pd.notna(row[tf]))

	texts = [join_text(row) for _, row in df.iterrows()]
	ids = [str(row[id_field]) for _, row in df.iterrows()]

	# Embed in small batches (Ollama embeds one by one under the hood)
	vectors: List[List[float]] = []
	for i in tqdm(range(0, len(texts), batch_size), desc="Embedding"):
		chunk = texts[i : i + batch_size]
		for t in chunk:
			vectors.append(_embed.embed(t))

	if dry_run:
		for node_id, vec in zip(ids, vectors):
			if id_type == "property":
				print(f"MATCH (n:{label} {{{id_field}: '{node_id}'}}) SET n.{vector_prop} = [..{len(vec)} dims..];")
			else:
				print(f"MATCH (n) WHERE id(n) = {node_id} AND '{label}' IN labels(n) SET n.{vector_prop} = [..{len(vec)} dims..];")
		return

	for node_id, vec in tqdm(list(zip(ids, vectors)), desc="Updating", total=len(ids)):
		_update_node_vector(label, node_id, vec, id_type, id_field, vector_prop)

	print(f"Updated {len(ids)} {label} node(s) with vectors in property '{vector_prop}'.")


if __name__ == "__main__":
	typer.run(main)


