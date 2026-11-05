# Docker 脚本触发 API 与 MCP 服务

English: [README.md](README.md)

这是一个基于 Python 3.14 的轻量级 Docker 服务，可通过普通 HTTP API 和 MCP 服务触发配置好的 Python 或 Shell 脚本。两个接口共用路由配置、API 密钥、超时设置和脚本执行逻辑。

## 功能

- HTTP 接口保留配置中定义的请求路径和 JSON 响应格式。
- MCP 使用 **Streamable HTTP** 传输，地址为 `/mcp`，提供 `list_scripts` 和 `run_script` 工具。
- HTTP 和 MCP 请求共用 `X-API-Key` 认证。
- `config.yaml` 和 `keys.json` 会在请求时读取，文件修改后无需重启容器即可生效。
- 向调用方返回脚本输出、退出状态、运行时间和超时信息。
- 容器以非 root 用户 `chksys`（UID/GID 8000）运行。

## 启动服务

需要安装 Docker 和 Docker Compose。镜像构建与服务启动分开执行。本地镜像名称为 `midas_trigger:0.1`；Compose 只使用本地镜像，不会构建或拉取镜像。

```bash
docker build -t midas_trigger:0.1 .
```

### 推送 Git tag 时自动发布

`.github/workflows/publish-image.yml` 会在推送版本 tag（例如 `0.1` 或 `v0.1`）时自动发布镜像。它会将对应版本标签和 `latest` 推送至 GitHub Container Registry，镜像地址为 `ghcr.io/<OWNER>/<REPO>`，并创建同名 GitHub Release，附带 `linux/amd64` 和 `linux/arm64` 两种架构的压缩 Docker 镜像归档。GitHub Actions 使用仓库内置的 `GITHUB_TOKEN`，无需个人访问令牌。

```bash
git tag 0.1
git push origin 0.1
```

工作流完成后，可在仓库的 **Packages** 页面查看镜像。若部署机器可以访问 GHCR，可拉取版本并改成本地 Compose 使用的镜像名：

```bash
docker pull ghcr.io/<OWNER>/<REPO>:0.1
docker tag ghcr.io/<OWNER>/<REPO>:0.1 midas_trigger:0.1
```

也可以从 GitHub Release 下载对应架构的 `midas_trigger-<TAG>-linux-<ARCH>.tar.gz`，导入本地 Docker：

```bash
gunzip -c midas_trigger-0.1-linux-amd64.tar.gz | docker load
docker tag midas_trigger:0.1-linux-amd64 midas_trigger:0.1
```

内网或离线部署时，将该本地标签保存为镜像归档并传输，步骤见下方说明。

在可以访问所需基础镜像和 Python 包源的机器上手动构建镜像。迁移到内网或离线环境时，先导出镜像并将归档文件传到目标机器，然后导入：

```bash
docker save -o midas_trigger.tar midas_trigger:0.1
# 将 midas_trigger.tar 传到目标机器
docker load -i midas_trigger.tar
```

进入包含 `docker-compose.yml` 的目录，启动服务：

```bash
docker compose up -d
```

服务监听端口 `9020`。HTTP API 地址为 `http://localhost:9020`，MCP 地址为 `http://localhost:9020/mcp`。

仓库当前包含一个仅供本地测试的 API Key（也已将其哈希写入 `keys.json`），可直接验证示例接口：

```bash
curl -H "X-API-Key: 8e6b78e064f0b2242257c3b76d8cf03b47a6bd4ded1f5cb9" \
  http://localhost:9020/helloworld
```

**正式使用前请删除 README 中的这个测试 Key，并从 `keys.json` 撤销 `test`（`python manage_keys.py revoke --client test`），然后创建并安全保存自己的 Key。不要将真实密钥提交到代码仓库。**

创建正式使用的密钥：

```bash
python manage_keys.py create --client my-app
```

命令只会显示一次明文密钥，请妥善保存。`keys.json` 中只保存密钥的 SHA-256 哈希。

也可以通过 `API_KEYS` 环境变量提供以逗号分隔的明文密钥。无论密钥来自环境变量还是 `keys.json`，均可访问 HTTP 和 MCP。不要将真实密钥提交到代码仓库。

## HTTP 接口

路由在 `config.yaml` 中配置，例如：

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

每条路由将一个 URL 路径映射到 `/scripts` 下的脚本。支持 `.py` 和 `.sh` 扩展名，分别使用 `python` 和 `bash` 执行。`method` 默认为 `GET`，`timeout` 默认为 60 秒。位置参数和具名参数都会作为命令行参数传给脚本。

### 位置参数与具名参数

对于 `GET` 路由，重复使用查询参数 `arg` 传入位置参数；其他查询参数均作为具名参数：

```bash
curl -G -H "X-API-Key: <YOUR_API_KEY>" \
  --data-urlencode "arg=monthly report" \
  --data-urlencode "arg=2026" \
  --data-urlencode "format=csv" \
  http://localhost:9020/build-report
```

