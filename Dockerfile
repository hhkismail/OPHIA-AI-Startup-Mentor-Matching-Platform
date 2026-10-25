# One image for both services.
#   Default: the dashboard on the bundled snapshot (no keys, no cloud):
#     docker build -t ophia . && docker run -p 8501:8501 ophia
#   Full stack (backend + dashboard on Firestore/Vertex AI): docker compose up
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so code changes don't reinstall them
COPY ophia-nlp/requirements.txt ophia-nlp/requirements.txt
COPY ophia-data/requirements.txt ophia-data/requirements.txt
COPY ophia-backend/requirements.txt ophia-backend/requirements.txt
COPY ophia-frontend/requirements.txt ophia-frontend/requirements.txt
RUN pip install -r ophia-backend/requirements.txt -r ophia-frontend/requirements.txt

COPY . .

# Run as a non-root user; HOME is where Google's login (ADC) is looked up
RUN useradd --create-home --uid 1000 app && chown -R app /app/ophia-data/credentials
USER app

EXPOSE 8000 8501

CMD ["streamlit", "run", "ophia-frontend/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
