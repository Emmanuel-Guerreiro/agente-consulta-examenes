#!/usr/bin/env python
"""Script to run the FastAPI server for the agent."""
import sys
import os

# Ensure the project root is in the path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
	sys.path.insert(0, project_root)

if __name__ == "__main__":
	import uvicorn
	from app.api.server import app
	
	# Run the server
	uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)

