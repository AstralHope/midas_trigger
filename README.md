# Docker API and MCP Script Trigger

简体中文说明：[README.zh-CN.md](README.zh-CN.md)

A small Docker service based on Python 3.14 that exposes configured Python and Shell scripts through both a regular HTTP API and an MCP server. Both interfaces use the same route configuration, API keys, timeout settings, and script execution code.

## Features

- HTTP endpoints preserve the configured paths and JSON response format.
- MCP uses the **Streamable HTTP** transport at `/mcp` and provides `list_scripts` and `run_script` tools.
- HTTP and MCP requests require the same `X-API-Key` credential.
- `config.yaml` and `keys.json` are read at request time and changes take effect without restarting the container.
- Script output, exit status, duration, and timeout information are returned to the caller.
- The container runs as the unprivileged `chksys` user (UID/GID 8000).

## Start the service

Requirements: Docker and Docker Compose. Build the image separately from starting the service. The local image is named `midas_trigger:0.1`; Compose uses the local image and does not build or pull it.

Build the image on a machine with access to the required package and base image sources:

```bash
docker build -t midas_trigger:0.1 .
```

### Publish on a Git tag

The workflow in `.github/workflows/publish-image.yml` publishes an image whenever a version tag such as `0.1` or `v0.1` is pushed. It publishes the matching tag and `latest` to GitHub Container Registry at `ghcr.io/<OWNER>/<REPO>`. GitHub Actions uses the repository's built-in `GITHUB_TOKEN`; no personal access token is needed. The workflow builds both `linux/amd64` and `linux/arm64` images.

```bash
git tag 0.1
git push origin 0.1
```

After the workflow completes, find the image in the repository's **Packages** page. To use a published version on a deployment machine that can access GHCR, pull it and assign the local name expected by Compose:

```bash
docker pull ghcr.io/<OWNER>/<REPO>:0.1
docker tag ghcr.io/<OWNER>/<REPO>:0.1 midas_trigger:0.1
```

For an offline/internal deployment, save that local tag, transfer the archive, and load it as described below.

For an internal or offline environment, export the built image, transfer the archive, and import it there:

```bash
docker save -o midas_trigger.tar midas_trigger:0.1
# Transfer midas_trigger.tar to the target machine
docker load -i midas_trigger.tar
```

Start the service from the directory containing `docker-compose.yml`:

```bash
docker compose up -d
```

The service listens on port `9020`. The HTTP API remains at `http://localhost:9020`; the MCP endpoint is `http://localhost:9020/mcp`.

This repository currently includes an API key for local testing (its hash is also in `keys.json`). Use it to try the example endpoint:

```bash
curl -H "X-API-Key: 8e6b78e064f0b2242257c3b76d8cf03b47a6bd4ded1f5cb9" \
  http://localhost:9020/helloworld
```

**Before production use, remove this test key from the README and revoke `test` from `keys.json` (`python manage_keys.py revoke --client test`), then create and securely store your own key. Never commit real credentials to source control.**

Create a production key on the host:

```bash
python manage_keys.py create --client my-app
```

The command prints the plaintext key once. Save it securely. Only its SHA-256 hash is stored in `keys.json`.

Alternatively, provide comma-separated plaintext keys using the `API_KEYS` environment variable. Keys configured either way authorize both HTTP and MCP. Avoid putting real keys in source control.

## HTTP usage

Routes are configured in `config.yaml`. For example:

```yaml
routes:
  - path: "/helloworld"
    script: "helloworld.py"
    method: "GET"
    timeout: 30.0
  - path: "/build-report"
    script: "build_report.sh"
    method: "POST"
    timeout: 120.0
```

Each route maps one URL path to a file under `/scripts`. Supported extensions are `.py` and `.sh`; Python scripts run with `python`, and Shell scripts with `bash`. `method` defaults to `GET`, and `timeout` defaults to 60 seconds. Both positional and named arguments are passed to the script as command-line arguments.

Trigger a route with its configured HTTP method:

```bash
curl -H "X-API-Key: <YOUR_API_KEY>" http://localhost:9020/helloworld
```

For a `GET` route, repeat the `arg` query parameter for positional arguments. Every other query parameter is treated as a named argument:

```bash
curl -G -H "X-API-Key: <YOUR_API_KEY>" \
  --data-urlencode "arg=monthly report" \
  --data-urlencode "arg=2026" \
  --data-urlencode "format=csv" \
  http://localhost:9020/build-report
```

