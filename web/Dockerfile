FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data directory for SQLite
RUN mkdir -p /data

EXPOSE 5100

# Entrypoint: init DB + seed, then start server
# Single worker required: convert_jobs is in-memory dict shared via threads.
# Multiple workers = separate processes = lost state on progress webhooks + polls.
CMD python seed.py && gunicorn --bind 0.0.0.0:5100 --workers 1 --threads 4 app:app
