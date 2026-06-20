# 知识库项目开发复盘总结

> 本文档系统记录本项目（个人知识库 / RAG 检索系统）开发全流程中遇到的技术坑点、排障经验以及核心开发要点，旨在为后续项目复盘、代码审查以及同类项目开发提供可追溯的参考依据。

| 项目代号 | 知识库 (Knowledge OS) |
| --- | --- |
| 技术栈 | FastAPI · LangChain Core · React 18 · TypeScript · 自研 JSON VectorStore · DeepSeek |
| 开发语言 | Python 3.13 · TypeScript |
| 文档版本 | v1.0 (2026-06-12) |
| 复盘范围 | 全项目，重点为「智能问答」与「文档管理」两个核心模块 |

> 文档元信息
>
> - **维护人**：项目主开发
> - **更新机制**：每完成一轮重要功能或排障后追加一节
> - **本文档不进入 README**（README 只展示功能，不展示开发问题）

---

## 目录

- [1. 项目架构与关键技术选型](#1-项目架构与关键技术选型)
- [2. 典型排障 ⭐](#2-典型排障-)
  - [2.1 智能问答元数据查询异常 ⭐⭐⭐](#21-智能问答元数据查询异常)
  - [2.2 文档分类下拉框只显示「默认」](#22-文档分类下拉框只显示默认)
  - [2.3 FastAPI 路由顺序冲突导致端点静默失效](#23-fastapi-路由顺序冲突导致端点静默失效)
  - [2.4 相对路径在不同 CWD 下解析错误](#24-相对路径在不同-cwd-下解析错误)
  - [2.5 工作台折叠功能被错误地写到不存在的页面](#25-工作台折叠功能被错误地写到不存在的页面)
  - [2.6 前端 HMR 缓存与"代码写了不生效"陷阱](#26-前端-hmr-缓存与代码写了不生效陷阱)
  - [2.7 浏览器自动化测试触发 React 合成事件失败](#27-浏览器自动化测试触发-react-合成事件失败)
- [3. 核心开发要点](#3-核心开发要点)
- [4. 同类项目开发建议清单](#4-同类项目开发建议清单)
- [5. 复盘元数据](#5-复盘元数据)
- [6. 第二轮修复记录（2026-06-15 ~ 2026-06-16）](#6-第二轮修复记录2026-06-15--2026-06-16)
- [7. 同类项目 RAG 质量优化清单（v2）](#7-同类项目-rag-质量优化清单v2)
- [8. 第三轮修复记录（2026-06-18）— Qwen3 ModelScope API 接入](#8-第三轮修复记录2026-06-18--qwen3-modelscope-api-接入)

---

## 1. 项目架构与关键技术选型

### 1.1 后端

```
backend/
├── app/
│   ├── api/          # FastAPI 路由层
│   ├── core/         # RAG / LLM / VectorStore / Embedding 中心化服务
│   ├── services/     # 业务服务（document_service、knowledge_graph、search_service）
│   └── models/       # Pydantic 数据模型
├── tests/            # pytest 单元 + 集成测试
└── data/             # 持久化 JSON（documents / vector_store / op_log / categories）
```

### 1.2 前端

```
frontend/src/
├── pages/            # 一级路由：Home / Documents / Graph / Chat / Chunks / Settings
├── components/       # 可复用：Graph2D、DraggableLegend、DocumentDetail...
├── services/         # api.ts 集中封装（fetch / axios）
└── types/            # TypeScript 类型
```

### 1.3 关键架构决策

| 决策 | 取舍 |
| --- | --- |
| **LangChain core + 自研 VectorStore** | 用 `BaseRetriever` / `Document` / `ChatPromptTemplate` 等核心抽象保持兼容性；向量库自研纯 Python + JSON（不依赖 numpy）以避免 18MB+ 模型权重下载。代价：失去 FAISS/Chroma 的 ANN 加速，长尾文档检索性能受限。 |
| **RAG 中心化设计** | 所有问答调用必须经过 `RAGChainService.ask()` / `stream_ask()`。便于统一日志/可观测性/可控参数（如 `categories` 过滤）。 |
| **同步 + 流式双端点** | `/ask` 用于一次性返回（如脚本调用），`/ask/stream` 用于前端打字机效果。两端点逻辑镜像维护。 |
| **JSON 文件持久化** | 无数据库依赖，单机即可运行。代价：并发写需要进程锁；文件体积随文档量增长。 |

---

## 2. 典型排障 ⭐

### 2.1 智能问答元数据查询异常 ⭐⭐⭐

> 本节是本轮复盘的核心案例，按用户要求**完整记录故障表现、多轮修复未解的核心原因、本次最终技术方案与验证结果**。

#### 2.1.1 故障表现

**用户报告（场景 A）**：在「智能问答」页面向知识库提问 `agent是什么？`，系统错误返回：

> 知识库中暂未找到与该问题高度相关的内容。

**用户报告（场景 B）**：提问 `现在知识库有哪些内容？`，系统同样返回：

> 知识库中暂未找到相关资料。

**期望行为**：

- 场景 A：基于知识库中的《01Agent理论基础》《02Agent工具系统》《06_LLM框架实战_Tools》等多份资料，给出 Agent 的定义、原理、工具调用等相关内容。
- 场景 B：直接列出知识库全量文档清单、分类体系、统计数字等基础信息（**元数据级查询，不应走内容检索**）。

#### 2.1.2 此前多轮修复未解决的核心原因

回顾整个排障过程，**修复经历了 2 轮失败 + 1 轮成功**，每一轮的根因诊断都在更深的层次：

| 轮次 | 表面修复 | 失败的根因 |
| --- | --- | --- |
| **第 1 轮** | 怀疑向量库空了 → 触发向量化重建 | 向量库实际有 514 个分块，**不是空的**。修复方向错误。 |
| **第 2 轮（部分成功）** | 将 `SYSTEM_PROMPT` 的「相关度 ≥ 0.3 才引用」阈值降到 0.20 | ✅ 场景 A（"agent是什么？"）修复成功（命中 score=0.299 等），但 ❌ 场景 B（"现在知识库有哪些内容？"）依然答非所问——因为 RAG 检索只能从文本块里找相似内容，**根本无法感知"全量元数据"这种全局性问题**。 |
| **第 3 轮（真正修复）** | 识别元数据查询并走专用路径 | 见下文方案。 |

**根因复盘**：

> **本质问题**：把"内容检索问题"和"元数据查询问题"混入了同一条 RAG 路径。
>
> - RAG 检索本质上是一个**相似度匹配**过程：query → 向量 → top_k 文本块 → LLM 总结。
> - 它的设计目标是从**大量文本中捞出与 query 语义相近的片段**。
> - 当用户问「现在有什么/统计/分类列表」时，**正确答案根本不存在于任何文本块中**——它在 `documents.json` 的元数据里、在分类聚合统计里。
> - 强行用 RAG 检索得到的"top 1"通常是某个文本块里偶然出现的相似词（比如"Multi-Agent"代码示例），LLM 据此生成看似相关但答非所问的答案。
> - **置信度被 RAG 的存在性偏差污染**：哪怕分数 0.169，LLM 也会"努力作答"，而不是说"这个问题不该走 RAG"。

#### 2.1.3 本次最终修复的技术方案

**架构：内容检索 vs 元数据查询的**双路径分流****。

**核心实现**（[rag_chain.py](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/rag_chain.py#L385-L455)）：

```python
# 步骤 1：元数据查询识别
@staticmethod
def _is_meta_query(question: str) -> bool:
    meta_keywords = [
        "有哪些", "有什么", "多少篇", "多少个", "多少", "统计",
        "分类列表", "分类", "什么内容", "哪些文档", "列出", "清单",
        "how many", "what documents", "list", "categories", "summary",
    ]
    q = question.lower().strip()
    return any(kw in q for kw in meta_keywords)

# 步骤 2：元数据快照聚合（直接读 documents.json + VectorStore.count_total）
@staticmethod
def _collect_meta_snapshot(category: str = None) -> dict:
    from app.services.document_service import _documents
    docs = list(_documents.values())
    if category:
        docs = [d for d in docs if d.category == category]
    by_cat = {}
    for d in docs:
        by_cat.setdefault(d.category, []).append({
            "id": d.id, "title": d.title,
            "file_type": d.file_type, "owner": d.owner,
        })
    return {
        "total_documents": len(docs),
        "total_categories": len(by_cat),
        "total_chunks": VectorStore.count_total(),
        "categories": [...],
    }

# 步骤 3：在 ask() / stream_ask() 入口处早返回
if RAGChainService._is_meta_query(question):
    snap = RAGChainService._collect_meta_snapshot()
    # 拼装结构化上下文（数字、清单全部已查询，无幻觉）
    summary_prompt = f"用户问题：{question}\n\n知识库元数据：\n{meta_context}\n\n请基于以上结构化数据回答"
    llm.invoke([HumanMessage(content=summary_prompt)])  # 非流式
    # 或
    for chunk in llm.stream([...]): yield {...}  # 流式
    return  # 关键：直接 return，不进入 HybridRetriever.invoke(question)
```

**配套端点**：[documents.py#L444-L473](file:///d:/code/个人开发项目/202605/知识库/backend/app/api/documents.py#L444-L473)

```python
@router.get("/meta-summary")
async def get_meta_summary(category: str = None):
    """返回知识库元数据全貌（供前端统计面板 / 元数据 API 调用）"""
    ...
```

让元数据既可以走"LLM 总结"路径（用户提问），也可以直接 JSON 返回（前端用）。

**修复要点**：

1. **关键词识别用「语义意图」而非「字面规则」**：覆盖中英文 + 常见同义表达（"有什么/多少/统计/清单"等）。
2. **保持中心化设计**：识别逻辑落在 `RAGChainService`（所有问答的必经之路），不破坏 `/ask` / `/ask/stream` 的双端点镜像。
3. **元数据查询 confidence=1.0**：因为答案完全来自结构化数据，零幻觉。
4. **流式兼容**：流式端点也走相同路径，逐 token 输出 LLM 总结，保持前端打字机效果。

#### 2.1.4 验证结果

**单元 + 集成测试**（[test_meta_query.py](file:///d:/code/个人开发项目/202605/知识库/backend/tests/test_meta_query.py) — 12 项全通过）：

| 测试类 | 覆盖点 |
| --- | --- |
| `TestMetaQueryDetection` | 中英文关键词识别 10+ 例；不误判内容查询 5+ 例；空/None 容错 |
| `TestMetaSnapshot` | 真实 `_documents` 数据聚合；按分类过滤；空分类返回 |
| `TestMetaRAGPath` | mock LLM 验证：元数据查询 bypass HybridRetriever、citations=[]、confidence=1.0；非元数据查询仍走 RAG |
| `TestMetaSummaryAPI` | `/api/documents/meta-summary` 端点正确返回聚合数据；过滤参数生效；未知分类返回空 |
| `TestAskEndpointIntegration` | 端到端 `/api/ai/ask` 命中元数据查询返回零幻觉答案 |

**真实端到端实测**：

| 查询 | 修复前 | 修复后 |
| --- | --- | --- |
| `现在知识库有哪些内容？` | conf=0.169，答「Multi-Agent 路由示例」 | conf=1.0，列「agent 分类 4 篇 + 默认分类 4 篇 + 共 11 篇」 |
| `知识库统计` | RAG 路径 | 元数据路径 |
| `agent 是什么？` | conf=0.299，答 agent 工具调用 | conf=0.299，**仍答 agent**（不误判） |
| `RAG 原理` | RAG 路径 | RAG 路径（不误判） |

**测试运行命令**：

```bash
cd backend
D:\Anaconda\Anaconda\envs\knowledge\python.exe -m pytest tests/test_meta_query.py -v
# ============================== 12 passed ==============================
```

#### 2.1.5 经验提炼（同类项目可复用）

1. **永远为「全局性问题」预留专用通道**：用户的"有什么/统计/分类/列清单"等查询不是"内容相似度问题"，是"数据枚举问题"。RAG 不擅长枚举。
2. **关键词识别要覆盖意图而非字面**：宁可宽匹配多走元数据路径（RAG 兜底），也不要漏匹配让用户得到答非所问。
3. **结构化元数据给 LLM 当"事实上下文"**：比让 LLM 自己猜准确率高一两个数量级。
4. **confidence 分级**：元数据查询 = 1.0（事实），RAG 检索 = 0~0.5（相似度），无结果 = 0。前端可根据 confidence 区分"高置信直接展示" vs "低置信需提示"。

---

### 2.2 文档分类下拉框只显示「默认」

#### 故障表现

用户上传了大量「agent」相关资料，但「文档管理」页的分类下拉框中**只显示「默认」一项**。新增分类按钮虽然能建出新分类，但已有的「agent」分类无法选择。

#### 根因

`/api/categories/` 端点**只从 `ChunkingService.CATEGORY_CONFIGS` 字典读**：

```python
# 旧实现
@router.get("/")
async def get_categories():
    categories = []
    for name, config in ChunkingService.CATEGORY_CONFIGS.items():
        categories.append({...})
    return categories
```

而 `CATEGORY_CONFIGS` 来自 `data/categories.json`，**用户上传文档时即便指定了 `category="agent"`，这个分类也从未被回写到 `categories.json` 中**。所以 `CATEGORY_CONFIGS` 始终只有「默认」一项。

#### 修复

修改 [categories.py#L13-L41](file:///d:/code/个人开发项目/202605/知识库/backend/app/api/categories.py#L13-L41)，合并两个数据源：

```python
# 1. 已配置的分类（CATEGORY_CONFIGS 中的）
for name, config in ChunkingService.CATEGORY_CONFIGS.items():
    seen.add(name)
    categories.append({...})

# 2. 文档中实际存在但尚未配置的分类（自动推断）
for doc in _documents.values():
    cat = doc.category
    if cat and cat not in seen:
        seen.add(cat)
        categories.append({"name": cat, "strategy": "recursive", ...})  # 默认分块
```

#### 经验

- **单一数据源陷阱**：分类来源不只是配置，还有用户行为（上传/迁移）。**配置数据与业务数据要定期 reconcile**。
- **「下拉框只显示 N 个但用户用了 M 个」是一个高发 UX bug**，排查时优先查端点是否聚合了所有数据源。

---

### 2.3 FastAPI 路由顺序冲突导致端点静默失效

#### 故障表现

实现 `GET /api/documents/op-log` 端点后，调用方永远返回 `null`（4 字节字符串 `"null"`），**没有任何错误日志**，加 `print` 也不输出。

#### 根因

FastAPI 路由匹配是**按注册顺序**的（基于 Starlette 的 `Router.lifo=False` 实现）。本项目中：

```python
@router.get("/{doc_id}")                 # L219 — 通配符
async def get_document(doc_id: str): ...

@router.get("/op-log")                   # L436 — 字面路径
async def get_op_log(): ...
```

请求 `GET /api/documents/op-log`：

1. 路由表按注册顺序检查。
2. `/{doc_id}` 第一个被检查，**它能匹配**（`doc_id = "op-log"`），于是请求被路由到 `get_document()`。
3. `get_document()` 在 `_documents` 中找不到 id="op-log" 的文档，返回 `null`。
4. **`/op-log` 端点永远不会被调用**，静默失效。

#### 修复

**两步走**：

1. **路径改名为不与通配符冲突的语义化路径** `/migration-log`（含"-"的路径不易与 UUID 撞车）。
2. **在 `/{doc_id}` 路由之前注册 `/migration-log`**，确保字面路径优先匹配。

```python
# 在 /list 之后，/migration-log 必须在 /{doc_id} 之前
@router.get("/migration-log")
async def get_migration_log(limit: int = 50):
    return list(reversed(_OP_LOG[-limit:]))

@router.get("/list")    # 也在 /{doc_id} 之前
async def list_documents(...): ...

# 最后才是通配符
@router.get("/{doc_id}")
async def get_document(doc_id: str): ...
```

#### 经验

- **任何带 `/{param}` 通配符的路由文件，字面路由必须先注册**，这是 FastAPI 的硬性约束。
- **写完新端点必须用 OpenAPI 文档或 `print` 验证**：本案例中加 `print(f"[DEBUG] /op-log 命中")` 后发现 `print` 不输出，立刻定位到路由根本没被匹配。
- **推荐：用 Swagger 风格的 `api/v1/resource/{id}/sub-resource` 命名空间**（如 `/documents/{id}/chunks/{cid}`）替代扁平的 `/op-log` 等「魔法路径」。

---

### 2.4 相对路径在不同 CWD 下解析错误

#### 故障表现

后端启动时 `op_log.json` 总是新建在 `D:\code\个人开发项目\202605\知识库\data\op_log.json`（项目根），而不是预期的 `backend/data/op_log.json`。即便迁移请求成功返回，前端 GET 日志接口依然返回 `null`。

#### 根因

```python
# 旧代码
_OP_LOG_FILE = Path("data/op_log.json")
```

`Path("data/op_log.json")` 是**相对路径**，解析时基于**进程的当前工作目录（CWD）**：

| 启动方式 | CWD | 实际写入路径 |
| --- | --- | --- |
| `cd backend && uvicorn ...` | `backend/` | `backend/data/op_log.json` ✓ |
| `uvicorn main:app`（无 cd） | 项目根 | `<root>/data/op_log.json` ✗ |

`--reload` 模式下 WatchFiles 触发 reload 时，**CWD 可能被进程切换**，导致文件位置漂移。

#### 修复

**基于当前文件位置锚定绝对路径**：

```python
# __file__ = backend/app/api/documents.py
# parents[0] = backend/app/api
# parents[1] = backend/app
# parents[2] = backend
_OP_LOG_FILE = Path(__file__).resolve().parents[2] / "data" / "op_log.json"
```

这样无论从哪里启动、reload 多少次、是不是多进程，都指向同一个文件。

#### 经验

- **所有持久化文件路径必须基于 `__file__` 计算**（`Path(__file__).resolve().parents[N]`），永远不要写 `Path("data/...")`。
- **启动脚本要 `cd` 到预期的目录**：在 `start_server.py` / `package.json` 脚本里显式 `os.chdir(__file__)`，避免开发者各自启动时 CWD 不一致。

---

### 2.5 工作台折叠功能被错误地写到不存在的页面

#### 故障表现

工作台页面（`/`，渲染 `HomePage.tsx`）的「文档列表」**完全没有折叠功能**，11 篇文档全部展开，挤爆主界面。开发者反复确认「代码写了，逻辑也跑通了」，但用户在前端看不到任何变化。

#### 根因

折叠动画（`grid-template-rows` 0fr↔1fr 平滑过渡 + localStorage 持久化 + 展开/收起按钮）**完整地写到了 `DashboardPage.tsx` 中**（对应路由 `/dashboard`）。

但**项目里根本没有导航到 `/dashboard` 的入口**！用户实际使用的是 `/`（`HomePage.tsx`）。结果：

- 代码 100% 正确
- 单元测试能跑通
- 真实 UI 上**完全没体现**

#### 修复

**把功能从 `DashboardPage.tsx` 完整迁移到 `HomePage.tsx`**：

1. `localStorage` 折叠状态 key 保持一致（避免老用户状态丢失）
2. 折叠容器 / 触发按钮 / 动画时长完全复刻
3. 在迁移后**立刻用浏览器自动化测试（MCP Chrome DevTools）打开 `/` 路由 + 实际点击**验证，确认 UI 行为

#### 经验

- **写功能前先 grep 路由表 + 确认用户实际访问的页面**：在 React Router 项目里，多个组件可能都叫 "Page"，但只有挂载到实际路由的那个才生效。
- **完成代码 ≠ 完成功能**：必须在真实运行的 UI 上验证。这是 Karpathy 准则「Goal-Driven Execution」中强制的验收标准。
- **建立"功能落地清单"**：每写一个功能明确记录"它被用户看到的入口在哪里"。

---

### 2.6 前端 HMR 缓存与"代码写了不生效"陷阱

#### 故障表现

修改 `HomePage.tsx` / `ChatPage.tsx` 后保存文件，浏览器**没有变化**。开发者困惑："我代码改了为什么没生效？"

#### 根因

Vite 的 HMR（Hot Module Replacement）在以下情况会失效或卡死：

1. **文件保存触发多次 reload**，中间状态导致模块编译失败
2. **依赖循环 / 循环引用**导致 HMR 报"Failed to reload"
3. **浏览器缓存了旧版本**

#### 修复

- 在浏览器自动化测试中**强制忽略缓存**刷新：

  ```javascript
  mcp_chrome_navigate_page({ url: "http://localhost:5173/", ignoreCache: true })
  ```

- 在 `vite.config.ts` 中**禁用部分 HMR 优化**（当改动频繁且 HMR 出错时）：

  ```typescript
  server: { hmr: { overlay: true } }  // 出错时弹窗提示
  ```

- 关键修复后**清理 `.vite` 缓存目录**（`frontend/node_modules/.vite/deps_temp_*`）

#### 经验

- **"代码改了但 UI 没变"的首要排查动作 = 强制刷新 + 清除缓存**。
- **HMR 失败日志要看完整堆栈**：Vite 经常在控制台报"Failed to reload"但不说明根因，需要查看具体哪个模块的 `SyntaxError`。
- **关键流程用 Playwright / Puppeteer 验证**而不是人工点击，避免"我以为我点了但其实没"。

---

### 2.7 浏览器自动化测试触发 React 合成事件失败

#### 故障表现

用 Chrome DevTools MCP 工具通过 `evaluate_script` 设置 `<textarea>.value = "agent是什么？"` 后 dispatch `input` 事件，**React 的 onChange 回调没有被触发**。文本框的 React state 仍是空的，导致 `fill` + `click(发送)` 提交了空内容。

#### 根因

React 18 的合成事件系统对原生 `input` 事件的 `InputEvent.inputType` 等字段敏感：

- `dispatchEvent(new Event('input', {bubbles: true}))` 会被 React 识别为"非用户输入"，跳过 onChange
- 必须用 `InputEvent` + `inputType: 'insertText'` 才能模拟真实输入
- 即便如此，React 18 在某些状态下仍会忽略编程触发的输入

#### 修复

**优先用 Playwright-style 原生输入而非 React 编程触发**：

```javascript
// ✅ 推荐：使用 press_key + type_text（MCP 工具内置）
mcp_chrome_click({ uid: "textarea" })
mcp_chrome_press_key({ key: "/" })
// 注意：先发 / 触发 KbCategoryPicker，再 Backspace 清除
mcp_chrome_press_key({ key: "Backspace" })
mcp_chrome_type_text({ text: "agent是什么？", submitKey: "Enter" })
```

**或者在 evaluate_script 中强制走 React 内部**：

```javascript
const setter = Object.getOwnPropertyDescriptor(
  window.HTMLTextAreaElement.prototype, 'value'
).set
setter.call(textarea, 'agent是什么')
textarea.dispatchEvent(new InputEvent('input', { 
  bubbles: true, data: 'agent是什么', inputType: 'insertText' 
}))
```

#### 经验

- **浏览器自动化测试 React 组件时优先用真实键盘事件**，而不是 `dispatchEvent`。
- **MCP `press_key` + `type_text` 工具是最高保真的模拟方式**，会触发完整的 focus → keydown → input → keyup 流程。
- **测试结果以"UI 上能看到预期变化"为准**：state 改了 ≠ UI 渲染了。

---

## 3. 核心开发要点

### 3.1 RAG 中心化设计模式

**所有问答必须经过 `RAGChainService` 入口**（[rag_chain.py](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/rag_chain.py)）：

```
FastAPI 端点 (ai.py)
    ↓
RAGChainService.ask() / stream_ask()
    ↓
_is_meta_query() 早返回（本次新增）
    ↓
HybridRetriever.invoke()  内容检索
    ↓
LLMChainService.invoke() / stream()  LLM 调用
    ↓
返回 citations / confidence / answer
```

**优势**：

- 检索 / LLM 配置 / 过滤 / 兜底 / 日志 / 可观测性**集中在一个地方**
- 同步 (`/ask`) 与流式 (`/ask/stream`) 共享 95% 代码
- 业务端点（[ai.py](file:///d:/code/个人开发项目/202605/知识库/backend/app/api/ai.py)）只关心"传参 / 拿结果"，不必懂 RAG 内部

### 3.2 元数据 vs 内容的查询分流模型

```
query ─→ is_meta_query(q)?
              ├─ true  →  _collect_meta_snapshot()  → LLM 总结结构化数据 → conf=1.0
              └─ false →  HybridRetriever.invoke()  → RAG 检索         → conf=0~0.5
```

**判断维度**：

| 维度 | 元数据查询 | 内容查询 |
| --- | --- | --- |
| 期望答案位置 | `_documents` 元数据 / `categories.json` | 向量库中的文本块 |
| 答案是否确定 | 100% 确定 | 相似度匹配，可能答非所问 |
| confidence | 1.0 | top-1 分数（0~1） |
| LLM 角色 | 把结构化数据翻译成自然语言 | 基于检索片段做总结 / 推断 |
| 用户感受 | "系统准确知道库里有什么" | "系统能基于文档回答专业问题" |

### 3.3 SSE 流式进度的统一模式

**后端**（任务 2.2 [documents.py#L407-L494](file:///d:/code/个人开发项目/202605/知识库/backend/app/api/documents.py#L407-L494)）：

```python
@router.post("/migrate-batch-stream")
async def stream(payload: dict):
    def _gen():
        for i, item in enumerate(items):
            yield f"data: {json.dumps({'type': 'start', 'index': i, ...})}\n\n"
            try:
                result = process(item)
                yield f"data: {json.dumps({'type': 'done', 'ok': True, ...})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        yield f"data: {json.dumps({'type': 'summary', ...})}\n\n"
        yield "data: {\"type\":\"done\"}\n\n"
    return StreamingResponse(_gen(), media_type="text/event-stream")
```

**前端**（[DocumentsPage.tsx handleConfirmMigrate](file:///d:/code/个人开发项目/202605/知识库/frontend/src/pages/DocumentsPage.tsx)）：

```typescript
const reader = res.body.getReader()
const decoder = new TextDecoder('utf-8')
let buf = ''
while (true) {
  const { value, done } = await reader.read()
  if (done) break
  buf += decoder.decode(value, { stream: true })
  const events = buf.split('\n\n')   // SSE 事件以双换行分隔
  buf = events.pop() || ''
  for (const ev of events) {
    const json = ev.trim().slice(5)  // 去掉 "data:" 前缀
    const obj = JSON.parse(json)
    // 更新 progress state
  }
}
```

**关键点**：

- `buf.split('\n\n')` 处理跨 chunk 的事件边界（**必做**）
- 每个事件用 `\n\n` 终止（FastAPI 自动添加，客户端不要省略）
- `done` 事件要带 `ok: true` 区分成功，否则 `summary` 事件可能误判

### 3.4 路由设计原则（FastAPI）

| 原则 | 说明 |
| --- | --- |
| **字面路由在通配符之前** | `GET /list` 必须在 `GET /{doc_id}` 之前注册 |
| **避免单词型魔法路径** | 用 `/documents/migration-log` 而非 `/op-log`，与资源命名空间对齐 |
| **批量操作走 `POST /resource/action`** | `POST /documents/migrate-batch` 语义清晰 |
| **进度/长操作走 SSE** | 端点 `-stream` 后缀表示流式响应 |
| **CRUD 完整覆盖** | `list` / `get` / `create` / `update` / `delete` 五个端点起步 |

### 3.5 测试金字塔

```
            ┌─────────────────────────┐
            │   集成测试 (E2E)        │  ← MCP 浏览器自动化
            │   test_rag_e2e.py        │
            ├─────────────────────────┤
            │   端点集成测试            │  ← TestClient + httpx
            │   test_batch_migrate.py  │
            ├─────────────────────────┤
            │   单元测试               │  ← mock 外部依赖
            │   test_meta_query.py     │
            └─────────────────────────┘
```

**本项目测试现状**：

- 22 项单元 + 集成测试全通过
- 12 项元数据查询 + 10 项批量迁移
- 配合 `tsc --noEmit` 做前端类型校验

---

## 4. 同类项目开发建议清单

### 4.1 项目启动前

- [ ] **明确架构边界**：哪些是「内容检索」，哪些是「元数据查询」，哪些是「工具调用」，不要让 LLM 模糊地处理所有事
- [ ] **持久化路径用 `Path(__file__).resolve().parents[N]`** 写绝对路径
- [ ] **建立路由表文档**（即使是小项目），记录每个端点的注册顺序约束

### 4.2 开发过程中

- [ ] **每个新功能完成后立即在真实 UI 上验证一次**，不要等所有功能都写完才验收
- [ ] **RAG 阈值（0.3、0.5 等）不要硬编码到 prompt**，而是放在代码常量里 + 测试覆盖
- [ ] **任何"用户配置了 N 个但实际用了 M 个"的数据源**，端点必须 reconcile 所有源
- [ ] **新端点先 `print` 一行验证被命中**，再实现逻辑
- [ ] **SSE 端点写完必须做 buf 边界测试**（事件恰好跨 chunk）

### 4.3 排障时

- [ ] **「代码写了不生效」三板斧**：
  1. 强制刷新（ignoreCache）
  2. `print` 验证函数被调用
  3. 检查路由注册顺序 / HMR 错误日志
- [ ] **「API 返回 null 但端点存在」→ 99% 是路由顺序问题**（被 `/{param}` 拦截）
- [ ] **「文件路径找不到」→ 99% 是相对路径 / CWD 问题**（用 `Path(__file__)` 锁定）
- [ ] **「LLM 答非所问」→ 检查是元数据查询被混入内容检索**，还是 prompt 指令不清晰

### 4.4 测试覆盖

- [ ] **RAG 类系统必须有「内容查询」+「元数据查询」两类单元测试**
- [ ] **SSE 类端点必须有「单事件」「跨 chunk」「失败事件」三组测试**
- [ ] **路径类操作必须有「绝对路径」「跨平台」两组测试**
- [ ] **测试夹具与生产数据隔离**（用 `__test_xxx__` 命名空间）

### 4.5 文档与复盘

- [ ] **每个修复节点写成"故障现象 → 根因 → 方案 → 验证"四段式**，便于后人追溯
- [ ] **记录「多轮修复未解决」的失败过程**比只记录最终成功更有价值（避免重蹈覆辙）
- [ ] **本复盘文档每完成一个里程碑更新一次**，保持鲜活

---

## 6. 第二轮修复记录（2026-06-15 ~ 2026-06-16）

> 本章记录第二轮全链路 RAG 质量提升的 6 个核心修复，按时间顺序 / 排查链排列。

### 6.1 ⭐⭐⭐ 19 篇文档只索引 33 chunks（启动同步 bug）

**故障现象**：

知识库实际上传 19 篇文档，分块服务测试也正常（能切出 534 块），但前端「向量分块」页只显示 **33 个分块，仅覆盖 1 篇文档和 1 个分类**。RAG 检索效果极差，AI 大量幻觉 / 返回「未找到」。

**根因链**：

| 层 | 检查项 | 结果 |
|---|---|---|
| 文档存储 | `data/documents.json` | ✅ 19 篇 |
| 文档服务 | `_documents` 内存 | ✅ 19 篇 |
| 分块服务 | `ChunkingService.chunk()` | ✅ 19 篇 → 534 块 |
| 向量库文件 | `data/vector_store.json` | ❌ **只有 33 块 / 1 篇** |
| 启动钩子 | `main.py` 的 `startup_event` | ❌ **不重建** |

**根因（核心 bug）**：

[main.py](file:///d:/code/个人开发项目/202605/知识库/backend/main.py) 启动时的同步逻辑：

```python
# 旧逻辑（错误）
if existing_chunks == 0:
    trigger_full_reindex()   # 只有空库才重建
```

这意味着：**只要 `vector_store.json` 不为空，跳过全部重建**。第一次重建时只有 1 篇文档被处理并写入了 33 个 chunks，之后 18 篇新文档上传后启动就直接跳过 → 永远只索引那 33 块。

**修复（增量重建）**：

```python
# 新逻辑（修复后）
total_docs_in_db = len(_documents)
covered_docs = VectorStore.get_stats().get("covered_docs", 0)
missing_docs = total_docs_in_db - covered_docs
need_reindex = (
    (total_docs_in_db > 0 and existing_chunks == 0)  # 空库 → 全量
    or (missing_docs > 0)                             # 任一缺失 → 增量
)
if need_reindex:
    trigger_incremental_reindex(missing_only=True)
```

修复后实测：19 篇文档全部覆盖，**534 个分块**，启动日志清晰列出每个文档的处理结果。

**经验**：

> **同步逻辑必须以"实际覆盖情况"为依据，而不是"是否首次"**。判断 `existing_chunks == 0` 这种"首次标志"型条件，几乎一定会导致后续新增数据丢失。

---

### 6.2 ⭐⭐⭐ Pydantic ModelPrivateAttr 异常导致 query 改写失败

**故障现象**：智能问答偶发日志中出现 `'ModelPrivateAttr' object has no attribute 'items'`，导致部分查询（如「RAG 是什么」）改写失败，命中错误的检索分支。

**根因**：

LangChain 的 `BaseRetriever` 基于 Pydantic v2，**类属性字典会被识别为 `ModelPrivateAttr`**。

```python
class HybridRetriever(BaseRetriever):
    _QUERY_SYNONYMS = {  # ❌ 错：类属性 dict 被当作私有属性
        "RAG": ["检索增强生成", "Retrieval-Augmented Generation"],
    }
```

**修复**：把 `_QUERY_SYNONYMS` 移到**模块级常量**（不是类属性）：

```python
# ✅ 模块级 dict（修复后）
_QUERY_SYNONYMS = {
    "RAG": ["检索增强生成", "Retrieval-Augmented Generation"],
    ...
}

class HybridRetriever(BaseRetriever):
    # 类内部通过 _QUERY_SYNONYMS 直接引用模块级变量
    pass
```

**经验**：

> 在 LangChain 中继承 `BaseRetriever` / `BaseChatModel` 等 Pydantic 模型时，**禁止在类内部用 `_*` 命名 dict/list 属性**，会被识别为 ModelPrivateAttr。统一提到模块级。

---

### 6.3 ⭐⭐ 同义词扩展污染长 query 导致 RAG 检索失败

**故障现象**：

```
Q: "RAG 的核心流程是什么?"
```

实际 RAG 检索的 query 被改写为：

```
RAG 的核心流程是什么? | 检索增强生成 | Retrieval-Augmented Generation | RAG 技术
```

embedding 编码后检索 top-k，结果是 LangChain/LangGraph 等无关文档，LLM 据此输出"知识库中暂未找到"。

**根因**：

[memory_chain.py:FollowUpDetector.expand_with_synonyms](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/memory_chain.py) 对"包含词典关键词的复合 query"也做扩展，用 `|` 拼接。

embedding 模型对拼接 query 的处理：**同义词和原 query 共享向量空间**，但同义词占比太高时，原始 query 的语义被稀释。

**修复**：严格化扩展条件——**只在 query 极短（≤ 10 字符）且完全命中词典 key 时扩展**，其他情况一律不扩展。

```python
@classmethod
def expand_with_synonyms(cls, query: str) -> str:
    q_stripped = query.strip()
    if not q_stripped:
        return query
    # 只在 query 极短（≤ 10 字符）且完全命中词典 key 时扩展
    if len(q_stripped) <= 10 and q_stripped in cls._QUERY_SYNONYMS:
        synonyms = cls._QUERY_SYNONYMS[q_stripped]
        return f"{q_stripped} | {' | '.join(synonyms)}"
    return query  # 其他情况不扩展
```

**修复后实测**：
- "RAG 的核心流程是什么?" → 不再扩展 → 3 citations 用户文档 ✅
- "介绍一下 LangChain" → 不再扩展 → kb_content 路径 ✅

**经验**：

> 同义词扩展只对**纯短查询（≤ 10 字符）**有意义。对复合 query 做扩展会严重污染 embedding 语义。

---

### 6.4 ⭐⭐ system_faq 误判：技术名词被当作系统介绍

**故障现象**：

提问「介绍一下 LangChain」「Agent 是什么」这类**技术名词查询**，被错误路由到 system_faq 路径，使用内置 FAQ 文档（`__kb_overview__` / `__kb_resources__`）回答，与用户上传的实际文档完全脱钩。

**根因**：

[intent_classifier.py](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/intent_classifier.py) 的 SYSTEM_FAQ_RULES 包含过于宽松的 pattern：

```python
r"介绍一下",  # ❌ 任何 "介绍一下 X" 都会被识别为 system_faq
```

**修复**：双层修复

1. 严格化 `r"介绍一下"` 为 `r"^介绍一下\s*(本|这个|该|当前|我的)?\s*(知识库|系统|平台|工具|应用|软件|产品)?\s*[?？。!！]?$"`，必须后接系统/平台/知识库类词才算 system_faq。
2. 在 system_faq 之前加入 META_QUERY override patterns，让"介绍一下本知识库/我的知识库/知识库有什么"走 meta_query。

**经验**：

> **意图分类的正则必须以"歧义边界"为粒度设计**。"介绍一下 + 任意内容"明显有歧义，必须分别处理：技术名词走 kb_content，知识库类元词走 meta_query，系统功能问句走 system_faq。

---

### 6.5 ⭐⭐ `<think>` 剥离把整个 answer 砍空

**故障现象**：

部分 LLM 流式输出在流中断时只输出 `<think>` 而没有 `</think>` 闭合标签，前端的 `_strip_think_blocks` 把整个 answer 砍到 0 字符。

**根因**：

[ai.py:_strip_think_blocks](file:///d:/code/个人开发项目/202605/知识库/backend/app/api/ai.py) 第 2 步逻辑：

```python
open_idx = re.search(r'<\s*think\s*>', cleaned, re.IGNORECASE)
if open_idx:
    cleaned = cleaned[:open_idx.start()].strip()  # ❌ 截到 <think> 之前
```

如果 LLM 输出只有 `<think>` 而没有 `</think>`（流被截断），`open_idx.start() = 0`，整个 answer 被截到 0。

**修复**：

```python
# 只有同时具备 <think> 和 </think> 时才剥离
if has_open and has_close:
    cleaned = _THINK_BLOCK_RE.sub('', answer).strip()
    ...
return answer.strip()  # 否则保留原文，避免误删
```

**经验**：

> 流式 LLM 输出可能被截断，**任何"防御性截断"逻辑必须先判断完整性**。宁可保留完整 answer 也不要粗暴截断。

---

### 6.6 ⭐⭐ ChatPage 引用块提前显示（先引用后回答）

**故障现象**：

用户提问后，前端 ChatPage 页面渲染顺序异常：
1. **空白消息条**（content 还没回来）
2. **引用来源卡片**（metadata 已先到，含 citations）
3. **正式回答**（流式 token 累积）

**根因**：

[ChatPage.tsx:convertToRichContents](file:///d:/code/个人开发项目/202605/知识库/frontend/src/pages/ChatPage.tsx) 在生成 contents 时**无条件添加 citation block**：

```tsx
if (msg.citations && msg.citations.length > 0) {
  contents.push({ type: 'citation', content: msg.citations })
}
```

后端 `/api/ai/ask/async` 的处理顺序：
1. metadata 事件 → `mgr.update(citations=..., confidence=...)`
2. text 事件 → `mgr.append_text(...)` 累积流式 token
3. done 事件

所以前端第一次轮询就拿到 `citations=[]`，但 `text=""`。引用卡立刻渲染，正文还是空白 → 用户看到"先引用后回答"。

**修复**：

```tsx
if (msg.citations && msg.citations.length > 0) {
  // 仅在打字机效果完成时才追加 citation block
  if (!isTyping) {
    contents.push({ type: 'citation', content: msg.citations })
  }
}
```

`isTyping = displayedLengths[msg.id] < msg.content.length` —— 流式打字机跑完才显示引用卡。

**同时修复**：

[AIChat.tsx](file:///d:/code/个人开发项目/202605/知识库/frontend/src/components/AIChat.tsx) 的引用块条件增加 `displayChars >= msg.content.length || taskStatus === 'done'` 双重保险。

**新增 `TypingIndicator` 组件**：三点跳动动画 + 阶段文字轮换（思考中 → 检索知识库 → 正在生成回答），替代简陋的"● 思考中..."占位符。

**经验**：

> 流式 SSE / 异步任务中，**前端必须根据"完整数据"渲染，不能根据"中间状态"渲染**。引用块、统计数字、置信度等"辅助信息"必须等到主内容完整后再生效。

---

### 6.7 ⭐ 任务 Z「未找到 marker」误清空 citations

**故障现象**：

LLM 偶尔输出"在 RAG 中，如果没有找到相关资料..."这种**说明性表述**（含"没有找到"），触发后端"任务 Z"逻辑把 citations 全部清空。

**根因**：

[rag_chain.py:1035-1062](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/rag_chain.py) 的"任务 Z"：

```python
not_found_markers = ["未找到", "没有找到", ...]
if any(marker in answer_text for marker in not_found_markers):
    citations = []
    confidence = 0.0
    # 同时截断 answer 到 marker 位置
```

**修复方向**：

- 将 marker 检测从 `answer_text in marker` 改为**更严格的"独立段落"模式**（要求 marker 出现在句首/句末标点后）
- 对 KB_CONTENT_QUERY 路径禁用强制清空（只对真正无引用的 meta_query / 引用缺失场景清空）

**经验**：

> "未找到"是 LLM 高频用词，不能简单 substring 匹配。需要更严格的语义判断（如：长度 < 100 字符、只含单句、且不含引用标号）。

---

### 6.8 ⭐ Embedding 实际加载模型与日志不符

**故障现象**：

`.env` 配置 `EMBEDDING_MODEL_NAME=Qwen/Qwen3-Embedding-0.6B`，但启动日志显示：

```
[Embedding] BGE 加载成功 (transformers, cpu, dim=512)
```

让运维误以为加载的是 BGE。

**根因**：

[embedding.py](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/embedding.py) 中加载成功的日志硬编码为 "BGE 加载成功"，与实际模型路径无关。

**修复**：日志改为按实际 model path 输出：

```python
model_basename = os.path.basename(model_path.rstrip("/\\"))
print(f"[Embedding] 加载成功 (transformers, {self._device}, dim={self._dim}, model={model_basename})")
```

启动后输出：

```
[Embedding] 加载成功 (transformers, cpu, dim=1024, model=Qwen_Qwen3-Embedding-0.6B)
```

**经验**：

> **日志消息不能与代码状态脱钩**。硬编码的"BGE 加载成功"在换了模型后成为误导性信息，所有日志必须基于动态状态。

---

## 7. 同类项目 RAG 质量优化清单（v2）

> 在 §4 基础上，针对 RAG 全链路的 6 个核心环节补充检查项。

| 环节 | 检查项 | 验证方法 |
| --- | --- | --- |
| 文档上传 | 上传后立刻拉取 documents.json 确认存储 | `GET /api/documents/list` |
| 分块服务 | 单元测试覆盖所有分块策略，对比 chunk 数量 | `pytest test_chunking.py` |
| 向量化 | 启动日志确认**实际加载的模型名 + 维度** | 检查 `[Embedding] 加载成功 (..., model=...)` |
| 向量库覆盖 | 启动时比对 `_documents` 数 vs `vector_store.get_stats()["covered_docs"]` | 增量重建 |
| 意图分类 | 准备 20+ 测试 query 覆盖每种意图边界 | `pytest test_intent_classifier.py` |
| 同义词扩展 | 严格化扩展条件，避免污染长 query | 单元测试短查询 vs 长查询行为差异 |
| 检索结果 | 检查 top-k 标题是否来自用户文档（非内置 FAQ） | API 层强制过滤 `__kb_*` |
| 引用规范 | `citations` 列表必须与 LLM 输出的引用标号数量一致 | `_align_citations` 后核对 |
| 渲染顺序 | 流式过程中不渲染引用卡 / 置信度 | `isTyping` 状态判断 |
| <think> 剥离 | 必须**同时**具备 `<think>` 和 `</think>` 才剥离 | 双标志检查 |

---

## 5. 复盘元数据

| 项 | 值 |
| --- | --- |
| 复盘负责人 | Claude (with user guidance) |
| 复盘周期 | 2026-06-08 ~ 2026-06-16 |
| 涉及文件 | `rag_chain.py` / `documents.py` / `categories.py` / `vector_store.py` / `intent_classifier.py` / `memory_chain.py` / `embedding.py` / `query_cache.py` / `main.py` / `ai.py` / `AIChat.tsx` / `ChatPage.tsx` / `RichContentRenderer.tsx` |
| 测试通过率 | 22/22 单元 + 集成测试（pytest） · 0 TS 错误 |
| 本轮核心修复 | 增量重建索引 + Qwen3 Embedding + Pydantic 修复 + 同义词严格化 + system_faq override + think 块安全剥离 + 渲染顺序优化 |

### 修订历史

| 版本 | 日期 | 修订内容 |
| --- | --- | --- |
| v1.0 | 2026-06-12 | 初版：建立完整复盘框架；收录 7 个典型排障案例；提炼 4 大核心开发要点；输出 5 维度同类项目建议清单 |
| v2.0 | 2026-06-16 | 追加 §6 八个典型排障案例（启动同步 / Pydantic / 同义词 / 意图分类 / 思考块 / 渲染顺序 / 任务 Z / 日志误导）；新增 §7 RAG 质量优化 v2 清单 |
| v3.0 | 2026-06-18 | 新增 §8 四个核心修复（Chroma+Qwen3 双原则 / encoding_format 静默 fallback / Chroma 路径不一致 / API 化零依赖价值）；3.55 GB 释放；score 0.328 → 0.768 |

---

## 8. 第三轮修复记录（2026-06-18） — Qwen3 ModelScope API 接入

> 本章记录第三轮 RAG 质量提升 + Embedding 架构升级的 4 个核心修复。**核心目标**：让 Chroma 真正用上 Qwen3-Embedding-0.6B（1024 维），并彻底告别本地模型加载的兼容性问题。

### 8.1 ⭐⭐⭐ P0 原则确立：必须用 Chroma + 必须用 Qwen3

**项目两大不可妥协原则**：

1. **必须用 Chroma**（不能回退到自研 JSON VectorStore）
2. **必须用 Qwen3-Embedding-0.6B**（不能用 BGE、不能用 hash 兜底）

围绕这两条原则，本轮经历了三轮失败的尝试 + 一次成功的方案。

#### 失败路径回顾

| 尝试 | 方案 | 失败根因 |
|------|------|---------|
| **尝试 1：本地直加载 Qwen3** | 用 `transformers.AutoModel.from_pretrained()` 加载 1.2 GB 本地权重 | `huggingface_hub 0.19.4` 移除了 `is_offline_mode` 等 API；`transformers` 旧版本仍引用导致 `ImportError` |
| **尝试 2：升级 transformers / huggingface_hub** | `pip install --upgrade` | 清华源没有 `huggingface_hub >= 1.3.0`；pip 切到 PyPI 官方源后：`transformers 5.12 + torch 2.10` ABI 冲突（`CPU dispatcher tracer already initlized`） |
| **尝试 3：降级 torch 到 2.1.0** | 解决 ABI 冲突 | wheel 192 MB 下载极慢（清华源 → 官方源），耗时过长放弃 |
| **尝试 4：✅ 走 ModelScope API** | 调用 `https://api-inference.modelscope.cn/v1/embeddings` | **完美**：0 本地依赖、0 兼容性、1024 维真实 Qwen3 |

**关键洞察**：

> **不要被「本地加载」束缚**。LLM 时代所有主流模型都有 OpenAI 兼容的 API 服务（ModelScope、SiliconFlow、Together、Replicate 等），**走 API 等于走「云端推理 + 本地零成本」**。本项目早已预留 `EMBEDDING_PROVIDER=modelscope` 配置 + `_HF_STUBS` 兼容性补丁 + `EMBEDDING_MODEL_OVERRIDE` 覆盖机制——**架构层面早就为 API 模式做好了准备，只是没人用**。

#### 成功方案（最终架构）

```python
# .env
EMBEDDING_MODE=api                      # 关键：切到 API 模式
EMBEDDING_PROVIDER=modelscope           # 魔塔社区
EMBEDDING_MODEL_OVERRIDE=Qwen/Qwen3-Embedding-0.6B
MODELSCOPE_API_KEY=ms-779e184f-...     # 用户在魔塔申请
```

**优势**：

- **0 本地模型文件**（释放 3.45 GB：`models/BAAI_bge-small-zh-v1.5` 92 MB + `Qwen_Qwen3-Embedding-0.6B` 2.3 GB + `models--Qwen--Qwen3-Embedding-0.6B` 1.15 GB + `.locks`）
- **0 PyTorch/transformers 依赖冲突**（不再 import 任何本地模型）
- **0 启动时 OpenBLAS 内存分配失败**（之前 1.2 GB 内存占用 + numpy 多线程下经常崩）
- **真实 1024 维 Qwen3 嵌入**（之前 hash_fallback 512 维 → 真正 Qwen3 1024 维）

**业务影响**：

| 指标 | 之前 hash_fallback | 现在真 Qwen3 |
|------|-------------------|-------------|
| 检索 top-1 score | 0.328 | **0.768** ⬆️ 2.3 倍 |
| 检索 top-3 命中 | 3 条 LLM 框架相关 | **同 3 条，置信度更高** |
| 22 文档 reindex 耗时 | 7.2 秒（hash 极快） | 19.6 秒（首次含 API 网络） / 7.2 秒（hash 假象）|
| 22 文档重 reindex（API 真用上） | — | **66.47 秒**（22 文档 × 多次 API 调用）|

**经验**：

> **「必须用 X」不一定意味着「必须本地跑 X」**。API 化是 2024+ 的标准答案，本地化只在数据隐私极端敏感时才有意义。架构设计要预留 provider 抽象（`EMBEDDING_PROVIDER`），业务调用方只关心「拿到 embedding」。

---

### 8.2 ⭐⭐⭐ ModelScope API 强制要求 `encoding_format` 但项目代码未传（**静默 fallback**）

**故障现象**：

切换到 ModelScope API 后，reindex 显示 **22 文档 601 chunks 全部成功**，但搜索 `langchain 框架` 时：

- **之前 hash_fallback score 0.328**
- **现在 Qwen3 应该 0.7+**
- **实际只返回 0.4268**，且只匹配到 `system_faq` 的"知识库使用方式"

> **看 score 不升反降，怀疑 Qwen3 仍然没真用上**。

**根因链**：

| 层 | 检查项 | 结果 |
|---|---|---|
| `.env` | `EMBEDDING_MODE=api` | ✅ |
| `start_server.log` | `API 模式 \| provider=魔塔社区 (ModelScope)` | ✅ |
| reindex 输出 | `{"status":"ok", "success_docs": 22, "total_chunks": 601}` | ✅ 看似成功 |
| **API 真实响应** | **直接调 `requests.post(embeddings)` 看 raw response** | ❌ `{'errors': {'message': "encoding_format must be 'float' or 'base64', got ''"}, ...}` |
| **项目代码路径** | [embedding.py#_call_openai](file:///d:/code/%E4%B8%AA%E4%BA%BA%E5%BC%80%E5%8F%91%E9%A1%B9%E7%9B%AE/202605/%E7%9F%A5%E8%AF%86%E5%BA%93/backend/app/core/embedding.py#L390-L404) | ❌ `embeddings.create(model=..., input=...)` 没传 `encoding_format` |
| **fallback 触发** | API 抛异常 → `_handle_error` → `return [LocalEmbedding._hash_embed(t, 1024) for t in texts]` | ❌ **静默降级到 hash_fallback** |

**为什么 22 文档"成功"？**

**项目代码的 fallback 太"温柔"**：

```python
# embedding.py:390-404 (修复前)
try:
    response = self._client.embeddings.create(model=self.model, input=texts)
    return [d.embedding for d in response.data]
except Exception as e:
    self._handle_error(e, "OpenAI 协议")
    return [LocalEmbedding._hash_embed(t, self._expected_dim) for t in texts]
```

`_handle_error` 只 print 一行 warning，**然后 fallback 到 hash 伪向量**。reindex 看到 `total_chunks: 601` 就以为成功——**完全不知道底层用了 hash**。

**修复**（[embedding.py#L390-L404](file:///d:/code/%E4%B8%AA%E4%BA%BA%E5%BC%80%E5%8F%91%E9%A1%B9%E7%9B%AE/202605/%E7%9F%A5%E8%AF%86%E5%BA%93/backend/app/core/embedding.py#L390-L404)）：

```python
# 修复后
try:
    # 任务 P0: ModelScope API 强制要求 encoding_format（'float' 或 'base64'）
    # OpenAI 官方也接受，所以统一传
    response = self._client.embeddings.create(
        model=self.model, input=texts, encoding_format="float"
    )
    return [d.embedding for d in response.data]
except Exception as e:
    self._handle_error(e, "OpenAI 协议")
    return [LocalEmbedding._hash_embed(t, self._expected_dim) for t in texts]
```

**验证**（修复后真实 reindex 耗时）：

| 阶段 | 耗时 | 数据维度 |
|------|------|---------|
| 之前 hash_fallback（reindex 假成功） | **7.2 秒** | 512 维 hash |
| 修复 encoding_format 后真 Qwen3 | **66.47 秒** | **1024 维 Qwen3** |

> **耗时 9 倍 = 真模型在跑**。如果走 hash 不会超过 10 秒；66 秒是 22 文档 × 30 chunks × 多次 API 调用的真实成本。

**修复后 score 实测**：

```
query: 'langchain 框架'
1. 04_LLM框架实战_中级.pdf       score=0.768
2. 03LLM框架实战_基础.pdf        score=0.7667
3. 10_LLM框架实战_Agent实战.pdf  score=0.7617
```

**经验**：

> **任何"AI 服务调用 + 兜底实现"的组合都是 P0 风险**。项目必须：
> 1. **外部 API 失败时主动报错**而非静默 fallback（用 `EMBEDDING_FALLBACK=error` 环境变量切换）
> 2. **记录实际调用耗时**到 metrics（hash_fallback 永远 < 10 秒，Qwen3 真模型 > 30 秒，**耗时本身就是维度正确性的探针**）
> 3. **reindex 完成后用一条已知 query 检索 + 验证 score 范围**（hash_fallback score 通常 < 0.4，真 Qwen3 > 0.5）

---

### 8.3 ⭐⭐ Chroma 持久化路径与代码常量不一致（用了未生效的 `chroma_db_v2`）

**故障现象**：

PITFALLS §2.1 修复中提到 "Chroma 切换路径" 之后，项目实际是**两个 Chroma 目录并存**：

- `backend/data/chroma/`（6.6 MB，**实际被代码使用**）
- `backend/data/chroma_db_v2/`（被多次"重建"但**不被任何代码引用**）

我曾花费半小时在 `chroma_db_v2` 上做 reindex、清空、再 reindex——**但搜索时实际读写的是 `chroma/`**，所有 `chroma_db_v2` 的工作完全是无用功。

**根因**：

[vector_store.py#L34](file:///d:/code/%E4%B8%AA%E4%BA%BA%E5%BC%80%E5%8F%91%E9%A1%B9%E7%9B%AE/202605/%E7%9F%A5%E8%AF%86%E5%BA%93/backend/app/core/vector_store.py#L34)：

```python
# 旧实现
CHROMA_PERSIST_DIR = DATA_DIR / "chroma"
```

代码常量写死为 `chroma`，但项目其他地方（包括我之前的修复）都基于 `chroma_db_v2` 操作。**改路径是改一处，但代码其他地方都按旧路径找数据**。

**修复**：

```python
# vector_store.py#L34 (修复后)
# 任务 P0: 切换到 chroma_db_v2 目录（旧的 chroma/ 目录因 Windows mmap 锁无法删除，
# 但 chroma_db_v2/ 可以安全删除和重建）。这样能确保用 Qwen3-Embedding-0.6B 1024 维重建。
CHROMA_PERSIST_DIR = DATA_DIR / "chroma_db_v2"
```

**踩坑点**：

`backend/data/chroma/chroma.sqlite3` **因 Windows mmap 文件锁无法删除**（`PermissionError: [WinError 32] 另一个程序正在使用此文件`）——是 chromadb 0.5.20 的已知问题，mmap 句柄不释放，必须**重启 Windows** 才能彻底解锁。

**经验**：

> **重构"数据目录"时一定要先验证"是否所有读写都走新路径"**：
> 1. `grep -rn "chroma/" --include="*.py"` 全文搜索
> 2. `grep -rn "CHROMA_PERSIST_DIR" --include="*.py"` 看所有引用点
> 3. 启动日志确认 `[Chroma] 初始化完成 | dir=...` 中 `dir=` 是预期路径
>
> **否则会出现"代码以为在做 A，实际在做 B"的诡异 bug**。

---

### 8.4 ⭐⭐⭐ API 模式删除本地模型后的"零依赖"架构价值

**故障现象**：

切换到 ModelScope API 之后，**项目里所有本地 Embedding 模型都可以删了**——3.45 GB 磁盘、1.2 GB 运行时内存、PyTorch + transformers + numpy ABI 兼容性问题**全部归零**。

**清理清单**：

| 删除项 | 释放 | 备注 |
|--------|------|------|
| `backend/models/BAAI_bge-small-zh-v1.5/` | 92 MB | BGE 512 维兜底模型 |
| `backend/models/Qwen_Qwen3-Embedding-0.6B/` | 2.3 GB | 之前手动下载的 Qwen3 本地副本 |
| `backend/models/models--Qwen--Qwen3-Embedding-0.6B/` | 1.15 GB | `huggingface_hub` 自动缓存 |
| `backend/models/.locks/` | 0 KB | 锁文件 |
| `backend/data/vector_store.json` | 23 MB | Chroma 之前的兜底实现（已迁完） |
| `backend/data/vector_store.json.migrated.bak` | 5.8 MB | 迁移备份 |
| `backend/diag.log` | — | 调试日志 |
| **合计** | **~3.55 GB** | |

**清理后 `backend/` 顶层结构**：

```
backend/
├── app/              # 业务代码（未变）
├── data/
│   ├── chroma_db_v2/  # Chroma 持久化（Qwen3 1024 维真数据）
│   ├── graph/         # 知识图谱
│   ├── knowledge/     # 知识库配置
│   ├── uploads/       # 上传的原文件
│   └── *.json + *.log # 业务数据 + 日志
├── __pycache__/       # Python 运行时缓存
├── .env               # 环境配置（含 ModelScope API key）
├── .env.example       # 配置模板
├── main.py
├── requirements.txt
└── start_server.py
```

**注意**：

- `backend/models/` **整个目录** 已删除（不再需要）
- `LocalEmbedding` 类仍在代码中作为兜底（`EMBEDDING_FALLBACK=hash` 时启用），但**永远不会**被实例化（因为 `EMBEDDING_MODE=api`）

**项目配置演化**：

| 模式 | 配置 | 模型来源 | 维度 | 依赖 |
|------|------|---------|------|------|
| 之前 (local) | `EMBEDDING_MODE=local` | 本地 1.2 GB Qwen3 | 1024 维（真模型） / 512 维（hash 假象）| torch 2.10 + transformers 5.12 + numpy 2.1 |
| 之前 (local + BGE) | `EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5` | 本地 92 MB BGE | 512 维 | 同上 |
| **现在 (api)** | `EMBEDDING_MODE=api` + `EMBEDDING_PROVIDER=modelscope` | **ModelScope 云端** | **1024 维** | **0**（只依赖 `openai` Python 包） |

**最终 RAG 检索质量**：

```
query: 'langchain 框架'
1. 04_LLM框架实战_中级.pdf       score=0.7680  ← 真 Qwen3
2. 03LLM框架实战_基础.pdf        score=0.7667  ← 真 Qwen3
3. 10_LLM框架实战_Agent实战.pdf  score=0.7617  ← 真 Qwen3
```

**经验**：

> **API 化是 LLM 时代的"最佳实践"**：
> 1. 避免模型权重分发（合规 + 版权 + 体积）
> 2. 避免本地推理框架兼容（PyTorch / transformers / numpy ABI 地狱）
> 3. 升级 / 切换模型不影响代码（改 `EMBEDDING_MODEL_OVERRIDE` 即可）
> 4. 多个端点（siliconflow、together、replicate）可平替（用 `EMBEDDING_PROVIDER` 切换）
>
> **唯一代价**：必须联网。但对 RAG 类应用，**没有"离线用 RAG"的真实需求**（生产环境 RAG 永远在服务器上跑，不可能要求用户下载 1.2 GB 模型）。

---

> **本复盘文档的使命**：让下一个接手此项目（或同类项目）的开发者，**少走我们走过的弯路**。

---



---

## 9. 第四轮修复记录（2026-06-19）— Embedding 切换 / 登录删除 / 端口冲突

### 9.1 ⭐ 端口冲突：conda 环境的幽灵 worker 抢占 8000

#### 故障表现

修改后端端口为 8000 后，浏览器访问 `http://localhost:5173` 仍然空白，Vite 转发请求到后端时拿到**未预期响应**；后端 8000 端口的服务能正常启动并响应 200，但浏览器侧始终拿不到数据。

#### 根因

```powershell
PS> netstat -ano | findstr :8000
  TCP    0.0.0.0:8000           LISTENING       27692  # 我们的后端
  TCP    127.0.0.1:8000         LISTENING       3636   # 幽灵
```

8000 端口同时被两个 listener 占据：

| PID | 绑定地址 | 进程 |
|-----|---------|------|
| 27692 | 0.0.0.0:8000 | 我们的 uvicorn |
| 3636 | 127.0.0.1:8000 | Trae IDE 内置 conda `knowledge` 环境的 worker |

**Windows 路由规则**：当浏览器访问 `localhost:8000`（解析为 `127.0.0.1`）时，**优先匹配具体绑定 `127.0.0.1`**，于是请求被 PID 3636 那个不知名的 worker 抢走。

**嵌套问题**：PID 3636 又是 Trae 进程（PID 32216）通过 `multiprocessing.spawn` 派生的子进程。**杀掉后会自动重启**（Trae 看门狗机制），每隔一段时间就会回来。

#### 复现验证

```powershell
PS> Get-CimInstance Win32_Process -Filter "ProcessId=3636" | Select-Object CommandLine
CommandLine : "D:\Anaconda\Anaconda\envs\knowledge\python.exe" -c "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=35108, pipe_handle=524)" --multiprocessing-fork
```

#### 修复

1. 杀掉 worker + 父进程（一次性，**有时会自动重启**）：
   ```powershell
   taskkill /F /PID 3636 /T
   taskkill /F /PID 35108 /T
   ```
2. 在 `.env` 中显式锁定 8001 作为 fallback：
   ```ini
   PORT=8001
   ```
3. 接受临时方案：**让 conda worker 监听 127.0.0.1:8000，我们的 uvicorn 绑定 0.0.0.0:8001**，让两套共存。

#### 经验

- **Windows 端口可被 0.0.0.0 + 127.0.0.1 同时绑定**，与 Linux 的 `Address already in use` 不同。
- **开发机如有 Trae / VSCode 集成的 Python 进程**，会通过 `multiprocessing.spawn` 后台跑服务，需定期 `netstat` 排查。
- **生产部署务必 Linux**（干净环境，端口冲突机制明确）。

---

### 9.2 ⭐ Layout.tsx 残留 UserMenu 引用导致整页白屏

#### 故障表现

执行「删除登录功能」后，浏览器打开前端整页空白。控制台：

```
Uncaught ReferenceError: UserMenu is not defined
  at Layout (http://localhost:5173/src/components/Layout.tsx:44:41)
```

#### 根因

清理 `UserMenu.tsx` 文件后，**`Layout.tsx` 中第 181 行仍然有 `<UserMenu />` JSX**。React 在 `Layout` 组件首次渲染时执行到该标签，因 `UserMenu` 未导入而抛出 `ReferenceError`，整个组件树挂掉 → 整页白屏。

**原因追溯**：清理过程中用了 3 个 Edit 步骤，**第一个 Edit 的 `old_string` 没有完全匹配实际文件内容**（可能因为换行符或缩进差异），导致只删除了 `import` 语句，**未删除 JSX 使用处**。

#### 修复

1. 全局检索所有 `UserMenu` 引用：
   ```bash
   grep -r "UserMenu" frontend/src
   ```
2. 定位到 [Layout.tsx#L181](file:///d:/code/个人开发项目/202605/知识库/frontend/src/components/Layout.tsx#L181) 的 `<UserMenu />` 残留。
3. 删除该 JSX，保留外层 `div` 容器。
4. **重启服务确认无残留**（HMR 有时不报删错组件）。

#### 经验

- **删除组件必须三步走**（缺一不可）：
  1. 删 import
  2. 删 JSX 使用
  3. 删文件
- **建议**：「删除」类操作**用一次 Edit 完成 3 处变更**，避免分步 Edit 中某一步因字符串不匹配而漏改。
- **Vite HMR 在组件未导入时**不会自动报错（因为没编译到），**只在浏览器执行时才暴露 ReferenceError**——所以清理后必须打开页面验证。
- **Chrome DevTools MCP 的 `list_console_messages`** 是排查前端白屏的利器：直接列出控制台所有 error，无需打开浏览器 F12。

---

### 9.3 ⭐ 删除登录功能后端依赖清理不全

#### 故障表现

执行「删除登录功能」后，后端启动失败：

```
ModuleNotFoundError: No module named 'app.core.auth_service'
```

#### 根因

清理过程分多步，但 `main.py` 中**第三步**的 `from app.core.auth_service import init_default_admin` 这一行仍然存在。Edit 操作被某次中断（用户跳过），但 partial state 已被保存。

#### 修复

打开 [main.py](file:///d:/code/个人开发项目/202605/知识库/backend/main.py) 全文检索 `auth_service`、`init_default_admin`，删除所有 import 与调用点。

#### 经验

- **「删除」操作的依赖收集要全量**：用 `grep` 搜被删模块的引用名，确保 0 个引用才能删。
- **建议**：先列删除清单，按清单逐项删除，每步后跑一次 `python -c "import main"` 做语法验证。
- **大改动的兜底**：用 git 暂存区跟踪，删除失败可立即 `git checkout .` 回滚。

---

### 9.4 ⭐ VectorStore 维度冲突：ChromaDB collection 不可变

#### 故障表现

将 Embedding 从 `Qwen3-Embedding-0.6B`（1024 维）切换为 `Qwen3-VL-Embedding-8B`（4096 维）后，触发 reindex：

```
total_chunks: 639
failures: 0
```

表面上成功，但**实际没有任何 chunk 写入**，查询返回空结果。

#### 根因

ChromaDB 的 collection 在第一次添加时**绑定维度**（由首批向量的 dim 决定），**后续再向同一 collection 写入不同维度的向量会抛 `InvalidDimensionException`**。

```python
# vector_store.py 的 reindex 逻辑
existing = col.get(include=[])  # 读所有 ID
col.delete(ids=existing["ids"])  # 删 chunks
col.add(ids=..., embeddings=...)  # 加新 chunks ← 4096 维被拒绝
```

`delete()` 不会改变 collection 的维度，**新加的 4096 维向量被静默回滚**（因为 `add_document` 内部 try/except + JSON 兜底）→ 日志显示 success，数据库无变化。

#### 修复

1. **改 COLLECTION_NAME 为按维度动态生成**（[vector_store.py](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/vector_store.py#L36-L55)）：
   ```python
   def _get_collection_name() -> str:
       dim = get_embedding_service().dimension()
       return f"chunks_d{dim}"
   ```
2. **删除旧 chroma_db_v2 目录**（清空损坏状态）：
   ```bash
   rm -rf backend/data/chroma_db_v2
   ```
3. **重新 Reindex** → 自动创建 `chunks_d4096` collection，639 个 chunks 正常写入。

#### 经验

- **ChromaDB collection 维度不可变**：换 Embedding 必须换 collection 名（或重建 collection）。
- **永远不要相信「返回 0 errors」就以为成功**：写测试验证（`col.count()`、`col.peek()`）。
- **删除+重建的 collection 策略 vs 同名 collection 策略**：优先按维度/版本命名（`chunks_d4096`），历史数据可恢复。

---

### 9.5 ⭐ 配置不自洽：`default_model` 和 `dim` 矛盾

#### 故障表现

前端系统设置页显示：

```
Qwen/Qwen3-Embedding-0.6B · 4096 维
```

模型名是 0.6B（1024 维），但显示维度是 4096，明显矛盾。

#### 根因

[config.py#L114-L125](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/config.py#L114-L125) 在切换到 VL-8B 时，**只改了 `dim` 没改 `default_model`**：

```python
"siliconflow": {
    "default_model": "Qwen/Qwen3-Embedding-0.6B",   # 1024 维模型
    "dim": 4096,                                    # VL-8B 维度
}
```

#### 修复

```python
"siliconflow": {
    "default_model": "Qwen/Qwen3-VL-Embedding-8B",
    "dim": 4096,
}
```

#### 经验

- **配置字段之间要保持自洽**：`default_model` 和 `dim` 必须匹配。
- **建议**：用 `pydantic` 校验配置一致性，启动时报错而不是运行时显示矛盾。
- **UI 显示配置时**优先用 `EMBEDDING_MODEL_OVERRIDE`（实际生效值），而不是 `EMBEDDING_MODEL_NAME`（默认值）。

---

### 9.6 GZip 中间件 + Cache-Control 头配置

#### 实施

在 [main.py#L14-L82](file:///d:/code/个人开发项目/202605/知识库/backend/main.py#L14-L82) 增加：

```python
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(CacheControlMiddleware)
```

其中 `CacheControlMiddleware` 对元数据类接口设置 `Cache-Control: public, max-age={N}`。

#### 验证效果

| 接口 | 原始大小 | GZip 后 | 节省 |
|------|---------|--------|------|
| `/api/documents/list` | 14,098 B | 5,496 B | **61%** |
| `/api/embedding/providers` | 3,748 B | 1,431 B | **62%** |
| `/api/categories` | 526 B | 173 B | **67%** |
| `POST /api/embedding/encode` | 88,119 B | ~12,000 B | **~86%** |

#### 经验

- **GZip 是性能优化第一手段**，零代码改动即可生效。
- **中间件顺序很重要**：CORS 在最外层 → GZip → CacheControl → 业务路由。
- **< 500B 不压缩**（节省 CPU，得不偿失），用 `minimum_size` 控制。

---

### 9.7 uvicorn 多 worker 在 Windows 不可用

#### 故障表现

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

启动失败：

```
[WinError 10022] 提供了一个无效的参数
```

#### 根因

uvicorn 的多 worker 模式依赖 Linux 的 `fork` + `socket fd 传递`。Windows 没有 `fork`（只有 `spawn`），无法将 socket 句柄在父子进程间传递。

#### 修复

- **Windows 开发环境**：单 worker（接受性能损失）。
- **生产部署**：必须 Linux。已写好 [start_prod.py](file:///d:/code/个人开发项目/202605/知识库/backend/start_prod.py) 自动选 worker 数。
- **临时方案**：在 Windows 上启 4 个不同端口的 uvicorn（8000-8003），用 Nginx upstream 负载均衡（[nginx.conf](file:///d:/code/个人开发项目/202605/知识库/deploy/nginx.conf) 已配置）。

#### 经验

- **跨平台 daemon 行为差异**：`fork` vs `spawn` 是 Python 多进程的根本差异。
- **生产部署脚本必须在目标环境测试**，不要只在 Windows / macOS 测过就发布。

---

### 9.8 ChromaDB 写入锁导致「Cannot open header file」

#### 故障表现

Reindex 大量 chunks 时出现间歇性错误：

```
[Chroma] add_document failed: Cannot open header file
```

但最终统计仍报「成功」（chunks 数对）。

#### 根因

ChromaDB 用 HNSW 索引，**索引文件的 header 在多线程并发写入时可能短暂被独占锁**。FastAPI 是异步框架，**多个请求可能同时触发 reindex**（如初始化时 + 用户上传），导致竞争。

#### 修复

1. **加进程级 asyncio.Lock**（[vector_store.py](file:///d:/code/个人开发项目/202605/知识库/backend/app/core/vector_store.py)）：序列化所有写入操作。
2. **第一次 reindex 出现 638 次失败**时，删除 `chroma_db_v2/` 目录重建 → 干净状态，第二次完美。
3. **生产环境建议**：把 embedding 任务放到独立 worker（Celery / RQ / 自研 async worker），与 HTTP server 解耦。

#### 经验

- **ChromaDB 不适合高并发写入**：单实例单写者模式性能才稳定。
- **「最终成功」不一定真成功**：写测试断言 `col.count() == expected_count`。
- **HNSW 索引 结构**对文件锁敏感，并发场景优先考虑分片 / 多实例 / 异步队列。

---

### 9.9 性能优化的取舍

#### 实施的项目

1. GZip 中间件（节省 60-86% 带宽）
2. SQLAlchemy 连接池（`pool_size=10, max_overflow=20`）
3. Cache-Control 头（CDN 友好）
4. 生产多 worker 启动器（[start_prod.py](file:///d:/code/个人开发项目/202605/知识库/backend/start_prod.py)）
5. Nginx 反代 + GZip + SSL 模板（[deploy/nginx.conf](file:///d:/code/个人开发项目/202605/知识库/deploy/nginx.conf)）
6. Systemd 服务单元（[deploy/kb-backend.service](file:///d:/code/个人开发项目/202605/知识库/deploy/kb-backend.service)）
7. Dockerfile 多阶段构建（[backend/Dockerfile](file:///d:/code/个人开发项目/202605/知识库/backend/Dockerfile)）

#### 决定不做的事

| 优化项 | 不做的原因 |
|-------|----------|
| 切换到 PostgreSQL | 当前数据量 < 1MB，SQLite 足够 |
| 引入 Redis | 单机部署，避免增加运维负担 |
| 切换到分布式 Chroma | 单机性能可承受，分布式会引入一致性复杂度 |
| uvloop | Windows 不支持，跨平台方案需谨慎 |
| 切换到 LLM 微调 | 当前需求通用 RAG 足够，过早优化 |

#### 经验

- **不要过早优化**：先验证真实瓶颈，再针对性优化。
- **优化要可量化**：对比前后数据（响应大小、延迟、QPS），不能凭感觉。
- **运维复杂度是隐形税**：每多一个组件（Redis / K8s）都是潜在的故障源。

---

## 10. 复盘元数据（持续更新）

| 轮次 | 时间 | 主题 | 关键修复 |
|-----|------|------|---------|
| 1 | 2026-06-12 | 初版 | JSON VectorStore + 元数据查询分离 |
| 2 | 2026-06-15 | LangChain 集成 | 标签系统 / 图谱 / 引用 |
| 3 | 2026-06-18 | Qwen3 / ModelScope | 维度切换 + collection 重命名 |
| **4** | **2026-06-19** | **Embedding 切换 / 登录删除 / 端口冲突** | **9.1-9.9 全部记录** |

---

> **复盘文档的使命**：让下一个接手此项目（或同类项目）的开发者，**少走我们走过的弯路**。
