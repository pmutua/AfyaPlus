FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DASHBOARD_ARTIFACT_ROOT=/app

WORKDIR /app

COPY dashboard/requirements.txt /app/dashboard/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/dashboard/requirements.txt

COPY dashboard /app/dashboard
COPY evaluation/*.csv /app/evaluation/
COPY drift/drift_trend_table.csv /app/drift/drift_trend_table.csv
COPY cost/*.csv /app/cost/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "dashboard.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
