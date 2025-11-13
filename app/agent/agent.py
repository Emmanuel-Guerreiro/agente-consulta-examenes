from __future__ import annotations

import sys
from typing import List

from langchain_ollama import OllamaLLM
import json
from langchain_core.prompts import PromptTemplate

from app.config import get_config
from app.db.neo4j_client import run_query
from app.agent.tools import (
	ensure_vector_indexes,
	vector_search_documents,
	grade_answer,
	get_student_knowledge,
	get_topic_summaries,
	recommend_exercises,
	summarize_with_validation,
)


def upsert_student(legajo: str) -> None:
	cypher = """
	MERGE (s:Student {legajo: $legajo})
	RETURN s.legajo AS legajo
	"""
	run_query(cypher, {"legajo": legajo})


def build_llm() -> OllamaLLM:
	cfg = get_config()
	print(f"Building LLM with model {cfg.ollama_model} and base URL {cfg.ollama_base_url}")
	return OllamaLLM(base_url=cfg.ollama_base_url, model=cfg.ollama_model, temperature=0.7)


def answer_with_rag(llm: OllamaLLM, question: str) -> str:
	docs = vector_search_documents(question, top_k=5)
	context_parts: List[str] = []
	sources: List[str] = []
	for d in docs:
		if d.get("nombre"):
			sources.append(d["nombre"])
		if d.get("content"):
			context_parts.append(f"Doc: {d.get('nombre','')}\n{d['content']}")
		for s in (d.get("sections") or []):
			if s.get("content"):
				context_parts.append(f"Section: {s.get('id','')}\n{s['content']}")
	context = "\n\n".join(context_parts) if context_parts else "No context found."

	template = PromptTemplate(
		input_variables=["question", "context"],
		template=(
			"You are a helpful teaching assistant. Answer concisely using the context.\n"
			"Context:\n{context}\n\n"
			"Question: {question}\n\n"
			"Answer in Spanish. If unsure, say you don't know."
		),
	)
	prompt = template.format(question=question, context=context)
	response = llm.invoke(prompt)
	ref = f"\n\nFuente(s): {', '.join(sources)}" if sources else ""
	return f"{response}{ref}"


