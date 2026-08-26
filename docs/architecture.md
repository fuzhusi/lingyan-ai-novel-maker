# 灵砚 — AI 小说创作系统 架构文档


> **更新于 2026-08-20** - 反映 V3.2 最新架构（单用户免登录、短篇 3+1 阶段策划、逐节点多轮生成、长篇相关性上下文注入、LLM 多厂商配置）

## 1. 概述

**灵砚 (LingYan)** — AI 小说创作系统。支持长篇和短篇创作，多 Agent 协作，双盲审两角色审评，按 Agent 类型配置模型，**单用户免登录**。

### 核心能力

- **Writer + Critic + 4 Keeper + Editor** 多 Agent 协作
- **双盲审两角色审评** — 阎浮×白骨零上下文盲审（替代旧 17 维审计）
- **因果链 + 向量记忆 + 信息边界** 长篇一致性保障
- **去 AI 化 + 风格指纹 + Skill 系统** 文字质量控制
- **按 Agent 类型配置模型** — 灵活的成本与质量权衡
- **短篇三模式** — Inspiration（发散 → 逐节点多轮生成）/ Setting / Careful
- **MCP Server + CLI** AI 与自动化可操作
- **单用户免登录** — Web/CLI 直接使用

---

## 2. 技术栈

| 层 | 技术 | 备注 |
|---|---|---|
| 语言 | Python 3.14 | — |
| Web 框架 | Flask | app factory 模式 |
| ORM | Flask-SQLAlchemy | — |
| 数据库 | SQLite | `data.db` 单文件 + FTS5 |
| AI 接口 | DeepSeek V4 API | OpenAI 兼容协议 |
| HTTP 客户端 | httpx | SSL 容错，SSE streaming |
| 前端 | Jinja2 + 原生 JS | 响应式 CSS |
| 样式 | CSS 自定义属性 | "朱金 · 玄漆" 中式主题（夜幕 + 宣纸稿纸面）+ 响应式；Three.js 环境月夜（aurora.js / inkflow.js） |
| 流式传输 | SSE | `text/event-stream` |
| 认证 | 已禁用 | 单用户模式，`login_required` 为 no-op |
| MCP | `mcp` Python SDK | stdio 协议 |

---

## 3. 项目结构

```text
Ai novel system/
├── run.py                          # Web 入口 (免登录)
├── cli.py                          # CLI 工具 (15 命令组，免登录)
├── mcp_server.py                   # MCP Server (26 工具)
├── .env                            # API 配置
├── data.db                         # SQLite 数据库
│
└── app/
    ├── __init__.py                 # Flask app 工厂 (22 blueprints)
    ├── config.py                   # 环境变量加载
    ├── models.py                   # 18 SQLAlchemy 数据模型
    │
    ├── routes/                     # 16 个路由蓝图
    │   ├── novel.py                # 小说 CRUD + gateway
    │   ├── chapter.py              # 章节 CRUD + 版本管理
    │   ├── generate.py             # AI 生成 SSE 流式
    │   ├── knowledge.py            # 知识库 CRUD + 角色模板 + AI生成
    │   ├── review.py               # 评审 + 审批 + 改写
    │   ├── short_story.py          # 短篇 (3 模式 + 版本 + 评审)
    │   ├── pipeline.py             # 多 Agent 并行检查
    │   ├── blind_review.py         # 双盲审工作台 + 通用 API
    │   ├── story_state.py          # 故事状态引擎
    │   ├── relations.py            # 角色关系
    │   ├── optimizer.py            # 全书优化
    │   ├── settings.py             # 全局 + Per-Agent 配置
    │   ├── templates_lib.py        # 提示词模板库
    │   ├── export.py               # TXT/DOCX/MD/HTML/EPUB 导出
    │   └── dashboard.py            # 仪表盘 (含趋势图)
    │
    ├── services/                   # 业务逻辑 (12 + 6 独立蓝图)
    │   ├── prompt_builder.py       # 提示词组装 + 约束
    │   ├── blind_review.py        # 双盲审引擎（阎浮×白骨）
    │   ├── causal_chain.py         # 因果链引擎 (蓝)
    │   ├── book_optimizer.py       # 全书诊断
    │   ├── vector_memory.py        # FTS5 向量记忆 (蓝)
    │   ├── deai_agent.py           # 去 AI 化 (120+ 禁用模式)
    │   ├── info_boundary.py        # 信息边界系统
    │   ├── style_fingerprint.py    # 风格指纹 + 文风锚例 (原文直插 prompt)
    │   ├── skill_system.py         # Skill 系统 (蓝)
    │   ├── temporal_truth.py       # 时序真理库 (蓝)
    │   ├── text_cleaner.py         # 文本清理
    │   ├── http_client.py          # SSL 容错 httpx 工厂
    │   ├── auth.py                 # 认证已禁用（单用户，login_required 为 no-op）
    │   ├── sample_data.py          # 示例数据生成 (蓝)
    │   └── outline_templates.py    # 大纲模板库 (蓝)
    │
    ├── templates/                  # 17 Jinja2 模板
    │   ├── base.html               # 基础布局 (含移动端菜单)
    │   ├── login.html              # 登录页（已禁用，仅保留路由）
    │   ├── gateway.html            # 网关首页 (含引导卡片)
    │   ├── novel_list.html         # 小说列表
    │   ├── chapter_write.html      # 写作页 (核心)
    │   ├── characters.html         # 人物管理
    │   ├── character_detail.html   # 角色详情
    │   ├── world_settings.html     # 世界观管理
    │   ├── outline.html            # 大纲树
    │   ├── foreshadowing.html      # 伏笔管理
    │   ├── dashboard.html          # 仪表盘 (含趋势图)
    │   ├── settings.html           # 设置 (含 Per-Agent 配置)
    │   ├── prompt_templates.html   # 提示词模板库
    │   └── short_story/
    │       ├── list.html
    │       ├── new.html
    │       └── write.html (含草稿恢复)
    │
    └── static/
        ├── css/
        │   └── main.css            # "朱金 · 玄漆" 主题（玄漆暖黑夜幕 + 朱砂/泥金；阅读面转宣纸稿纸，令牌影射）
        └── js/
            ├── aurora.js           # 全站环境月夜层（WebGL 暖玉满月 + 云纱 + 烛光星子 + 朱金双色流光；网关页自动让位）
            └── inkflow.js          # 网关沉浸页增强场景（Three.js 大满月 + 桂花雨粒子 + 鼠标扰动）
```

---

## 4. 数据模型 (18 张表)

### 4.1 核心业务 (6 张)

| 表 | 说明 |
|---|---|
| `novels` | 小说主体（标题、类型、简介、世界观、model_override） |
| `chapters` | 章节（编号、标题、大纲、用户指示） |
| `chapter_versions` | 多版本支持（来源：ai/human/rewrite） |
| `chapter_summaries` | 章节摘要 + 因果链 JSON |
| `critic_reviews` | 评审记录 |
| `prompt_templates` | 提示词模板（含约束） |

### 4.2 知识库 (4 张)

| 表 | 说明 |
|---|---|
| `characters` | 人物卡片（性格、说话风格、外貌、背景、动机、弧光） |
| `world_settings` | 世界观设定（按类别） |
| `outline_nodes` | 大纲树（卷 → 章 → 场景） |
| `foreshadowing` | 伏笔（状态机 + 超时 + 重要度） |

### 4.3 高级功能 (5 张)

| 表 | 说明 |
|---|---|
| `character_relations` | 角色关系（5 维度量化） |
| `story_states` | 故事状态引擎（弧阶段、冲突、伏笔） |
| `story_state_snapshots` | 状态快照（用于回滚） |
| `chapter_memories` | 章节记忆（场景级，键事件，角色变化） |
| `short_stories` | 短篇（3 模式 + 状态机 + 3 阶段策划字段 plan_characters/plan_theme） |

