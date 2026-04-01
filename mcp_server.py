"""
Remote Command MCP Server
支持 stdio 和 streamable-http 两种传输模式的 MCP 服务器
支持 SK (Secret Key) 校验
"""

import json
import subprocess
import logging
import hashlib
import hmac
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局 SK 配置
SK_CONFIG = {
    "enabled": False,
    "secret_key": "",
}


def load_sk_config(sk_path: str = ".sk") -> None:
    """从文件加载 SK 配置"""
    p = Path(sk_path)
    if not p.exists():
        logger.warning(f"SK 配置文件 {sk_path} 不存在，SK 校验已禁用")
        SK_CONFIG["enabled"] = False
        return
    try:
        with open(p, 'r') as f:
            data = json.load(f)
            SK_CONFIG["secret_key"] = data.get("secret_key", "")
            SK_CONFIG["enabled"] = bool(SK_CONFIG["secret_key"])
            logger.info(f"SK 校验: {'已启用' if SK_CONFIG['enabled'] else '未启用'}")
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"SK 配置文件加载失败: {e}")
        SK_CONFIG["enabled"] = False


def verify_sk(sk: str) -> bool:
    """
    验证 SK 是否合法

    Args:
        sk: 客户端传入的 Secret Key

    Returns:
        是否验证通过
    """
    if not SK_CONFIG["enabled"]:
        return True
    if not sk:
        return False
    return hmac.compare_digest(sk, SK_CONFIG["secret_key"])


def verify_sk_with_timestamp(sk: str, timestamp: str, ttl: int = 300) -> bool:
    """
    验证带时间戳的 SK（防重放攻击）

    Args:
        sk: 客户端传入的 Secret Key
        timestamp: 客户端请求时间戳（秒）
        ttl: 允许的时间偏差（秒），默认 5 分钟

    Returns:
        是否验证通过
    """
    if not SK_CONFIG["enabled"]:
        return True

    # 检查 SK
    if not sk or not hmac.compare_digest(sk, SK_CONFIG["secret_key"]):
        return False

    # 检查时间戳防重放
    if timestamp:
        try:
            req_time = int(timestamp)
            now = int(time.time())
            if abs(now - req_time) > ttl:
                logger.warning(f"请求时间戳过期: 请求时间={req_time}, 当前时间={now}, 偏差>{ttl}s")
                return False
        except (ValueError, TypeError):
            logger.warning(f"无效的时间戳: {timestamp}")
            return False

    return True


class RemoteCommandServer:
    """远程命令执行逻辑"""

    def __init__(self, config_path: str = "commands.json"):
        self.config_path = Path(config_path)
        self.commands = {}
        self.load_config()

    def load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning(f"配置文件 {self.config_path} 不存在，使用默认配置")
            self.commands = self._get_default_commands()
            return
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.commands = json.load(f).get('commands', {})
            logger.info(f"已加载 {len(self.commands)} 个命令配置")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"配置文件解析失败: {e}")
            self.commands = self._get_default_commands()

    def _get_default_commands(self) -> dict:
        return {
            "/hi": {"command": ["echo", "hello world"], "description": "输出 hello world"},
            "/date": {"command": ["date"], "description": "显示当前日期时间"},
            "/hostname": {"command": ["hostname"], "description": "显示主机名"},
        }

    def execute_command(self, cmd_key: str, args: list[str] = None) -> dict:
        if cmd_key not in self.commands:
            return {"success": False, "error": f"未知命令: {cmd_key}，可用命令: {', '.join(self.commands.keys())}"}
        cmd_config = self.commands[cmd_key]
        command = cmd_config["command"].copy()
        if args:
            command.extend(args)
        try:
            logger.info(f"执行命令: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, shell=False)
            return {"success": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode, "command": cmd_key}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "命令执行超时（30秒）", "command": cmd_key}
        except Exception as e:
            return {"success": False, "error": str(e), "command": cmd_key}

    def get_available_commands(self) -> list[dict]:
        return [{"key": key, "command": " ".join(cfg["command"]), "description": cfg.get("description", "")} for key, cfg in self.commands.items()]


