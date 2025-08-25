FROM python:3.11-slim

# Install ffmpeg and default fonts for libass
RUN apt-get update && \
    apt-get install -y ffmpeg fonts-dejavu && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py .

# Create temp directory for file processing
RUN mkdir -p /tmp/media

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]