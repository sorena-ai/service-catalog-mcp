FROM python:3.12.9-slim

RUN apt-get update && apt-get install -y curl git gh nodejs npm tini && \
    rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN claude mcp add --scope user context7 -- npx -y @upstash/context7-mcp

# The install script runs an interactive post-install setup that fails without a TTY.
# We ignore its exit code and assert the binary exists instead.
RUN curl -fsSL https://cli.devin.ai/install.sh | bash; test -x /root/.local/bin/devin
ENV PATH="/root/.local/bin:$PATH"

ENTRYPOINT ["/usr/bin/tini", "--"]

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .
