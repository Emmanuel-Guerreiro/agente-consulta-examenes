from __future__ import annotations

import json
from typing import List, Sequence

import requests

from app.config import get_config


EMBEDDING_MODEL = "mxbai-embed-large"


class OllamaEmbeddingClient:
	def __init__(self, base_url: str | None = None, model: str = EMBEDDING_MODEL) -> None:
		cfg = get_config()
		self.base_url = base_url or cfg.ollama_base_url
		self.model = model
		self._endpoint = f"{self.base_url.rstrip('/')}/api/embeddings"

	def embed(self, text: str) -> List[float]:
		payload = {"model": self.model, "prompt": text}
		resp = requests.post(self._endpoint, data=json.dumps(payload), timeout=60)
		resp.raise_for_status()
		data = resp.json()
		# API returns: {"embedding": [..]}
		return data["embedding"]

	def embed_many(self, texts: Sequence[str]) -> List[List[float]]:
		# Ollama API embeds one text per call; batch on client side
		return [self.embed(t) for t in texts]

	def detect_dimension(self) -> int:
		vec = self.embed("dimension probe")
		return len(vec)


