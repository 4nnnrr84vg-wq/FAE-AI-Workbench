# FAE AI Workbench Web MVP

## 定位

这是一个 FAE-研发协作工作台，不是泛用聊天机器人。MVP 的重点是把客户问题转成可处理的信息流：

客户消息 -> 结构化问题 -> 资料检索 -> 可选工程检索 -> 日志初筛 -> 客户回复 -> 内部工单。

## 模块

1. FAE Inbox
   - 接口：`POST /api/inbox/parse`
   - 输出客户、型号、SDK/固件版本、现象、错误码、附件、缺失信息、优先级、建议负责模块。

2. Knowledge Base / RAG
   - 接口：`POST /api/kb/query`
   - 状态：`GET /api/kb/status`
   - 重建索引：`POST /api/kb/reindex`
   - 资料来源：`reference/documents/`、`file_library/`
   - 支持：`.md`、`.txt`、`.log`、`.csv`、`.json`、`.yaml`、`.c`、`.h`、`.py`、`.pdf`、`.docx`、`.xlsx`
   - 返回：完整资料名、对应问题、命中片段、检索模式。

3. Project Context
   - 输入：本地工程路径，可为空。
   - 检索：源码、头文件、配置文件、工程文件、README、日志。
   - 返回：工程文件名、行号、相关配置/实现片段。

4. SDK Version Resolver
   - 输入：SDK 版本，例如 `v2.3.1`。
   - 可选配置：GitLab 地址、项目、token、ref pattern。
   - 输出：匹配到的 tag/branch、commit、Release Notes 片段。
   - 作用：让“SDK v2.3.1 有没有已知问题/升级后为什么异常”这类问题能和真实版本对应起来。

5. Log Analyzer
   - 接口：`POST /api/logs/analyze`
   - 输出关键错误行、错误码、模块归属、时间线、上下文、初步假设、缺失信息、检查清单。

6. FAE Response Generator
   - 接口：`POST /api/responses/draft`
   - 输出简洁客户回复：相关资料、初步处理方案、需补充信息。

7. Internal Ticket Generator
   - 接口：`POST /api/tickets/generate`
   - 输出研发工单：问题摘要、客户环境、关键日志、相关资料、初步判断、需研发确认事项。

8. Workbench
   - 接口：`POST /api/workbench/run`
   - 串联完整流程。

## 检索模式

`file_scan`：

- 直接扫描当前资料文件。
- 不依赖 Qdrant。
- 适合本地快速验证，也能保证资料来源真实。

`qdrant_vector`：

- 对资料解析、分块、生成 embedding，写入 Qdrant。
- 查询时走向量召回。
- 命中的资料仍来自当前文件资料库，不生成虚构资料。

`project_scan`：

- 当用户填写本地工程路径时启用。
- 用于回答“客户其实只是不会配工程/不懂调用顺序”的简单问题。
- 结果会和资料库依据一起进入 AI 简洁总结。

`gitlab_sdk`：

- 当配置 GitLab 且输入 SDK 版本时启用。
- 会尝试把版本号映射到 tag/branch/release。
- 结果会作为版本依据进入资料回答和客户回复。

## 使用方式

启动后端：

```powershell
cd D:\wechat_bot\wechat_bot
.\install_web_backend_deps.bat
.\run_web_backend.bat
```

启动前端：

```powershell
cd D:\wechat_bot\wechat_bot
.\run_web_frontend.bat
```

访问：

- 前端：http://127.0.0.1:3000
- 后端：http://127.0.0.1:8000/health

重建向量索引：

```powershell
.\reindex_kb.bat
```

检查索引：

```powershell
curl http://127.0.0.1:8000/api/kb/status
```

## MVP 可交付标准

当前版本达到 MVP 的条件：

- 能读取当前资料库文件，而不是只返回泛泛 AI 回答。
- 每条资料命中都有资料名、对应问题、命中片段。
- 客户回复短、直接、可复制。
- 日志分析明确定位为初步假设和检查清单。
- Qdrant 不可用时系统仍可工作。

仍不适合承诺正式生产的部分：

- PostgreSQL/Redis 还没有完整接入业务持久化和异步任务。
- 扫描版 PDF 需要 OCR 管线。
- 向量召回质量取决于 embedding 模型；本地模式适合离线运行，正式交付建议配置专业 embedding API。
- 还没有权限系统、客户数据隔离、操作审计。
