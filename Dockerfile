FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple --trusted-host mirrors.cloud.tencent.com -r requirements.txt

COPY mcp_server.py .
COPY commands.json .

EXPOSE 8080

CMD ["python", "mcp_server.py", "--transport", "streamable-http"]
