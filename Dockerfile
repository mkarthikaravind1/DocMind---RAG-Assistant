FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only PyTorch first: the default wheel bundles several GB of GPU (CUDA)
# libraries this app never uses, which made the image ~9 GB and the build slow.
RUN pip install --no-cache-dir --default-timeout=120 --retries 10 \
    torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir --default-timeout=120 --retries 10 -r requirements.txt

# Copy all backend files from root
COPY app.py access.py auth.py database.py dependencies.py \
    guardrails.py ingest.py models.py rag.py vector_store.py ./

# Copy routes folder
COPY routes/ ./routes/

RUN mkdir -p documents

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
