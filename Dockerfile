FROM python:3.14-slim

# Install essential system tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Network transfer tools
    lftp \
    ftp \
    curl \
    wget \
    openssh-client \
    rsync \
    # Network diagnostic tools
    iproute2 \
    iputils-ping \
    telnet \
    netcat-openbsd \
    dnsutils \
    # File compression tools
    zip \
    unzip \
    # Data processing tools
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create user chksys with UID 8000
RUN groupadd -g 8000 chksys && \
    useradd -u 8000 -g chksys -m -s /bin/bash chksys

# Set up app directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API and shared server code
COPY main.py .

# Create script and data directories with permissions
RUN mkdir -p /scripts /data && \
    chown -R chksys:chksys /app /scripts /data

# Use user chksys
USER chksys

# Expose port 9020
EXPOSE 9020

# Start FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9020"]
