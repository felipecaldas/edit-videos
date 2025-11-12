FROM python:3.11-slim

# Set timezone
ENV TZ=Australia/Melbourne

# Install ffmpeg, fonts for libass, tzdata, curl, and Temporal CLI binary
ARG TEMPORAL_CLI_VERSION=latest
ARG TEMPORAL_CLI_ARCH=amd64
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg fonts-dejavu tzdata curl && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    curl -fsSL "https://temporal.download/cli/archive/${TEMPORAL_CLI_VERSION}?platform=linux&arch=${TEMPORAL_CLI_ARCH}" -o /tmp/temporal-cli.tar.gz && \
    tar -xzf /tmp/temporal-cli.tar.gz -C /tmp && \
    mv /tmp/temporal /usr/local/bin/temporal && \
    chmod +x /usr/local/bin/temporal && \
    rm -f /tmp/temporal-cli.tar.gz && \
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