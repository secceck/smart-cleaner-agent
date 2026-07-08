# 🧹 扫地机器人智能客服 Agent

基于 **ReAct Agent + RAG** 的本地单机智能客服系统，为扫地机器人用户提供全场景智能问答服务。

## 技术架构

```
Browser (Streamlit :8501) → FastAPI (:8000) → FreeLLMAPI (:3001) Docker
                                    ↓
                       SQLite (chat.db)  +  Chroma (chroma_db/)
```

| 层级 | 技术栈 |
|------|--------|
| 后端框架 | FastAPI + LangChain + LangGraph |
| 智能体模式 | LangGraph ReAct 循环推理 (Think → Act → Observe) |
| 大模型网关 | [FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi/tree/main)（Docker 本地容器，兼容 OpenAI 接口） |
| 向量存储 | Chroma 本地文件持久化 |
| 文本处理 | RecursiveCharacterTextSplitter 递归分片 |
| 前端 | Streamlit 轻量化 Python Web 页面 |
| 数据存储 | SQLite 轻量本地数据库 |
| 包管理 | uv（Python 3.14+） |

## 功能模块

### ReAct 智能体引擎
- 基于 LangGraph StateGraph 实现 Think → Act → Observe 循环
- 支持工具并行调用（ToolNode `asyncio.gather`）
- **模型故障转移**（最多 20 次重试）：自动跳过宕机/限流模型，切换下一个可用模型
- **启动健康检查**：探测前 8 个模型的可用性，死模型自动排到队尾
- **会话粘性**：30 分钟内复用同一模型，减少冷启动延迟
- SSE 流式输出，文字逐字实时渲染

### RAG 本地知识库
- 支持 PDF / TXT 文档上传（单文件最大 50MB）
- RecursiveCharacterTextSplitter 递归分片（chunk_size=1024, overlap=200）
- Chroma 向量库持久化存储
- Top-K 相似度检索（默认 K=3）
- **内置知识库文档**：`data/knowledge/smart_cleaner_manual.txt`（5 款产品型号、10 个错误码及解决方案、保养指南、FAQ）

### 内置工具集（7 个）

| 工具 | 功能 | 数据来源 |
|------|------|---------|
| `weather_query` | 查询城市实时天气 + 7日预报 + 气象预警（温度/湿度/AQI/风力/能见度/降雨量） | 中国天气网（双 API 互补）|
| `get_location` | 获取用户地理位置 | 浏览器定位 / 手动输入 |
| `get_user_id` | 获取当前会话用户标识 | 会话上下文 |
| `query_usage_records` | 查询设备清扫使用记录（时长/面积/耗材/故障/电池） | 模拟数据生成 |
| `product_info_search` | 产品参数、功能说明、型号对比检索 | RAG 知识库 |
| `troubleshoot` | 故障排查（自动提取错误码 + 语义搜索解决方案） | RAG 知识库 |
| `fill_context_for_report` | **报告上下文聚合 + 触发动态 Prompt 切换** | 工具调用链 |

#### 天气工具亮点
- **全国城市全覆盖**：静态映射表 + `toy1.weather.com.cn/search` 动态搜索兜底
- **双 API 互补**：`weather_index`（实时观测，每 5 分钟更新）+ `dingzhi`（预报更新更快，前晚 18 点即发布次日预报）
- **自动选最新预报**：对比两个接口的发布时间，取较新者
- **日期零歧义**：使用 `dataSK.date` 官方日期字段（与 weather.com.cn 网站同步），明确标注"预报日期"与"发布时间"
- **气象预警**：自动展示蓝色/黄色/橙色/红色预警详情

### 清扫报告生成（动态 Prompt 切换）

用户说"生成报告"时，Agent 按四步流程执行：

```
Step 1: 并行收集     Step 2: 查询记录      Step 3: 触发切换       Step 4: 生成报告
get_user_id ─┐      query_usage_records   fill_context_for_report   REPORT_PROMPT
get_location ─┤           │                      │                  ┌─────────────┐
weather_query─┘           │                      │                  │ 设备使用概况 │
                          ↓                      ↓                  │ 清扫数据统计 │
                     获取清扫统计          系统检测到调用           │ 设备健康状态 │
                                         自动切换 Prompt           │ 耗材更换建议 │
                                                                  │ 季节清扫适配 │
                                                                  └─────────────┘
```

