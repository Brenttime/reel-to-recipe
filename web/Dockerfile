FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data directory for SQLite
RUN mkdir -p /data

EXPOSE 5100

# Entrypoint: init DB + seed, then start server
CMD python seed.py && gunicorn --bind 0.0.0.0:5100 --workers 2 --threads 2 app:app
