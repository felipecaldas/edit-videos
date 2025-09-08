FROM python:3.11-slim

# Set timezone
ENV TZ=Australia/Melbourne

# Install ffmpeg, fonts for libass, and tzdata; configure timezone
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg fonts-dejavu tzdata curl && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application package and config
COPY videomerge ./videomerge
COPY subtitle_config.json ./subtitle_config.json

# Create temp directory for file processing
RUN mkdir -p /tmp/media

EXPOSE 8000

CMD ["uvicorn", "videomerge.main:app", "--host", "0.0.0.0", "--port", "8000"]