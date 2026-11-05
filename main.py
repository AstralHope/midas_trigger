import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings


CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")
KEYS_PATH = os.environ.get("KEYS_PATH", "keys.json")
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/scripts"))
LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

logger = logging.getLogger("midas_trigger")
request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / "service.log",
            maxBytes=int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024)),
            backupCount=int(os.environ.get("LOG_BACKUP_COUNT", 5)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        logger.exception("file_logging_unavailable log_dir=%s; continuing with container logs", LOG_DIR)

_config_cache: dict[str, Any] = {"routes": [], "mtime": None}


def load_config() -> list[dict[str, Any]]:
    """Load route configuration, re-reading it when its modification time changes."""
    config_path = Path(CONFIG_PATH)
    if not config_path.exists():
        return []
    try:
        mtime = config_path.stat().st_mtime_ns
        if mtime != _config_cache["mtime"]:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            routes = data.get("routes", [])
            if not isinstance(routes, list):
                raise ValueError("'routes' must be a list")
            _config_cache["routes"] = routes
            _config_cache["mtime"] = mtime
        return _config_cache["routes"]
    except Exception:
        logger.exception("config_read_failed path=%s", CONFIG_PATH)
        return _config_cache.get("routes", [])


def load_api_key_hashes() -> set[str]:
    allowed_hashes: set[str] = set()
    for key in os.environ.get("API_KEYS", "").split(","):
        if key.strip():
            allowed_hashes.add(hashlib.sha256(key.strip().encode("utf-8")).hexdigest())

    keys_path = Path(KEYS_PATH)
    if keys_path.exists():
        try:
            keys_data = json.loads(keys_path.read_text(encoding="utf-8")) or {}
            for entry in keys_data.get("keys", []):
                key_hash = entry.get("hash")
                if key_hash:
                    allowed_hashes.add(key_hash.strip().lower())
        except Exception:
            logger.exception("api_key_file_read_failed path=%s", KEYS_PATH)
    return allowed_hashes


def is_valid_api_key(api_key: str | None) -> bool:
    if not api_key:
        return False
    incoming_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return any(secrets.compare_digest(incoming_hash, allowed) for allowed in load_api_key_hashes())


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not is_valid_api_key(api_key):
        logger.warning("auth_rejected interface=http_api reason=invalid_or_unconfigured_key")
        raise HTTPException(status_code=403, detail="Could not validate credentials (Invalid API Key)")
    return api_key


def find_route(route_path: str) -> dict[str, Any] | None:
    return next((route for route in load_config() if route.get("path") == route_path), None)


def command_arguments(args: Any, kwargs: Any) -> list[str]:
    """Convert structured arguments to argv entries without shell interpolation."""
    if not isinstance(args, list):
        raise HTTPException(status_code=400, detail="'args' must be a JSON array")
    if not isinstance(kwargs, dict):
        raise HTTPException(status_code=400, detail="'kwargs' must be a JSON object")

    def stringify(value: Any, label: str) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (str, int, float)):
            return str(value)
        raise HTTPException(status_code=400, detail=f"{label} must be a string, number, or boolean")

    argv = [stringify(value, "Each positional argument") for value in args]
    for name, value in kwargs.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
            raise HTTPException(status_code=400, detail=f"Invalid named argument '{name}'")
        argv.append(f"--{name}={stringify(value, f'Named argument {name!r}')}")
    return argv


def _output_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace").strip()
    return (value or "").strip()


def _log_script_result(
    run_id: str,
    script_name: str,
    status: str,
    duration: float,
    stdout: str,
    stderr: str,
    exit_code: int | None = None,
) -> None:
    logger.info(
        "script_finished request_id=%s run_id=%s script=%s status=%s exit_code=%s duration_seconds=%.4f",
        request_id_context.get(),
        run_id,
        script_name,
        status,
        exit_code,
        duration,
    )
    logger.info("script_stdout request_id=%s run_id=%s script=%s\n%s", request_id_context.get(), run_id, script_name, stdout or "<empty>")
    logger.info("script_stderr request_id=%s run_id=%s script=%s\n%s", request_id_context.get(), run_id, script_name, stderr or "<empty>")


