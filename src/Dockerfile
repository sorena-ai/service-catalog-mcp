FROM python:3.12.9-slim

RUN apt-get update && apt-get install -y curl git gh nodejs npm tini && \
    rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN claude mcp add --scope user context7 -- npx -y @upstash/context7-mcp

RUN curl -fsSL https://cli.devin.ai/install.sh | bash
ENV PATH="/root/.local/bin:$PATH"

ENTRYPOINT ["/usr/bin/tini", "--"]

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .
