# Remote Command MCP Server

一个支持 **streamable-http** 传输的 MCP (Model Context Protocol) 服务器，用于在远程部署服务器上执行预配置的指令。

## 功能特性

- 支持 MCP streamable-http 传输协议
- 通过 JSON 配置文件管理命令
- SK (Secret Key) 安全校验，支持时间戳防重放
- 安全的命令执行（预配置命令，非任意命令）
- 支持命令超时控制
- 动态重载配置

## 项目结构

```
remote-cmd-mcp-server/
├── mcp_server.py       # MCP 服务器主程序
├── commands.json       # 命令配置文件
├── .sk                 # SK 密钥配置（不提交到 Git）
├── .sk.example         # SK 配置示例
├── requirements.txt    # Python 依赖
├── .gitignore          # Git 忽略规则
└── README.md           # 本文档
```

## 安装

### 方式一：使用 uv（推荐）

[uv](https://github.com/astral-sh/uv) 是新一代 Python 包管理器，比 pip 更快。

```bash
# 安装 uv（如果还没有）
# Linux/macOS:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或者使用 pip 安装
pip install uv

# 创建虚拟环境并安装依赖（一条命令搞定）
uv venv && uv pip install -r requirements.txt

# 运行
uv run python mcp_server.py
```

### 方式二：使用 pip + venv

```bash
# Python 3.8+
python -m venv venv

# 激活虚拟环境
# Linux/macOS:
source venv/bin/activate

# Windows:
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

## 配置

### 1. 命令配置 (`commands.json`)

```json
{
    "commands": {
        "/hi": {
            "command": ["echo", "hello world"],
            "description": "输出 hello world"
        },
        "/date": {
            "command": ["date"],
            "description": "显示当前日期"
        },
        "/deploy": {
            "command": ["bash", "-c", "cd /opt/myapp && docker compose up -d --build"],
            "description": "部署应用"
        }
    }
}
```

| 字段 | 类型 | 描述 |
|------|------|------|
| `command` | array | 要执行的命令及参数 |
| `description` | string | 命令描述（可选） |

### 2. SK 安全配置 (`.sk`)

创建 `.sk` 文件启用接口鉴权：

```bash
# 复制示例文件
cp .sk.example .sk

# 编辑 .sk，设置你的密钥
# {
#     "secret_key": "your-secret-key-here"
# }
```

> - `.sk` 文件已在 `.gitignore` 中，不会提交到版本库
> - 如果 `.sk` 不存在或 `secret_key` 为空，SK 校验自动禁用
> - SK 校验支持时间戳防重放攻击（默认 5 分钟有效期）

## 启动 MCP Server

```bash
# streamable-http 模式（默认，远程部署推荐）
python mcp_server.py --transport streamable-http

# 指定配置文件和 SK 文件
python mcp_server.py --config commands.json --sk .sk

# stdio 模式（本地 Claude Desktop 使用）
python mcp_server.py --transport stdio

# 查看帮助
python mcp_server.py --help
```

### 宿主机后台部署（生产环境推荐）

```bash
# 安装依赖
uv venv && source .venv/bin/activate && uv pip install -r requirements.txt

# 使用 nohup 后台运行
nohup .venv/bin/python mcp_server.py --transport streamable-http > mcp.log 2>&1 &

# 或使用 systemd（推荐，见下方说明）
```

#### systemd 服务（推荐）

创建 `/etc/systemd/system/mcp-server.service`：

```ini
[Unit]
Description=Remote Command MCP Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mcp-server
ExecStart=/opt/mcp-server/.venv/bin/python mcp_server.py --transport streamable-http
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp-server
sudo systemctl start mcp-server
sudo systemctl status mcp-server   # 查看状态
journalctl -u mcp-server -f        # 查看日志
```

## MCP Client 调用

### 方式一：使用 MCP SDK (Python)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    headers = {}
    # 如果启用了 SK 校验
    headers["x-api-key"] = "your-secret-key-here"
    headers["x-timestamp"] = str(int(time.time()))

    async with streamablehttp_client(
        "http://your-server:8080/mcp",
        headers=headers
    ) as client:
        async with ClientSession(client) as session:
            await session.initialize()

            # 列出所有可用命令
            result = await session.call_tool("list_commands")
            print(result)

            # 执行命令
            result = await session.call_tool("exec_cmd", {"cmd_key": "/hi"})
            print(result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### 方式二：Claude Desktop 配置（stdio 模式）

在 `claude_desktop_config.json` 中添加：

```json
{
    "mcpServers": {
        "remote-cmd": {
            "command": "python",
            "args": ["/path/to/mcp_server.py", "--transport", "stdio"]
        }
    }
}
```

### 方式三：Claude Desktop 配置（HTTP 模式）

```json
{
    "mcpServers": {
        "remote-cmd": {
            "url": "http://your-server:8080/mcp",
            "headers": {
                "x-api-key": "your-secret-key-here"
            }
        }
    }
}
```

### 方式四：使用 curl 测试

```bash
# 不带 SK
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# 带 SK 鉴权
TS=$(date +%s)
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "x-api-key: your-secret-key-here" \
  -H "x-timestamp: $TS" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## 可用工具

### 1. exec_cmd

执行预配置的远程命令。

**参数：**
- `cmd_key` (string): 命令键，如 "/hi"
- `args` (array, optional): 额外的命令行参数

### 2. list_commands

列出所有可用的预配置命令。

### 3. reload_config

重新加载配置文件。

**参数：**
- `config_path` (string, optional): 配置文件路径

## 安全说明

1. **SK 校验**：支持 `x-api-key` 或 `Authorization: Bearer` 两种 header 传递密钥
2. **时间戳防重放**：通过 `x-timestamp` header 校验请求时效性（默认 5 分钟）
3. **命令白名单**：只能执行配置文件中预定义的命令
4. **命令超时**：所有命令默认 30 秒超时
5. **建议**：
   - 生产环境务必配置 SK
   - 使用 HTTPS 或 VPN 保护传输链路
   - 使用 systemd 管理进程，配置自动重启

## 常见问题

### Q: Windows 下命令不工作？

```json
{
    "/ip": {"command": ["ipconfig"], "description": "显示 IP 配置"},
    "/dir": {"command": ["cmd", "/c", "dir"], "description": "列出目录"}
}
```

### Q: 如何在宿主机执行 docker compose？

```json
{
    "/deploy": {
        "command": ["bash", "-c", "cd /opt/myapp && docker compose up -d --build"],
        "description": "部署应用"
    }
}
```

> 注意：MCP Server 需要部署在宿主机上（而非 Docker 容器内），才能直接执行宿主机的 docker 命令。

### Q: SK 校验失败？

- 检查 `.sk` 文件是否存在且 `secret_key` 不为空
- 检查 `x-api-key` header 是否正确传递
- 检查 `x-timestamp` 是否在 5 分钟有效期内

## License

MIT
