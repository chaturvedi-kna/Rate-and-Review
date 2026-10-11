FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Environment variables
ENV PORT=5000
ENV PYTHONUNBUFFERED=1
ENV DB_FILE=/app/data/meesho_studio.db

# Expose server port
EXPOSE 5000

# Run Flask application via Gunicorn
CMD ["sh", "-c", "mkdir -p /app/data && gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 app:app"]