def build_router_prompt(legajo: str, user_text: str, history: list[dict] | None = None, has_pending_exercise: bool = False) -> str:
	"""
	Builds the routing prompt for the LLM to select the appropriate tool.
	Returns a single string prompt expecting a strict JSON output: { "tool": "...", "input": "..." }
	"""
	# Get available topics to include in the prompt
	from app.agent.tools import get_all_topics
	available_topics = get_all_topics()
	topic_names = [t["nombre"] for t in available_topics] if available_topics else []
	topics_info = ""
	if topic_names:
		topics_info = f"\n⚠️ TEMAS DISPONIBLES: {', '.join(topic_names)}\n" + \
			"IMPORTANTE: Solo puedes usar estos temas. Si el usuario pide un tema que no está en esta lista, " + \
			"debes usar el tema más cercano de la lista, o informar que el tema no está disponible.\n"
	
	toolspec = (
		"Herramientas disponibles (elige UNA):\n"
		"- knowledge_report: informar nivel(es) de conocimiento. input: nombre o id del tema (vacío para todos). "
		"Si el usuario pide TODOS los temas, usa input vacío.\n"
		"- topic_summary: resumir actividad por tema. input: nombre o id del tema (vacío para todos)\n"
		"- retrieve_docs: recuperar contexto para responder preguntas conceptuales. input: la pregunta\n"
		"- recommend_exercises: recomendar ejercicios para practicar un tema según tu nivel actual. input: texto con el nombre del tema (DEBE ser uno de los temas disponibles)\n"
		"- ask_exercise: proponer un ejercicio concreto para un tema y dejarlo pendiente para corregir. input: texto con el nombre del tema (DEBE ser uno de los temas disponibles)\n"
		"- grade_pending: corregir la respuesta del ejercicio pendiente. input: el texto de la respuesta del usuario\n"
		"- summarize_topic: generar un resumen del tema solicitado usando fuentes recuperadas y validación/regeneración si hiciera falta. input: texto del tema\n"
		"- grade_exercise: (alternativa avanzada) evaluar respuesta de un ejercicio específico. input JSON: {'exercise_id':'...','answer_text':'...'}\n"
	)
	
	pending_warning = ""
	if has_pending_exercise:
		pending_warning = (
			"\n⚠️ IMPORTANTE: Hay un ejercicio pendiente de corrección. "
			"Si el usuario está respondiendo al ejercicio (no está pidiendo explícitamente otro ejercicio), "
			"DEBES usar 'grade_pending'. Solo usa 'ask_exercise' si el usuario EXPLÍCITAMENTE pide un nuevo ejercicio "
			"(por ejemplo: 'dame otro ejercicio', 'quiero practicar SQL', etc.). "
			"Si el usuario simplemente escribe una respuesta o frase relacionada, usa 'grade_pending'.\n"
		)
	
	router_system = (
		f"Eres un asistente que decide qué herramienta usar según la consulta del usuario con legajo {legajo}. "
		"Devuelve EXCLUSIVAMENTE un JSON con dos claves: tool e input. Nada más. "
		"Usa el contexto reciente para resolver referencias (p.ej., 'ahora sobre SQL')."
		+ topics_info
		+ pending_warning
	)
	# Contexto reciente
	ctx_lines: list[str] = []
	if history:
		ctx_lines.append("Contexto reciente (máx 6):")
		for item in history[-6:]:
			u = (item.get("user_prompt") or "").strip()
			t = (item.get("tool_used") or "").strip()
			a = (item.get("agent_response") or "").strip()
			if len(a) > 300:
				a = a[:297] + "..."
			ctx_lines.append(f"- U: {u} | Tool: {t or 'desconocido'} | A: {a}")
		ctx_lines.append("")
	examples = [
		("¿Cuál es mi nivel en CPU?", {"tool": "knowledge_report", "input": "CPU"}),
		("Muéstrame mis niveles en todos los temas", {"tool": "knowledge_report", "input": ""}),
		("Resúmeme mi actividad en Algoritmos", {"tool": "topic_summary", "input": "Algoritmos"}),
		("¿Qué es una CPU?", {"tool": "retrieve_docs", "input": "¿Qué es una CPU?"}),
		("Dame ejercicios sobre CPU", {"tool": "recommend_exercises", "input": "CPU"}),
		("Preguntas para practicar Unidad de procesamiento", {"tool": "recommend_exercises", "input": "Unidad de procesamiento"}),
		("Dame un ejercicio de SQL para practicar", {"tool": "ask_exercise", "input": "SQL"}),
		("Mi respuesta es: Es un lenguaje declarativo para manejar datos", {"tool": "grade_pending", "input": "Es un lenguaje declarativo para manejar datos"}),
		("Hazme un resumen sobre arquitectura de procesadores 8086", {"tool": "summarize_topic", "input": "arquitectura de procesadores 8086"}),
		("Evalúa mi respuesta al ejercicio ex_cpu_1: Es la unidad que ejecuta instrucciones", {"tool": "grade_exercise", "input": {"exercise_id": "ex_cpu_1", "answer_text": "Es la unidad que ejecuta instrucciones"}}),
	]
	ex_str = "\n".join([f"Usuario: {u}\nSalida JSON: {json.dumps(j, ensure_ascii=False)}" for u, j in examples])
	prompt = (
		f"{router_system}\n\n{toolspec}\n\n"
		+ ("\n".join(ctx_lines) if ctx_lines else "")
		+ f"{ex_str}\n\n"
		f"Usuario: {user_text}\nSalida JSON:"
	)
	return prompt