- **`fill_context_for_report`**：Agent 调用此工具表示数据已就绪，系统自动从通用 `SYSTEM_PROMPT` 切换到 `REPORT_PROMPT`
- **REPORT_PROMPT**：强制标准 Markdown 模板，五大模块，禁止编造数据
- 数据缺失时引导 Agent 补全，确保报告基于真实数据

## 快速开始

### 前置条件

1. **Docker** 已启动，FreeLLMAPI 容器运行中
2. **Python 3.14+** + **uv** 包管理器
3. 端口 3001、8000、8501 未被占用

### 1. 部署 FreeLLMAPI 模型网关

> 📦 FreeLLMAPI GitHub: [https://github.com/tashfeenahmed/freellmapi](https://github.com/tashfeenahmed/freellmapi/tree/main)
>
> FreeLLMAPI 是一个兼容 OpenAI 接口的本地大模型网关，支持接入 60+ 模型供应商（OpenAI / Anthropic / DeepSeek / 阿里百炼 / 硅基流动 等），统一暴露为 `/v1/chat/completions` 和 `/v1/embeddings` 端点。
> 本项目通过 FreeLLMAPI 实现模型的自动路由、故障转移和多模型聚合。

#### 1.1 拉取并启动 Docker 容器

```bash
docker run -d \
  --name freellmapi \
  -p 3001:3001 \
  --restart always \
  -v freellmapi-data:/app/data \
  freellmapi:latest
```

| 参数 | 说明 |
|------|------|
| `-p 3001:3001` | 映射容器 3001 端口到宿主机 |
| `--restart always` | Docker 启动时自动重启容器 |
| `-v freellmapi-data:/app/data` | 持久化 API Key 配置和数据库 |

#### 1.2 配置模型供应商（Web UI）

启动后访问 **http://127.0.0.1:3001** 进入管理后台：

1. **添加 API Key**：点击 `Provider Keys` → 输入各模型供应商的 API Key
   - OpenAI: `sk-xxx`
   - Anthropic: `sk-ant-xxx`
   - 阿里百炼: `sk-xxx`
   - 硅基流动: `sk-xxx`
   - DeepSeek: `sk-xxx`
   - 等等...
2. **启用/禁用供应商**：在 `Providers` 页面开关对应供应商
3. **获取 FreeLLMAPI Token**：在 `Settings` → `API Keys` 生成一个 Token，填入 `server/.env` 的 `FREELLMAPI_API_KEY`

#### 1.3 模型路由器说明

FreeLLMAPI 提供两种路由模式：

| 路由器 | 模型名 | 说明 |
|--------|--------|------|
| **Auto Router** | `auto` | 自动选择最快的可用模型，内部处理故障转移 |
| **Fusion Panel** | `fusion` | 多模型并行回答，由一个 Judge 模型投票选出最佳答案 |

> ⚠️ 本项目**自动过滤**了 `auto` 和 `fusion`（它们是路由器不是真实模型），直接使用后端真实模型名（如 `deepseek-v4-pro`、`qwen3-coder-480b`）。

#### 1.4 验证模型服务

```bash
# 查看可用模型列表
curl http://127.0.0.1:3001/v1/models \
  -H "Authorization: 你的FreeLLMAPI-Token"

# 测试对话
curl http://127.0.0.1:3001/v1/chat/completions \
  -H "Authorization: 你的FreeLLMAPI-Token" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"你好"}]}'

# 测试嵌入模型
curl http://127.0.0.1:3001/v1/embeddings \
  -H "Authorization: 你的FreeLLMAPI-Token" \
  -H "Content-Type: application/json" \
  -d '{"model":"text-embedding-3-small","input":"测试文本"}'
```

#### 1.5 常用模型推荐

| 用途 | 推荐模型 | 说明 |
|------|---------|------|
| 聊天/对话 | `deepseek-v4-pro` | DeepSeek V4 Pro，综合能力强 |
| 代码/逻辑 | `qwen3-coder-480b` | Qwen3 Coder 480B，代码能力强 |
| 快速响应 | `deepseek-v4-flash` | 轻量快速版本 |
| 多模态 | `gemini-2.5-flash` | Gemini 2.5 Flash，支持图片 |
| 嵌入 | `text-embedding-3-small` | OpenAI 兼容嵌入模型，1024 维 |

> 💡 **启动时健康检查**：本项目启动时会自动探测前 8 个模型的可用性，正常模型排到队首优先使用，不可用模型排到队尾。

### 2. 配置环境变量

编辑 `server/.env`：

```env
FREELLMAPI_BASE_URL=http://127.0.0.1:3001/v1
FREELLMAPI_API_KEY=你的API Token（不需要 Bearer 前缀）
FREELLMAPI_CHAT_MODEL=auto
FREELLMAPI_EMBEDDING_MODEL=text-embedding-3-small
```

### 3. 初始化目录 & 导入知识库

```bash
mkdir -p data/chroma_db data/knowledge logs
```

首次使用需导入内置知识库：

```bash
cd server
uv run python -c "
from app.rag.loader import process_document
process_document('../data/knowledge/smart_cleaner_manual.txt', 'smart_cleaner_manual.txt')
"
```

### 4. 启动后端

```bash
cd server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动日志应显示：
```
✅ 服务启动完成！
   - FreeLLMAPI: ✅ 已连接
   - Chroma: ✅ 已就绪
   - 可用模型: [qwen3-coder-480b, deepseek-v4-pro, ...]（已过滤 auto/fusion 路由器）
```

验证：访问 `http://127.0.0.1:8000/docs` 查看 API 文档

### 5. 启动前端

```bash
cd web
uv run streamlit run app.py --server.port 8501
```

访问：**http://127.0.0.1:8501**

## 项目结构

```
smart-cleaner-agent/
├── server/                     # FastAPI 后端
│   ├── .env                    # 环境变量配置
│   └── app/
│       ├── main.py             # 服务入口、CORS、生命周期
│       ├── agents/             # ReAct 智能体引擎
│       │   └── react_agent.py  # LangGraph 状态图定义
│       ├── tools/              # 6 个内置工具
│       │   ├── __init__.py     # 工具注册表
│       │   ├── weather.py      # 天气查询（weather.com.cn 双 API）
│       │   ├── location.py     # 位置获取（内存缓存）
│       │   ├── user.py         # 用户标识
│       │   ├── usage_records.py # 使用记录查询（多日期格式）
│       │   ├── product_info.py # 产品信息 RAG 检索
│       │   ├── troubleshoot.py # 故障排查（正则提取错误码 + RAG）
│       │   └── report_context.py # 报告上下文聚合 + 动态 Prompt 触发
│       ├── rag/                # RAG 知识库
│       │   ├── vectorstore.py  # Chroma 向量库单例
│       │   ├── loader.py       # 文档加载与分片
│       │   └── retriever.py    # 相似度检索
│       ├── api/v1/             # REST API 接口
│       │   ├── chat.py         # SSE 对话 + 会话管理
│       │   └── knowledge.py    # 知识库上传/检索
│       ├── models/             # 数据模型
│       │   ├── database.py     # SQLite 持久化层
│       │   └── schemas.py      # Pydantic 校验模型
│       ├── common/             # 公共模块
│       │   ├── config.py       # 配置管理（绝对路径 .env）
│       │   ├── logger.py       # 日志（按天分割/30天清理）
│       │   └── llm_factory.py  # 模型故障转移 + 健康检查
│       └── prompts/            # 提示词模板
│           ├── system_prompt.py
│           └── report_prompt.py
├── web/                        # Streamlit 前端
│   ├── .streamlit/secrets.toml # 前端配置
│   ├── app.py                  # 页面入口
│   ├── components/             # UI 组件
│   │   ├── sidebar.py          # 侧边栏
│   │   ├── chat.py             # 消息渲染
│   │   ├── knowledge.py        # 知识库管理
│   │   └── report.py           # 报告卡片
│   └── utils/                  # 工具函数
│       ├── api_client.py       # API 客户端（SSE 解析）
│       ├── session.py          # 会话状态管理
│       └── location.py         # 浏览器定位
├── data/                       # 持久化数据
│   ├── chroma_db/              # Chroma 向量库
│   ├── knowledge/              # 上传的原始文档 + 内置知识库
│   │   └── smart_cleaner_manual.txt  # 内置产品知识库
│   └── chat.db                 # SQLite 数据库
├── logs/                       # 日志文件（30天自动清理）
├── pyproject.toml              # uv 依赖配置
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/chat/stream` | SSE 流式对话 |
| `GET` | `/api/v1/chat/sessions` | 获取会话列表 |
| `POST` | `/api/v1/chat/sessions` | 创建新会话 |
| `DELETE` | `/api/v1/chat/sessions/{id}` | 删除会话 |
| `GET` | `/api/v1/chat/messages?thread_id=` | 获取消息记录 |
| `DELETE`| `/api/v1/chat/messages?thread_id=` | 清空消息 |
| `POST` | `/api/v1/knowledge/upload` | 上传知识库文档 |
| `POST` | `/api/v1/knowledge/search` | 知识库检索 |
| `POST` | `/api/v1/location` | 设置用户位置（前端调用）|
| `GET` | `/api/v1/health` | 健康检查 |

## 常见问题

### 端口被占用
```bash
# Windows
netstat -ano | findstr "8000"
taskkill -F -PID <PID>

# Mac/Linux
lsof -i :8000
kill -9 <PID>
```

### FreeLLMAPI 连接失败
- 确认 Docker 容器运行中：`docker ps | grep freellmapi`
- 确认 API Key 正确配置在 `server/.env`（**不需要** `Bearer` 前缀）
- 确认模型在 FreeLLMAPI 后台已配置有效密钥
- 启动日志中会显示可用模型列表，`auto`/`fusion` 已被自动过滤

### AI 不回复 / 回复异常
- 检查日志中是否有 `429`（限流）或 `502`（上游 Key 过期）错误
- 系统内置**启动健康检查**：不可用模型自动排到队尾，优先使用可用模型
- 429（Rate Limit）会自动退避重试（2^n 秒，最多 30 秒）
- 5xx 服务端错误会自动切换下一个模型

### 天气查询不到城市
- 支持全国任意中国城市，无需在映射表中
- 系统自动通过 `toy1.weather.com.cn/search` 动态搜索城市代码
- 如仍查不到，请尝试使用城市的标准名称（去掉"市"、"县"等后缀）

### 知识库检索无结果
- 确保已导入内置知识库：`data/knowledge/smart_cleaner_manual.txt`
- 确认 `FREELLMAPI_EMBEDDING_MODEL` 指向有效的嵌入模型
- 查看日志 `logs/app_*.log` 排查具体错误

### URL 地址异常
- 全局统一使用 `127.0.0.1`（不要用 `localhost`）
- 确认 `web/.streamlit/secrets.toml` 中 `API_BASE_URL` 配置正确

## 已修复的关键问题

| 问题 | 根因 | 修复 |
|------|------|------|
| `fusion` 模型报错 | 路由器模型未被过滤 | 过滤列表扩展为 `{auto, fusion}` |
| API 调用不重试 | OpenAI SDK 错误类型不匹配 | 429/5xx 统一进入重试分支 |
| 请求第一发必定失败 | 死模型排在列表第一位 | 启动健康检查，可用模型排前 |
| `.env` 找不到 | 路径依赖 CWD | 改为绝对路径 |
| Authorization 401 | 多了 `Bearer` 前缀 | 去掉前缀 |
| 天气显示昨天日期 | `fctime` 发布时间被误读 | 使用 `dataSK.date` + 明确标注 |
| 天气查不到小城市 | 仅静态映射表 | 动态搜索 API 兜底 |
| 知识库匹配度显示错误 | Chroma 距离值未转换 | 转为 0-100% 匹配度 |
