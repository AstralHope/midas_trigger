FROM eclipse-temurin:8-jdk AS temurin8

FROM python:3.14-slim

ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

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
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Use the current official Eclipse Temurin JDK 8 build in this Python-based image.
COPY --from=temurin8 /opt/java/openjdk /opt/java/openjdk
RUN java -version && javac -version

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
RUN mkdir -p /scripts /data /logs && \
    chown -R chksys:chksys /app /scripts /data /logs

# Use user chksys
USER chksys

# Expose port 9020
EXPOSE 9020

# Start FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9020"]