### 4.4 系统设置 (3 张)

| 表 | 说明 |
|---|---|
| `settings` | KV 表（全局 + Per-Agent 配置） |
| `llm_providers` | LLM 厂商（api_key/base_url/启用状态） |
| `llm_models` | LLM 模型（厂商下属模型，勾选启用） |
| `short_story_versions` | 短篇版本 |
| `short_story_reviews` | 短篇评审 |

---

## 5. 认证架构（已禁用）

### 5.1 现状：单用户免登录

登录/多用户模块已去除：

- `app/routes/auth.py`：`login_required` 为 no-op 装饰器，`/login` `/logout` 重定向首页
- 全局 `require_login` 钩子已删除，所有页面/API 直接放行
- `g.user` 恒为默认管理员（模板兼容）
- `cli.py`：`check_cli_auth()` 直接放行
- `app/templates/base.html`：用户区（登录/注销链接）已删除

### 5.2 恢复多用户

若需恢复，还原 `auth.py` 的 `require_login` 全局钩子和 `login_required` 实现，并在 `base.html` 恢复用户区即可。`DEFAULT_USERS` 常量与 `auth_bp` 注册均已保留。

---

## 6. 多 Agent 架构

### 6.1 长篇生成流水线

```text
Writer (V4 Flash)
    │
    ▼
┌─────────────┬──────────────┬──────────────┬──────────────┐
│   Critic    │  Character   │    Lore      │  Foreshadow  │  (4 Keeper 并行)
│  (V4 Pro)   │   Keeper     │   Keeper     │   Keeper     │
│             │  (V4 Pro)    │  (V4 Pro)    │  (V4 Pro)    │
└─────────────┴──────────────┴──────────────┴──────────────┘
                            │
                            ▼
                      Editor (V4 Pro)
                            │
                            ▼
                      最终润色输出
```

### 6.2 双盲审（两角色审评体系）

两位「恶毒编辑」对正文做零上下文盲审——不给大纲设定，只审判纸面事实，
每条批评必须引用原文，各给二值判决（追读 / 弃稿）：

| 编辑 | 视角 | 只关心 |
|------|------|--------|
| 尖酸嘴 · 阎浮 | 市场毒舌 | 读者会不会往下翻：钩子、灌水、跳段瞬间、AI 痕迹 |
| 白骨 · 文学审稿 | 文学刻薄 | 文字是不是「真的」：假情绪、假细节、套话腔、AI 腔 |

- 审评可返还 Writer 生成第二稿，循环「盲审 → 重写 → 再盲审」
- 引擎 `services/blind_review.py`；工作台 `/blind/`；API `/api/blind-review/*`
- 持久化独立 `BlindReview` 表；职责边界：一致性/伏笔逻辑由 Keepers 流水线负责

### 6.3 短篇 3+1 阶段策划流程（Inspiration / Setting 模式）

分阶段逐步生成，每阶段独立 AI 调用、产出可编辑、确认后解锁下一阶段：

```text
用户灵感 / 设定
    │
    ▼
阶段1 角色设计 (plan-characters) ──► 可编辑确认 ──► 解锁
    │
    ▼
阶段2 剧情大纲 (expand) ──► JSON 大纲 + 节点树 ──► 可编辑确认 ──► 解锁
    │
    ▼
阶段3 主题定调 (plan-theme) ──► 可编辑确认（可跳过）
    │
    ▼
阶段4 故事创作 (write-from-concept)
    │  逐节点多轮生成：注入角色档案 + 大纲 + 主题 + 前文
    │  每完成一个节点持久化（断点恢复）；
    │  根据评审重写 = 多轮逐节点二次生成（每节点孤立重写，其余保持）
    ▼
最终短篇输出（节点正文拼接 + 版本管理）
```

