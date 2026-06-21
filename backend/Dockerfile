FROM python:3.12-slim

# Prevent Python from buffering stdout/stderr (ensures logs appear immediately)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app

# Default command for the backend (FastAPI)
# Note: workers will override this command in docker-compose
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "9005"]
