# Backend: FastAPI app endpoints + the MCP server ElevenLabs connects to.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY . .
EXPOSE 8000
# Hosts like Render set PORT; default to 8000 locally.
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