def initialize_agent(legajo: str, llm: OllamaLLM):
	"""
	Initializes the agent runtime for a given student legajo and LLM.
	Returns a callable handle_query(user_text: str) -> str that selects and executes the right tool.
	"""
	# Simple in-memory context for the current CLI session
	pending: dict[str, str] = {"exercise_id": ""}
	history: list[dict] = []
	def tool_knowledge(term: str) -> str:
		term_norm = (term or "").strip() or None
		rows = get_student_knowledge(legajo, term_norm)
		if not rows:
			return "Sin registros de conocimiento."
		lines = [f"{r['nombre']} ({r['topic_id']}): nivel {float(r['level']):.2f}" for r in rows]
		return "\n".join(lines)

	def tool_summary(term: str) -> str:
		term_norm = (term or "").strip() or None
		rows = get_topic_summaries(legajo, term_norm)
		if not rows:
			return "Sin actividad para resumir."
		lines = [
			f"{r['nombre']} ({r['topic_id']}): sesiones {int(r['sessions'])}, "
			f"respuestas {int(r['answers'])}, conf. prom {float(r['avg_conf']):.2f}, "
			f"correctitud {float(r['correctness_rate']):.2f}, última {r['last_activity']}"
			for r in rows
		]
		return "\n".join(lines)

	def tool_grade(payload: str) -> str:
		ex_id = ""
		answer_text = ""
		try:
			data = json.loads(payload)
			ex_id = str(data.get("exercise_id") or "").strip()
			answer_text = str(data.get("answer_text") or "").strip()
		except Exception:
			for line in (payload or "").splitlines():
				if "exercise_id" in line:
					ex_id = line.split(":", 1)[1].strip()
				elif line.lower().startswith("answer") or line.lower().startswith("respuesta"):
					answer_text = line.split(":", 1)[1].strip()
		if not ex_id or not answer_text:
			return "Formato inválido. Proporcione JSON {'exercise_id':'...','answer_text':'...'} o líneas 'exercise_id: ...' y 'answer: ...'."
		res = grade_answer(legajo, ex_id, answer_text)
		if not res.get("ok"):
			return f"Error: {res.get('error')}"
		return f"Confianza: {res['confidence']:.3f}  Nuevo nivel (tema {res['topic_id']}): {res.get('new_level')}"

	def tool_recommend(term: str) -> str:
		res = recommend_exercises(legajo, term, limit=5)
		if not res.get("ok"):
			return res.get("error") or "No se pudo recomendar ejercicios."
		exs = res.get("exercises") or []
		if not exs:
			return f"No hay más ejercicios para tu nivel en el tema {res['topic_nombre']}."
		
		# Format exercises list in a clean, readable way
		exercise_list = f"EJERCICIOS DISPONIBLES - {res['topic_nombre']}\n"
		exercise_list += f"Tu nivel: {float(res['level']):.2f}\n\n"
		
		for i, e in enumerate(exs, 1):
			task_text = e.get('task', '').strip()
			if task_text:
				exercise_list += f"{i}. {task_text}\n"
				exercise_list += f"   Dificultad: {float(e.get('difficulty', 0.0)):.2f} | ID: {e['id']}\n\n"
		
		exercise_list += "Escribe 'Dame un ejercicio de [tema]' para practicar con uno."
		
		return exercise_list

	def tool_ask_exercise(term: str) -> str:
		"""
		Pick one recommended exercise for the topic and store it as pending for grading.
		"""
		# Log the term being used for debugging
		import sys
		if sys.stdout.isatty():
			print(f"[DEBUG] tool_ask_exercise called with term: '{term}'", file=sys.stderr)
		
		# First, verify that the term can be mapped to a valid topic
		from app.agent.tools import get_all_topics, find_topic_by_text
		available_topics = get_all_topics()
		topic_names = [t["nombre"].lower() for t in available_topics]
		
		# Try to find the topic
		res = recommend_exercises(legajo, term, limit=5)
		if not res.get("ok"):
			error_msg = res.get("error") or "No se pudo recomendar ejercicios."
			# Log the error for debugging
			if sys.stdout.isatty():
				print(f"[DEBUG] recommend_exercises failed: {error_msg}", file=sys.stderr)
			return error_msg
		exs = res.get("exercises") or []
		if not exs:
			return f"No hay más ejercicios para tu nivel en el tema {res.get('topic_nombre','') or 'desconocido'}."
		ex = exs[0]
		pending["exercise_id"] = ex["id"]
		
		# Build a well-formatted exercise message with all relevant information
		task_text = ex.get('task', '').strip()
		if not task_text:
			return f"Error: El ejercicio {ex['id']} no tiene un enunciado (task) definido."
		
		# Format exercise with clean, modern structure
		exercise_text = f"EJERCICIO - {res['topic_nombre'].upper()}\n\n"
		exercise_text += f"ENUNCIADO:\n\n"
		exercise_text += f"{task_text}\n\n"
		exercise_text += f"---\n"
		exercise_text += f"Dificultad: {float(ex.get('difficulty', 0.0)):.2f} | Tu nivel: {float(res['level']):.2f} | ID: {ex['id']}\n\n"
		exercise_text += f"Escribe tu respuesta y te la corregire automaticamente."
		
		return exercise_text

	def tool_grade_pending(answer_text: str) -> str:
		"""
		Grade the answer against the last pending exercise, if any.
		"""
		ex_id = pending.get("exercise_id") or ""
		if not ex_id:
			return "No hay un ejercicio pendiente. Pide uno con: \"Dame un ejercicio de <tema>\"."
		res = grade_answer(legajo, ex_id, answer_text.strip())
		# Clear pending after grading
		pending["exercise_id"] = ""
		if not res.get("ok"):
			return f"Error: {res.get('error')}"
		status = "Correcta" if float(res["confidence"]) > 0.7 else "Incorrecta"
		feedback = f"Correccion del ejercicio:\n\n"
		feedback += f"Tu respuesta: {status}\n"
		feedback += f"Confianza: {res['confidence']:.3f}\n"
		feedback += f"Nivel actualizado (tema {res['topic_id']}): {res.get('new_level'):.2f}\n\n"
		feedback += "Ejercicio completado. Si quieres practicar mas, pide otro ejercicio."
		return feedback

	def route_tool(user_text: str) -> tuple[str, str]:
		# CRITICAL: If there's a pending exercise, prioritize grade_pending
		has_pending = pending.get("exercise_id", "").strip() != ""
		
		if has_pending:
			# Check if user is explicitly asking for something else (like "dame otro ejercicio", "cambiar tema", etc.)
			user_lower = user_text.lower().strip()
			
			# List of phrases that indicate user wants a NEW exercise or other action
			explicit_requests = [
				"dame otro", "dame otro ejercicio", "otro ejercicio", "cambiar", "nuevo ejercicio",
				"ejercicio de", "dame un ejercicio", "quiero practicar", "ejercicios sobre", "ejercicios de",
				"dame ejercicios", "lista de ejercicios", "muestrame ejercicios"
			]
			
			# List of question patterns that indicate user is asking a question, not answering
			question_patterns = [
				"que es", "que son", "como funciona", "como se", "cual es", "cuales son",
				"donde", "por que", "porque", "explica", "explicame", "dime sobre",
				"cuenta sobre", "habla de", "resume", "muestra", "consulta"
			]
			
			# Check if it's an explicit request for new exercise
			is_explicit_new_exercise = any(phrase in user_lower for phrase in explicit_requests)
			
			# Check if it's a question (starts with question words or contains question patterns)
			is_question = (
				user_lower.startswith(("que", "como", "cual", "donde", "por que", "porque", "expl", "dime", "cuenta", "habla", "resume", "muestra", "consult")) or
				any(pattern in user_lower for pattern in question_patterns)
			)
			
			# If user is NOT explicitly requesting a new exercise AND not asking a question,
			# treat as answer to pending exercise
			if not is_explicit_new_exercise and not is_question:
				# Definitely treat as answer to pending exercise
				return "grade_pending", user_text
			elif is_explicit_new_exercise:
				# User wants a new exercise, clear pending first
				pending["exercise_id"] = ""
		
		# Route strictly via LLM using recent context
		try:
			prompt = build_router_prompt(legajo, user_text, history, has_pending)
			raw = llm.invoke(prompt)
			if not raw or not isinstance(raw, str):
				# Fallback: if pending, treat as answer
				if has_pending:
					return "grade_pending", user_text
				return "retrieve_docs", user_text
			
			try:
				start = raw.find("{")
				end = raw.rfind("}")
				if start == -1 or end == -1 or start >= end:
					# Fallback: if pending, treat as answer
					if has_pending:
						return "grade_pending", user_text
					return "retrieve_docs", user_text
				
				obj = json.loads(raw[start : end + 1])
				tool_name = str(obj.get("tool") or "").strip()
				tool_input = obj.get("input")
				if isinstance(tool_input, (dict, list)):
					tool_input_str = json.dumps(tool_input, ensure_ascii=False)
				else:
					tool_input_str = str(tool_input or "").strip()
				
				# FINAL SAFETY CHECK: if there's a pending exercise and LLM selected ask_exercise,
				# override it unless user was very explicit
				if has_pending and tool_name == "ask_exercise":
					# Only allow if user was very explicit about wanting a new exercise
					user_lower = user_text.lower()
					very_explicit = any(phrase in user_lower for phrase in [
						"dame otro ejercicio", "otro ejercicio", "nuevo ejercicio",
						"quiero practicar", "ejercicio de"
					])
					if not very_explicit:
						# Override: treat as answer to pending
						return "grade_pending", user_text
				
				if tool_name in {"knowledge_report", "topic_summary", "retrieve_docs", "grade_exercise", "recommend_exercises", "ask_exercise", "grade_pending", "summarize_topic"}:
					return tool_name, tool_input_str
			except (json.JSONDecodeError, KeyError, ValueError) as e:
				# If JSON parsing fails, fall back to retrieve_docs or grade_pending
				import sys
				if sys.stdout.isatty():
					print(f"Warning: Failed to parse LLM response as JSON: {e}", file=sys.stderr)
				# If there's a pending exercise, treat as answer
				if has_pending:
					return "grade_pending", user_text
				pass
		except Exception as e:
			# If LLM invocation fails, fall back to retrieve_docs or grade_pending
			import sys
			if sys.stdout.isatty():
				print(f"Warning: LLM invocation failed: {e}", file=sys.stderr)
			# If there's a pending exercise, treat as answer
			if has_pending:
				return "grade_pending", user_text
			pass
		
		# Final fallback
		if has_pending:
			return "grade_pending", user_text
		return "retrieve_docs", user_text

	def handle_query(user_text: str) -> str:
		import sys
		import traceback
		# Only print if running in CLI mode (not in web server)
		is_cli = sys.stdout.isatty()
		
		try:
			if is_cli:
				print(f"Current memory: {pending}") 
			tool_name, tool_input = route_tool(user_text)
			# Log selected tool and truncated input
			if is_cli:
				preview = tool_input if len(tool_input) <= 120 else (tool_input[:117] + "...")
				print(f"[tool] seleccionado={tool_name} input={preview}")
			
			response_text = ""
			try:
				if tool_name == "knowledge_report":
					response_text = tool_knowledge(tool_input)
				elif tool_name == "topic_summary":
					response_text = tool_summary(tool_input)
				elif tool_name == "grade_exercise":
					response_text = tool_grade(tool_input)
				elif tool_name == "recommend_exercises":
					response_text = tool_recommend(tool_input)
				elif tool_name == "ask_exercise":
					response_text = tool_ask_exercise(tool_input)
				elif tool_name == "grade_pending":
					response_text = tool_grade_pending(tool_input)
				elif tool_name == "summarize_topic":
					response_text = summarize_with_validation(llm, tool_input or user_text, max_sources=5)
				else:
					response_text = answer_with_rag(llm, user_text)
			except Exception as e:
				# If tool execution fails, return error message
				error_msg = f"Error al ejecutar la herramienta {tool_name}: {str(e)}"
				if is_cli:
					print(f"ERROR: {error_msg}", file=sys.stderr)
					traceback.print_exc()
				response_text = error_msg
			
			# Ensure response_text is a string and not empty
			if not response_text or not isinstance(response_text, str):
				response_text = "Lo siento, no pude generar una respuesta. Por favor intenta de nuevo."
			
			# Log current context (before sending response) - only in CLI mode
			if is_cli:
				print("[context] recent (max 6):")
				for i, item in enumerate(history[-6:], start=1):
					up = (item.get("user_prompt") or "").strip()
					tu = (item.get("tool_used") or "").strip() or "desconocido"
					ar = (item.get("agent_response") or "").strip()
					if len(ar) > 120:
						ar = ar[:117] + "..."
					print(f"  {i}. U: {up} | Tool: {tu} | A: {ar}")
				print(f"[context] pending: {pending}")
			
			# Update conversation history (cap at 6)
			history.append({
				"user_prompt": user_text,
				"agent_response": response_text if len(response_text) <= 300 else (response_text[:297] + "..."),
				"tool_used": tool_name,
			})
			if len(history) > 6:
				del history[:-6]
			
			return response_text
		except Exception as e:
			# Final fallback - ensure we always return a string
			error_msg = f"Error procesando la consulta: {str(e)}"
			if is_cli:
				print(f"FATAL ERROR: {error_msg}", file=sys.stderr)
				traceback.print_exc()
			return error_msg

	return handle_query


def main() -> None:
	cfg = get_config()
	if not (cfg.neo4j_uri and cfg.neo4j_user and cfg.neo4j_password):
		print("Missing Neo4j config. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in .env", file=sys.stderr)
		sys.exit(1)

	# Try to create vector indexes (safe to call multiple times)
	ensure_vector_indexes()

	legajo = input("Ingrese su legajo: ").strip()
	upsert_student(legajo)
	llm = build_llm()

	handle_query = initialize_agent(legajo, llm)

	print("Agent listo. Escribe tu consulta en lenguaje natural (escribe 'salir' para terminar).")
	while True:
		line = input("\n> ").strip()
		if not line:
			continue
		if line.lower() in ("salir", "exit", "quit"):
			break
		try:
			
			response = handle_query(line)
			print(response)
		except Exception as e:
			print(f"Ocurrió un error procesando la consulta: {e}")


if __name__ == "__main__":
	main()


