FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HuggingFace model cache — mount a volume here to persist downloads across restarts
ENV HF_HOME=/cache/huggingface
