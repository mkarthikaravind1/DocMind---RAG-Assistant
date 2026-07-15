FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend files from root
COPY app.py auth.py database.py dependencies.py \
    guardrails.py ingest.py models.py rag.py ./

# Copy routes folder
COPY routes/ ./routes/

RUN mkdir -p documents vectorstore

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]