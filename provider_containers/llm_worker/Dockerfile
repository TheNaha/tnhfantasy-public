FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy provider_core shared library
COPY provider_core/ /app/provider_core/

# Copy the LLM worker code
COPY llm_worker/ /app/llm_worker/

# Run the unified worker app
CMD ["python", "-m", "uvicorn", "llm_worker.worker:app", "--host", "0.0.0.0", "--port", "8000"]