def execute_script(target_route: dict[str, Any], args: Any = None, kwargs: Any = None) -> dict[str, Any]:
    script_name = target_route.get("script")
    timeout = float(target_route.get("timeout", 60.0))
    if not isinstance(script_name, str) or not script_name.strip():
        raise HTTPException(status_code=400, detail="Invalid script name in route configuration")

    relative_script_path = Path(script_name)
    if relative_script_path.is_absolute() or ".." in relative_script_path.parts:
        raise HTTPException(status_code=400, detail="Invalid script path in route configuration")

    scripts_root = SCRIPTS_DIR.resolve()
    try:
        script_path = (scripts_root / relative_script_path).resolve()
        script_path.relative_to(scripts_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Script path must stay inside the scripts directory") from exc

    if not script_path.is_file():
        raise HTTPException(status_code=404, detail=f"Script '{script_name}' not found in {SCRIPTS_DIR}")

    interpreter_map = {".py": "python", ".sh": "bash"}
    interpreter = interpreter_map.get(script_path.suffix.lower())
    if interpreter is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported script type '{script_path.suffix.lower()}'. Supported: {', '.join(interpreter_map)}",
        )

    script_args = command_arguments([] if args is None else args, {} if kwargs is None else kwargs)
    received_time = datetime.now().astimezone().isoformat()
    start_time = time.monotonic()
    run_id = uuid4().hex[:12]
    logger.info(
        "script_started request_id=%s run_id=%s script=%s timeout_seconds=%s positional_arg_count=%s named_arg_count=%s",
        request_id_context.get(),
        run_id,
        script_name,
        timeout,
        len(args or []),
        len(kwargs or {}),
    )
    try:
        result = subprocess.run(
            [interpreter, str(script_path), *script_args], capture_output=True, text=True, check=True, timeout=timeout
        )
        status = "success"
        exit_code = result.returncode
        stdout = _output_text(result.stdout)
        stderr = _output_text(result.stderr)
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = None
        stdout = _output_text(exc.stdout)
        stderr = f"Script execution timed out after {timeout} seconds. {_output_text(exc.stderr)}".strip()
    except subprocess.CalledProcessError as exc:
        status = "failed"
        exit_code = exc.returncode
        stdout = _output_text(exc.stdout)
        stderr = _output_text(exc.stderr)
    except Exception:
        logger.exception("script_crashed run_id=%s script=%s", run_id, script_name)
        raise

    duration = round(time.monotonic() - start_time, 4)
    _log_script_result(run_id, script_name, status, duration, stdout, stderr, exit_code)
    response = {
        "status": status,
        "script": script_name,
        "request_received_time": received_time,
        "execution_duration_seconds": duration,
        "stdout": stdout,
        "stderr": stderr,
    }
    if status == "failed":
        response["exit_code"] = exit_code
    return response


allowed_mcp_hosts = [
    host.strip()
    for host in os.environ.get("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,[::1]:*").split(",")
    if host.strip()
]
allowed_mcp_origins = [
    origin.strip()
    for origin in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
mcp = FastMCP(
    "Remote Script Trigger",
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_mcp_hosts,
        allowed_origins=allowed_mcp_origins,
    ),
)


@mcp.tool()
def list_scripts() -> list[dict[str, Any]]:
    """List the configured script routes available for execution."""
    return [
        {
            "path": route.get("path"),
            "script": route.get("script"),
            "method": route.get("method", "GET").upper(),
            "timeout": route.get("timeout", 60.0),
        }
        for route in load_config()
    ]


@mcp.tool()
def run_script(path: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a route with positional args and named kwargs, e.g. path='/report', args=['daily'], kwargs={'format': 'csv'}."""
    target_route = find_route(path)
    if not target_route:
        return {"status": "not_found", "error": f"No script mapped to path '{path}'"}
    try:
        return execute_script(target_route, args, kwargs)
    except HTTPException as exc:
        return {"status": "error", "http_status": exc.status_code, "error": exc.detail}


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Remote Script Trigger API and MCP Server", lifespan=lifespan)
mcp_asgi_app = mcp.streamable_http_app()
app.mount("/mcp", mcp_asgi_app, name="mcp")


@app.middleware("http")
async def authenticate_mcp(request: Request, call_next):
    if request.url.path.startswith("/mcp"):
        api_key = request.headers.get(API_KEY_NAME)
        if not is_valid_api_key(api_key):
            logger.warning(
                "auth_rejected interface=mcp reason=invalid_or_unconfigured_key key_header_present=%s",
                bool(api_key),
            )
            return JSONResponse(status_code=403, content={"detail": "Could not validate credentials (Invalid API Key)"})
    return await call_next(request)


@app.middleware("http")
async def log_http_request(request: Request, call_next):
    request_id = uuid4().hex[:12]
    start_time = time.monotonic()
    client_ip = request.client.host if request.client else "unknown"
    request_id_token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "http_request_failed request_id=%s method=%s path=%s client=%s host=%s origin=%s",
            request_id,
            request.method,
            request.url.path,
            client_ip,
            request.headers.get("host", ""),
            request.headers.get("origin", ""),
        )
        raise
    finally:
        request_id_context.reset(request_id_token)
    logger.info(
        "http_request request_id=%s method=%s path=%s status=%s duration_ms=%.2f client=%s host=%s origin=%s api_key_header_present=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.monotonic() - start_time) * 1000,
        client_ip,
        request.headers.get("host", ""),
        request.headers.get("origin", ""),
        bool(request.headers.get(API_KEY_NAME)),
    )
    return response


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def catch_all_trigger(path: str, request: Request, _: str = Security(verify_api_key)):
    request_path = f"/{path}"
    if request_path in {"/docs", "/openapi.json", "/redoc"}:
        raise HTTPException(status_code=404)

    target_route = find_route(request_path)
    if not target_route:
        raise HTTPException(status_code=404, detail=f"No script mapped to path '{request_path}'")

    allowed_method = target_route.get("method", "GET").upper()
    if request.method != allowed_method:
        raise HTTPException(
            status_code=405,
            detail=f"Method {request.method} not allowed for path '{request_path}'. Use {allowed_method}.",
        )

    if request.method == "GET":
        args = request.query_params.getlist("arg")
        kwargs = {
            key: value
            for key, value in request.query_params.multi_items()
            if key != "arg"
        }
    else:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="POST body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="POST body must be a JSON object")
        unknown = set(payload) - {"args", "kwargs"}
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown request fields: {', '.join(sorted(unknown))}")
        args = payload.get("args", [])
        kwargs = payload.get("kwargs", {})

    return await asyncio.to_thread(execute_script, target_route, args, kwargs)
