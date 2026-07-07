# FAE AI Workbench

面向 FAE 支持流程的本地 Web MVP，同时保留原有微信/剪贴板助手能力。

## 核心能力

- FAE Inbox：从客户消息、群聊上下文、日志、附件名中整理客户问题。
- 资料库检索：检索 `reference/documents/` 和 `file_library/` 中的当前文件资料，返回完整资料名、对应问题、命中片段。
- 工程上下文：可选输入本地客户工程路径，系统会检索工程源码/配置并和资料库一起回答。
- SDK 版本关联：可选关联 GitLab，输入 SDK 版本后自动找到对应 tag/branch、commit 和 Release Notes。
- RAG 索引：可用 Qdrant 对资料 chunk 建向量索引；未建索引时自动使用文件扫描。
- 日志初筛：提取关键错误行、错误码、模块归属、上下文、初步假设和检查清单。
- 客户回复：生成简洁 FAE 沟通稿，只说相关资料、初步处理方案、还需补充的信息。
- 内部工单：生成给研发看的 Markdown 问题报告。

## 快速运行

后端：

```powershell
cd D:\wechat_bot\wechat_bot
.\install_web_backend_deps.bat
.\run_web_backend.bat
```

前端：

```powershell
cd D:\wechat_bot\wechat_bot
.\run_web_frontend.bat
```

访问：

- 前端：http://127.0.0.1:3000
- 后端健康检查：http://127.0.0.1:8000/health

## API Key

复制模板：

```powershell
copy .env.web.example .env.web
```

填写：

```text
MODEL_API_BASE_URL=https://api.deepseek.com/v1
MODEL_API_KEY=你的 API Key
MODEL_API_MODEL=deepseek-chat
```

不要把 `.env` 或 `.env.web` 打包发给别人。

## 资料库与 RAG

直接查资料库时，系统会扫描当前资料文件：

```text
retrieval_mode=file_scan
```

如果填写了本地工程路径，回答会额外包含工程命中：

```text
retrieval_mode=file_scan+project_scan
```

启动 Qdrant 并重建索引后，命中向量索引时显示：

```text
retrieval_mode=qdrant_vector
```

重建索引：

```powershell
cd D:\wechat_bot\wechat_bot
.\reindex_kb.bat
```

检查状态：

```powershell
curl http://127.0.0.1:8000/api/kb/status
```

看到以下字段说明向量索引可用：

```text
qdrant_ok=true
collection_exists=true
indexed_points>0
```

## GitLab SDK 版本关联

如果 SDK 版本在 GitLab 上，用 `.env.web` 配置：

```text
GITLAB_BASE_URL=https://gitlab.example.com
GITLAB_PROJECT=firmware/sdk-xc65
GITLAB_TOKEN=你的 GitLab Personal Access Token
```

`GITLAB_PROJECT` 可以填数字项目 ID，也可以填 `group/subgroup/project` 路径。

如果 tag/branch 命名不是默认规则，可以改：

```text
GITLAB_REF_PATTERNS={version},v{plain},sdk-{version},release/{version}
```

例如输入 `v2.3.1` 时，系统会尝试：

- `v2.3.1`
- `2.3.1`
- `sdk-v2.3.1`
- `sdk-2.3.1`
- `release/v2.3.1`
- `release/2.3.1`

解析成功后，知识库回答会多一条 `gitlab_sdk` 依据，包含对应 ref、commit、Release Notes 片段。

## Docker

安装 Docker Desktop 后可启动完整栈：

```powershell
docker compose up --build
```

包含 PostgreSQL、Redis、Qdrant、MinIO、backend、frontend。当前 MVP 已使用 Qdrant 和对象存储；PostgreSQL/Redis 仍主要作为后续持久化和任务队列预留。

## 打包给别人

不要打包：

- `.env`
- `.env.web`
- `.venv312`
- `apps/frontend/node_modules`
- `apps/frontend/.next`
- `apps/frontend/.npm-cache`
- `.web_mvp_storage`
- `logs`

对方需要安装：

- Python 3.12
- Node.js 22.x
- 自己的模型 API Key

更多说明见 [docs/web_mvp.md](docs/web_mvp.md)。