- 角色设计/主题定调可跳过；大纲是核心步骤
- 单节点重写：`/short/<id>/node/<node_id>/rewrite` 只重生指定节点
- 局部编辑：续写 / 扩写选中 / 重写选中（编辑模式内流式变换）

### 6.4 长篇上下文注入（相关性驱动）

章节生成时不再全量堆砌设定，而是按相关性注入（`assemble_chapter_context`）：

| 机制 | 说明 |
|------|------|
| 出场角色勾选 | 写作页「本章出场角色」面板勾选登场角色，只注入选中角色档案；全不勾 = 不注入；参数缺省（MCP/旧流程）= 全部 |
| 上章结尾原文 | 上一章最新版本正文末尾 ~800 字，保障文风与钩子衔接 |
| 分层记忆 | 近 3 章详细摘要 -> 更早章节合并压缩概要（>600 字截断），不随章节数线性膨胀 |
| 摘要兜底 | `ChapterSummary` 只在审批时生成；无摘要章节自动截取正文开头 300 字做粗摘要 |

**注入顺序**（`build_writer_prompt`）：

```
system: 去AI化约束 > 技能 > writer 人设
user:   小说信息 > 大纲树 > 世界观 > 出场角色 > 上一章结尾
        > 近章前情提要 > 更早章节概要 > 伏笔 > 因果链 > 记忆 > 本章大纲 > 特别指示
```

角色选择持久化到 `localStorage`（按小说+章节键）。
`/api/generate-stream` 新增表单参数 `character_ids`（逗号分隔 id）。

---

## 7. 配置系统

### 7.1 六级配置优先级

```
Agent 指定厂商模型 > Agent 参数 > 小说覆盖 (model_override)
    > 自动默认（厂商勾选模型） > Setting 全局键（遗留） > .env
```

| 级别 | 存储位置 | 配置方式 |
|------|---------|---------|
| Agent 厂商模型 | `Setting` 表 (`llm_model_{agent_type}`，格式 `provider_id:model_id`) | `/settings/` UI 表格 |
| Agent 参数 | `Setting` 表 (`temperature_{agent_type}` 等) | `/settings/` UI 表格 / CLI |
| 小说 | `Novel.model_override` (JSON) | API (`/settings/api/novel-model-override`) |
| 自动默认 | `LLMProvider` + `LLMModel`（已勾选模型） | `/settings/llm` 厂商页 |
| 全局（遗留） | `Setting` 表 (`api_key`, `base_url`, `model_name`) | UI 表单 / CLI |
| 环境变量 | `.env` | 手动编辑 |

**自动默认规则**：未显式配置的 Agent 自动使用已启用厂商的模型 --
快速生成类（writer/outline/summary/short_story 等）优先匹配 flash/lite/mini 关键词，
深度分析类（critic/audit/rewrite/editor 等）优先匹配 pro/max/plus 关键词，
无匹配用第一个勾选模型。配好厂商即全局生效，无需逐 Agent 手动选择。

**回退保护**：Agent 指定的模型被取消勾选后自动回退默认；
存在自动默认时忽略裸 `model_name_{agent}`（避免模型名与 key 错配 401）。

### 7.2 16 种 Agent 类型

**快速生成类 (V4 Flash)**
- `writer`, `outline`, `summary`, `memory`, `causal_chain`, `temporal_truth`, `short_story`

**深度分析类 (V4 Pro)**
- `critic`, `rewrite`, `character_check`, `lore_check`, `foreshadow_check`, `editor`, `audit`, `optimizer`, `style`

### 7.3 配置文件

**`.env`**
```env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-v4-pro
SECRET_KEY=dev-secret-key
DATABASE_PATH=data.db
```

---

## 8. 模板库 (新增)

### 8.1 大纲模板 (4 种)

