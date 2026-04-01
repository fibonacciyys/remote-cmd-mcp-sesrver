# Remote Command MCP Server

一个支持 **streamable-http** 传输的 MCP (Model Context Protocol) 服务器，用于在远程部署服务器上执行预配置的指令。每个命令自动注册为独立的 MCP Tool，无需先查询再执行。

## 功能特性

- 支持 MCP streamable-http 传输协议
- 通过 JSON 配置文件管理命令，**自动注册为独立 MCP Tool**
- SK (Secret Key) 安全校验，支持时间戳防重放
- 安全的命令执行（预配置命令，非任意命令）
- 支持命令超时控制
- 动态重载配置（运行时更新工具列表）

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

每个命令会自动注册为一个独立的 MCP Tool，工具名直接使用命令 key（`-` 替换为 `_`）。建议使用统一前缀命名，如 `remote_server_cmd_`，避免与其他 MCP Server 工具名冲突。

```json
{
    "commands": {
        "remote_server_cmd_hi": {
            "command": ["echo", "hello world"],
            "description": "输出 hello world"
        },
        "remote_server_cmd_date": {
            "command": ["date"],
            "description": "显示当前日期时间"
        },
        "remote_server_cmd_update_blog": {
            "command": ["bash", "-c", "cd /root/blog && git pull && docker compose up -d --build"],
            "description": "更新个人博客"
        }
    }
}
```

| 字段 | 类型 | 描述 |
|------|------|------|
| key | string | 命令标识，同时作为 MCP Tool 名称（如 `remote_server_cmd_hi`） |
| `command` | array | 要执行的命令及参数 |
| `description` | string | 命令描述，会作为 Tool 的描述展示给 MCP Client |

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
nohup .venv/bin/python mcp_server.py --transport streamable-http > mcp_server.log 2>&1 &
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
import time

async def main():
    headers = {}
    # 如果启用了 SK 校验
    headers["x-api-key"] = "your-secret-key-here"
    headers["x-timestamp"] = str(int(time.time()))

    async with streamablehttp_client(
        "http://your-server:8080/mcp",
        headers=headers
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 列出所有可用工具（commands.json 中的每个命令 + reload_config）
            tools = await session.list_tools()
            print([t.name for t in tools.tools])

            # 直接调用命令，工具名就是命令 key
            result = await session.call_tool("remote_server_cmd_hi")
            print(result)

            result = await session.call_tool("remote_server_cmd_update_blog")
            print(result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### 方式二：Claude Desktop 配置（HTTP 模式）

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

### 方式三：Claude Desktop 配置（stdio 模式）

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

### 方式四：使用 curl 测试

```bash
# 初始化连接
TS=$(date +%s)
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "x-api-key: your-secret-key-here" \
  -H "x-timestamp: $TS" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## 可用工具

`commands.json` 中的每个命令会自动注册为一个 MCP Tool，工具名为命令 key。例如：

| 工具名 | 对应命令 key | 描述 |
|--------|-------------|------|
| `remote_server_cmd_hi` | `remote_server_cmd_hi` | 输出 hello world |
| `remote_server_cmd_date` | `remote_server_cmd_date` | 显示当前日期时间 |
| `remote_server_cmd_hostname` | `remote_server_cmd_hostname` | 显示主机名 |
| `remote_server_cmd_update_blog` | `remote_server_cmd_update_blog` | 更新个人博客 |

此外还有一个内置工具：

### reload_config

重新加载配置文件，动态更新可用工具列表。

**参数：**
- `config_path` (string, optional): 配置文件路径，默认 `commands.json`

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
    "remote_server_cmd_ip": {"command": ["ipconfig"], "description": "显示 IP 配置"},
    "remote_server_cmd_dir": {"command": ["cmd", "/c", "dir"], "description": "列出目录"}
}
```

### Q: 如何在宿主机执行 docker compose？

```json
{
    "remote_server_cmd_deploy": {
        "command": ["bash", "-c", "cd /opt/myapp && docker compose up -d --build"],
        "description": "部署应用"
    }
}
```

> 注意：MCP Server 需要部署在宿主机上（而非 Docker 容器内），才能直接执行宿主机的 docker 命令。

### Q: 如何运行多步命令？

使用 `bash -c` 将多条命令串联：

```json
{
    "remote_server_cmd_update_blog": {
        "command": ["bash", "-c", "cd /root/blog && git pull && docker compose up -d --build"],
        "description": "拉取代码并重新部署博客"
    }
}
```

### Q: SK 校验失败？

- 检查 `.sk` 文件是否存在且 `secret_key` 不为空
- 检查 `x-api-key` header 是否正确传递
- 检查 `x-timestamp` 是否在 5 分钟有效期内

## License

MIT
