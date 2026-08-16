FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/common ./common
COPY backend/services ./services

ARG SERVICE_MODULE=services.orchestrator.main:app
ENV SERVICE_MODULE=${SERVICE_MODULE}
ENV PORT=8080

EXPOSE 8080

CMD uvicorn ${SERVICE_MODULE} --host 0.0.0.0 --port ${PORT}
