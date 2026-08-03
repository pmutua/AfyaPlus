FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY app/requirements.txt /app/app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/app/requirements.txt

COPY app /app/app
COPY .chainlit /app/.chainlit
COPY knowledge /app/knowledge

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