# 全局命令服务器
_server: RemoteCommandServer = None


def _get_server(config_path: str = "commands.json") -> RemoteCommandServer:
    global _server
    if _server is None:
        _server = RemoteCommandServer(config_path)
    return _server


# 创建 FastMCP 实例
mcp = FastMCP("Remote Command Server", host="0.0.0.0", port=8080, streamable_http_path="/mcp")


def _register_dynamic_tools(srv: RemoteCommandServer):
    """根据 commands.json 动态注册每个命令为独立的 MCP tool"""
    for cmd_key, cmd_config in srv.commands.items():
        # 工具名：去掉前导 /，如 /hi → hi, /deploy-blog → deploy_blog
        tool_name = cmd_key.lstrip("/").replace("-", "_")
        description = cmd_config.get("description", f"执行命令 {cmd_key}")
        cmd_str = " ".join(cmd_config["command"])

        # 创建闭包捕获当前命令
        def make_handler(key, cfg):
            def handler(args: list[str] = None) -> str:
                result = srv.execute_command(key, args)
                return json.dumps(result, ensure_ascii=False, indent=2)
            return handler

        mcp.tool(name=tool_name, description=f"{description}\n命令: {cmd_str}")(make_handler(cmd_key, cmd_config))

    logger.info(f"已注册 {len(srv.commands)} 个动态工具: {[k.lstrip('/').replace('-','_') for k in srv.commands.keys()]}")


@mcp.tool()
def reload_config(config_path: str = "commands.json") -> str:
    """
    重新加载配置文件，动态更新可用工具

    Args:
        config_path: 配置文件路径（可选，默认 commands.json）
    """
    global _server
    _server = RemoteCommandServer(config_path)
    _register_dynamic_tools(_server)
    return json.dumps({"success": True, "message": "配置已重新加载", "commands": list(_server.commands.keys())}, ensure_ascii=False, indent=2)


def _run_http_with_sk():
    """手动构建带 SK 中间件的 HTTP 服务"""
    import anyio
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    class SKAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if not (path == "/mcp" or path.startswith("/mcp/")):
                return await call_next(request)
            if not SK_CONFIG["enabled"]:
                return await call_next(request)

            sk = request.headers.get("x-api-key", "") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            timestamp = request.headers.get("x-timestamp", "")

            if not verify_sk_with_timestamp(sk, timestamp):
                logger.warning(f"SK 校验失败, IP={request.client.host if request.client else 'unknown'}")
                return JSONResponse({"error": "Unauthorized", "message": "SK 校验失败"}, status_code=401)

            return await call_next(request)

    starlette_app = mcp.streamable_http_app()
    starlette_app.add_middleware(SKAuthMiddleware)

    async def _serve():
        config = uvicorn.Config(
            starlette_app,
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=mcp.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    anyio.run(_serve)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Remote Command MCP Server')
    parser.add_argument('--config', '-c', default='commands.json', help='配置文件路径')
    parser.add_argument('--sk', '-s', default='.sk', help='SK 配置文件路径 (默认: .sk)')
    parser.add_argument('--transport', '-t', choices=['stdio', 'streamable-http', 'sse'],
                        default='streamable-http', help='传输模式 (默认: streamable-http)')

    args = parser.parse_args()

    # 加载 SK 配置
    load_sk_config(args.sk)

    # 预先加载命令配置
    _get_server(args.config)
    _register_dynamic_tools(_server)
    logger.info(f"Remote Command MCP Server 启动中... (transport={args.transport})")
    logger.info(f"可用命令: {', '.join(_server.commands.keys())}")

    if args.transport == "streamable-http":
        _run_http_with_sk()
    else:
        mcp.run(transport=args.transport)
