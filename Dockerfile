# Email reply assistant: builds drafts from the sample inbox, then serves the review UI on :8030.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8030
# Keys and IMAP settings come from the environment (docker-compose env_file), never from the image.
CMD ["sh", "-c", "python -m assistant.main && python -m assistant.review --host 0.0.0.0 --port 8030"]