For a `POST` route, send a JSON object with optional `args` (array) and `kwargs` (object):

```bash
curl -X POST -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"args":["monthly report",2026],"kwargs":{"format":"csv"}}' \
  http://localhost:9020/build-report
```

Each positional value becomes one command-line argument in order. Each named value becomes `--name=value`; values may be strings, numbers, or booleans. For Python scripts, read them with `sys.argv` or `argparse`; for Shell scripts, use `$1`, `$2`, and so on, and parse named options as usual. The server passes values as separate process arguments and does not evaluate them as shell code.

Successful and unsuccessful script runs return JSON containing `status`, `script`, request time, duration, `stdout`, and `stderr`. A non-zero script exit returns `status: "failed"` and `exit_code`; a timeout returns `status: "timeout"`. Configuration and routing errors use normal HTTP error status codes.

## MCP usage

Configure an MCP client to connect to `http://localhost:9020/mcp` using Streamable HTTP and add this HTTP header:

```text
X-API-Key: <YOUR_API_KEY>
```

The server exposes two tools:

- `list_scripts` returns the currently configured route paths, script names, methods, and timeouts.
- `run_script` takes a `path` (for example, `/build-report`), optional `args` array, and optional `kwargs` object, then executes the mapped script. Argument formatting matches the HTTP interface.

Example `mcp.json` configuration for clients that support remote Streamable HTTP servers and custom headers:

```json
{
  "mcpServers": {
    "script-trigger": {
      "url": "http://localhost:9020/mcp",
      "headers": {
        "X-API-Key": "<YOUR_API_KEY>"
      }
    }
  }
}
```

Client configuration formats vary. Some clients support only local stdio MCP servers or require a remote-server connector; use the equivalent remote Streamable HTTP URL and header fields for your client. This project serves MCP over HTTP and does not provide a stdio launcher.

For local protocol inspection, the MCP Inspector can connect to the same URL; provide the API key as an HTTP header in its connection settings:

```bash
npx @modelcontextprotocol/inspector
```

## Key management

`manage_keys.py` runs on the host and needs only Python's standard library:

```bash
python manage_keys.py create --client <client-name>
python manage_keys.py list
python manage_keys.py revoke --client <client-name>
```

Revocation takes effect on the next HTTP or MCP request. Missing or invalid keys receive HTTP `403` responses.

## Script files and data

Put scripts in `./scripts`; the included Compose file mounts that directory with read/write access. If your scripts do not need to modify their own files, you can add `:ro` to the Compose volume to make it read-only. Scripts can write outputs to `/data`, which maps to `./data` on the host. For example:

```python
from pathlib import Path
Path("/data/result.txt").write_text("done", encoding="utf-8")
print("Wrote result.txt")
```

The API captures standard output and standard error and returns them to the caller. Do not print secrets into either stream.

## Configuration and deployment

Compose mounts `./scripts`, `./data`, `config.yaml`, and `keys.json` into the container. Route and key file changes take effect without a restart. After changing Python dependencies or server code, rebuild the image manually, then recreate the container:

```bash
docker build -t midas_trigger:0.1 .
docker compose up -d --force-recreate
```

The pinned FastAPI and Uvicorn versions satisfy the newer Starlette and Uvicorn requirements pulled in by the MCP SDK on Python 3.14.

Port `9020` is exposed by default. Put the service behind TLS and restrict network access appropriately before exposing it outside a trusted network. The same API key authorizes every configured script route and both protocols.

The MCP SDK validates the incoming `Host` header to reduce DNS rebinding risk. The Compose defaults allow local connections. When serving the MCP endpoint through a public hostname or reverse proxy, set `MCP_ALLOWED_HOSTS` in the shell or a Compose `.env` file to the host patterns clients use, for example `mcp.example.com:*,localhost:*`. Browser based MCP clients also send an `Origin` header; list permitted origins in `MCP_ALLOWED_ORIGINS`, such as `https://inspector.example.com`. Keep these lists as narrow as the deployment allows.

## Project layout

```text
main.py                 FastAPI HTTP API and mounted MCP Streamable HTTP server
config.yaml             Hot-reloaded path-to-script mappings
keys.json               Hashed API keys (managed by manage_keys.py)
manage_keys.py          Host-side key management CLI
scripts/                Python and Shell scripts
data/                   Example persistent output directory
Dockerfile              Python 3.14 image definition
docker-compose.yml      Starts the prebuilt midas_trigger:0.1 image
.github/workflows/     Publishes version-tagged images to GitHub Packages
```