| 模板 | 节点数 | 适用 |
|------|--------|------|
| 节拍式 | 15 | 商业小说 |
| 三幕式 | 12 | 戏剧性强 |
| 英雄之旅 | 12 | 冒险/成长 |
| 四幕式 | 13 | 电影剧本 |

**API:** `GET /api/outline-templates/list`

### 8.2 角色模板 (6 种)

- 热血少年、冷峻剑客、温婉少女、腹黑反派、智慧长者、搞笑担当

**API:** `GET /novel/<id>/characters/templates`

---

## 9. 核心服务

| 服务 | 功能 |
|------|------|
| `prompt_builder` | 提示词组装 + 9 种模板 + 写作约束注入 |
| `blind_review` | 双盲审引擎：阎浮×白骨两角色盲审 + 返还重写闭环 |
| `causal_chain` | 因果链提取（因→事→果→策） |
| `vector_memory` | FTS5 语义检索 |
| `deai_agent` | 120+ 禁用词 + 5 步处理 |
| `info_boundary` | 角色知识边界追踪 |
| `style_fingerprint` | 风格指纹提取 + 文风锚例（原文直插 prompt，全部正文生成链路） |
| `skill_system` | 7 内置 + 自定义写作技巧 |
| `temporal_truth` | 时序真理库 |
| `book_optimizer` | 全书诊断 + 自动修订 |
| `http_client` | SSL 容错 httpx 工厂 |
| `auth` | 认证已禁用（单用户免登录） |
| `sample_data` | 示例数据生成 |
| `outline_templates` | 大纲模板库 |

---

## 10. 一致性保障机制

| 机制 | 数据结构 | 应用场景 |
|------|---------|---------|
| 因果链 | `ChapterSummary.causal_chain_json` | 跨章节事件链 |
| 向量记忆 | SQLite FTS5 虚拟表 | 语义检索相关上下文 |
| 信息边界 | `Character` 知识追踪 | 防止角色"全知" |
| 时序真理 | `Setting` JSON 存储 | 角色/关系/世界状态随时间变化 |
| 风格指纹 | `Setting` JSON 存储 | 提取并应用写作风格 |
| 文风锚例 | `Setting` 键 `style_anchor_text/_enabled` | 真人原文直插 prompt 风格锚定（长篇+短篇全部正文链路） |
| Skill 系统 | `Setting` JSON 存储 | 注入写作技巧到 prompt |
| 角色关系 | `CharacterRelation` | 5 维度量化 |
| 故事状态 | `StoryState` | 弧阶段追踪 + 冲突 + 伏笔 |

---

## 11. 导出格式 (扩展)

| 格式 | 依赖 | 端点 |
|------|------|------|
| TXT | 无 | `/novel/<id>/export/txt` |
| DOCX | python-docx | `/novel/<id>/export/docx` |
| **Markdown** | 无 | `/novel/<id>/export/md` (新增) |
| **HTML** | 无 | `/novel/<id>/export/html` (新增) |
| **EPUB** | ebooklib | `/novel/<id>/export/epub` (新增) |

---

## 12. 启动

```bash
# 激活虚拟环境
source .venv/bin/activate        # Linux/macOS
source .venv/Scripts/activate    # Windows

# Web (免登录)
python run.py          # http://127.0.0.1:5000

# 首次访问
# 1. 打开 http://127.0.0.1:5000，免登录直接进入
# 2. 点击「一键加载示例数据」

# CLI (免登录)
python cli.py whoami
python cli.py novel list

# MCP Server (由 IDE 启动)
python mcp_server.py
```

---

## 13. 安全与稳定性

- **SSL 容错：** `verify=False`（`http_client.py`）
- **数据库迁移：** 自动 `ALTER TABLE` 在 `init_db()` 中
- **错误处理：** 所有 AI 调用有 try-except，返回 JSON 错误
- **单用户免登录：** 认证已禁用，`g.user` 恒为默认管理员
- **重置：** `python cli.py sys reset` 或手动删除 `data.db`