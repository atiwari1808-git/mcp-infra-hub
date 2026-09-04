FROM python:3.12-slim

WORKDIR /app

# Install deps first (Docker layer caching: deps rarely change, code often does)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Bind to 0.0.0.0 so the port is reachable from outside the container
CMD ["python", "mcp_server.py"]