对于 `POST` 路由，请发送包含可选 `args` 数组和 `kwargs` 对象的 JSON：

```bash
curl -X POST -H "X-API-Key: <YOUR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"args":["monthly report",2026],"kwargs":{"format":"csv"}}' \
  http://localhost:9020/build-report
```

每个位置参数按原顺序成为一个命令行参数；每个具名参数会转换成 `--name=value`。参数值可以是字符串、数字或布尔值。Python 脚本可通过 `sys.argv` 或 `argparse` 读取；Shell 脚本可通过 `$1`、`$2` 等读取位置参数，并按常规方式解析具名选项。服务会将参数作为独立进程参数传递，不会将参数内容当作 Shell 命令执行。

调用示例：

```bash
curl -H "X-API-Key: <YOUR_API_KEY>" http://localhost:9020/helloworld
```

成功或失败的脚本执行都会返回 JSON，包含 `status`、`script`、请求时间、耗时、`stdout` 和 `stderr`。脚本以非零状态退出时，`status` 为 `failed`，并返回 `exit_code`；超时时 `status` 为 `timeout`。配置和路由错误使用标准 HTTP 错误状态码。

## MCP 接口

将 MCP 客户端配置为通过 Streamable HTTP 连接 `http://localhost:9020/mcp`，并添加以下 HTTP 请求头：

```text
X-API-Key: <YOUR_API_KEY>
```

服务提供两个工具：

- `list_scripts`：返回当前配置的路由路径、脚本名称、HTTP 方法和超时时间。
- `run_script`：接收 `path`（例如 `/build-report`），以及可选的 `args` 数组和 `kwargs` 对象，然后执行对应脚本。参数格式与 HTTP 接口一致。

支持远程 Streamable HTTP 服务和自定义请求头的客户端，可参考以下 `mcp.json` 配置：

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

不同客户端的配置格式可能不同，请按客户端要求填写远程 Streamable HTTP 地址和请求头。有些客户端只支持本地 stdio MCP 服务，或需要额外的远程服务连接器。本项目提供 HTTP 传输，不提供 stdio 启动器。

如需在本机检查 MCP 协议，可启动 MCP Inspector，并在连接设置中填写同一地址和 API Key 请求头：

```bash
npx @modelcontextprotocol/inspector
```

## 密钥管理

宿主机上的 `manage_keys.py` 只依赖 Python 标准库：

```bash
python manage_keys.py create --client <client-name>
python manage_keys.py list
python manage_keys.py revoke --client <client-name>
```

撤销操作会在下一次 HTTP 或 MCP 请求时生效。缺少密钥或密钥无效时，服务返回 HTTP `403`。

## 脚本与数据文件

将脚本放入 `./scripts`。当前 Compose 配置以读写方式挂载该目录；如果脚本不需要修改自身文件，可以在 Compose volume 后添加 `:ro` 将其设为只读。脚本可以将输出写入 `/data`，该目录对应宿主机的 `./data`。例如：

```python
from pathlib import Path
Path("/data/result.txt").write_text("done", encoding="utf-8")
print("Wrote result.txt")
```

API 会捕获标准输出和标准错误并返回给调用方。不要在输出中打印密钥等敏感信息。

## 配置与部署

Compose 会挂载 `./scripts`、`./data`、`config.yaml` 和 `keys.json`。路由和密钥文件修改后无需重启即可生效。修改 Python 依赖或服务代码后，手动重建镜像并重新创建容器：

```bash
docker build -t midas_trigger:0.1 .
docker compose up -d --force-recreate
```

固定的 FastAPI 和 Uvicorn 版本与 Python 3.14 下 MCP SDK 所需的新版 Starlette 和 Uvicorn 依赖兼容。

默认开放端口 `9020`。将服务暴露到可信网络之外前，请配置 TLS 并限制网络访问。同一个 API Key 可以调用所有已配置脚本路由以及两种协议。

MCP SDK 会检查请求的 `Host` 头，以降低 DNS 重绑定风险。Compose 默认只允许本机连接。若通过公网域名或反向代理提供 MCP 服务，请在 shell 或 Compose `.env` 文件中设置 `MCP_ALLOWED_HOSTS`，填写客户端使用的 Host 模式，例如 `mcp.example.com:*,localhost:*`。基于浏览器的 MCP 客户端也会发送 `Origin` 请求头；请通过 `MCP_ALLOWED_ORIGINS` 列出允许的来源，例如 `https://inspector.example.com`。允许列表应尽量精确。

## 项目结构

```text
main.py                 FastAPI HTTP API 和挂载的 MCP Streamable HTTP 服务
config.yaml             热加载的路径到脚本映射
keys.json               API Key 哈希（由 manage_keys.py 管理）
manage_keys.py          宿主机密钥管理命令行工具
scripts/                Python 和 Shell 脚本
data/                   示例持久化输出目录
Dockerfile              Python 3.14 容器镜像定义
docker-compose.yml      启动预构建的 midas_trigger:0.1 镜像
.github/workflows/     将版本 tag 对应的镜像发布到 GitHub Packages
```
