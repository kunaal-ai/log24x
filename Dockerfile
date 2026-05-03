# Stage 1: Build dependencies
FROM python:3.12-slim as builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /install /usr/local/lib/python3.12/site-packages
COPY --from=builder /install/bin /usr/local/bin

COPY . .
ENV PYTHONPATH=/usr/local/lib/python3.12/site-packages

RUN useradd -m apiuser && chown -R apiuser:apiuser /app
USER apiuser

EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]