import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class AppConfig:
	neo4j_uri: str
	neo4j_user: str
	neo4j_password: str
	ollama_base_url: str = "http://localhost:11434"
	ollama_model: str = "qwen2.5:7b-instruct"
	use_vector_index: Optional[bool] = None


def _parse_bool(value: Optional[str]) -> Optional[bool]:
	if value is None or value == "":
		return None
	val = value.strip().lower()
	if val in ("1", "true", "yes", "y", "on"):
		return True
	if val in ("0", "false", "no", "n", "off"):
		return False
	return None


def get_config() -> AppConfig:
	return AppConfig(
		neo4j_uri=os.getenv("NEO4J_URI", ""),
		neo4j_user=os.getenv("NEO4J_USER", ""),
		neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
		ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
		ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
		use_vector_index=_parse_bool(os.getenv("USE_VECTOR_INDEX")),
	)


