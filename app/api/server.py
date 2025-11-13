from __future__ import annotations

import sys
from typing import Dict, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import os

# Add parent directory to path to ensure imports work
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
	sys.path.insert(0, project_root)

from app.config import get_config
from app.agent.agent import initialize_agent, build_llm, upsert_student, ensure_vector_indexes
from langchain_ollama import OllamaLLM

# Store agent instances per legajo (in production, use Redis or similar)
agent_instances: Dict[str, callable] = {}
llm_instance: Optional[OllamaLLM] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
	"""Initialize the LLM and ensure vector indexes on startup."""
	import traceback
	try:
		cfg = get_config()
		if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
			raise RuntimeError("Missing Neo4j config. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in .env")
		
		print("Ensuring vector indexes...")
		ensure_vector_indexes()
		
		print("Building LLM...")
		global llm_instance
		llm_instance = build_llm()
		
		# Test LLM connection
		print("Testing LLM connection...")
		test_response = llm_instance.invoke("Test")
		print(f"LLM test response: {test_response[:50]}...")
		
		print("Server initialized successfully")
	except Exception as e:
		error_traceback = traceback.format_exc()
		print(f"ERROR during server initialization: {error_traceback}", file=sys.stderr)
		raise
	yield
	# Cleanup code here if needed


app = FastAPI(title="Agente de Consulta de Exámenes", lifespan=lifespan)


class ChatMessage(BaseModel):
	legajo: str
	message: str


class ChatResponse(BaseModel):
	response: str
	legajo: str


# Serve static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
	app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def read_root():
	"""Serve the chat interface."""
	html_path = os.path.join(static_dir, "index.html")
	if os.path.exists(html_path):
		with open(html_path, "r", encoding="utf-8") as f:
			return HTMLResponse(content=f.read())
	return HTMLResponse(content="<h1>Error: index.html not found</h1>")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(message: ChatMessage):
	"""Handle chat messages."""
	import traceback
	
	if not message.legajo or not message.message:
		raise HTTPException(status_code=400, detail="Legajo and message are required")
	
	try:
		# Ensure student exists
		upsert_student(message.legajo)
		
		# Get or create agent instance for this legajo
		if message.legajo not in agent_instances:
			if llm_instance is None:
				raise HTTPException(status_code=500, detail="LLM not initialized")
			agent_instances[message.legajo] = initialize_agent(message.legajo, llm_instance)
		
		# Process message
		handle_query = agent_instances[message.legajo]
		response_text = handle_query(message.message)
		
		# Ensure response_text is a string
		if response_text is None:
			response_text = "Error: No se recibió respuesta del agente"
		elif not isinstance(response_text, str):
			response_text = str(response_text)
		
		return ChatResponse(response=response_text, legajo=message.legajo)
	except HTTPException:
		raise
	except Exception as e:
		# Log the full traceback for debugging
		error_traceback = traceback.format_exc()
		error_msg = str(e)
		print(f"Error processing message: {error_traceback}", file=sys.stderr)
		# Return a user-friendly error message (truncate traceback for security)
		# but log the full traceback to console
		raise HTTPException(
			status_code=500,
			detail=f"Error procesando el mensaje: {error_msg}"
		)


@app.get("/api/health")
async def health():
	"""Health check endpoint."""
	return {"status": "ok"}


if __name__ == "__main__":
	import uvicorn
	uvicorn.run(app, host="0.0.0.0", port=8000)

