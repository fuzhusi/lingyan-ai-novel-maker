# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**灵砚 (LingYan)** — AI 小说创作系统。Python Flask 后端 + Jinja2 前端，支持长篇和短篇创作。
**核心特性**：多 Agent 协作（Writer + Critic + 4 Keepers + Editor）、17 维度质量审计、按 Agent 类型配置不同模型、长篇一致性保障（因果链 + 向量记忆 + 信息边界）、短篇逐节点多轮生成、单用户免登录。

## Development Environment

- **语言：** Python 3.14
- **包管理：** uv (pyproject.toml + uv.lock)
- **虚拟环境：** `.venv/` (uv 自动管理)
- **数据库：** SQLite (`data.db`)
- **AI 接口：** LangChain + OpenAI 兼容协议（支持 DeepSeek / OpenAI / Ollama / 自定义厂商）

激活虚拟环境：

```bash
source .venv/bin/activate        # Linux/macOS
source .venv/Scripts/activate    # Windows Git Bash/WSL
.\.venv\Scripts\Activate.ps1     # Windows PowerShell
```

## Run

```bash
python run.py          # Web: http://127.0.0.1:5000 (免登录)
python mcp_server.py   # MCP Server (stdio 协议)
python cli.py --help   # CLI 工具 (免登录)
```

uv 常用命令：
```bash
uv sync                # 安装依赖
uv sync --extra export # 安装导出依赖 (python-docx, ebooklib)
uv run python run.py   # 通过 uv 运行
```

## Architecture

```text
app/
├── __init__.py          # Flask app factory, 注册 25 个 blueprints
├── config.py            # AppConfig 从 .env 加载
├── config_utils.py      # 配置解析 (get_model_config / get_effective_config)
│
├── models/              # 21 个 SQLAlchemy 模型 (按领域拆分)
│   ├── __init__.py      # 统一导出 + init_db()
│   ├── base.py          # db 实例 + now()
│   ├── novel.py         # Novel, Chapter, ChapterVersion, CriticReview, PromptTemplate, Setting
│   ├── knowledge.py     # Character, WorldSetting, OutlineNode, Foreshadowing, CharacterRelation
│   ├── state.py         # StoryState, StoryStateSnapshot, ChapterMemory, ChapterSummary
│   ├── short_story.py   # ShortStory, ShortStoryVersion, ShortStoryReview
│   └── llm_provider.py  # LLMProvider, LLMModel（厂商+模型配置）
│
├── routes/              # 20 个路由蓝图
│   ├── novel.py         # 小说 CRUD + gateway
│   ├── chapter.py       # 章节 CRUD + 版本管理
│   ├── generate.py      # AI 生成 (SSE 流式)
│   ├── review.py        # 评审 + 审批 + 改写
│   ├── knowledge/       # 知识库 (子包)
│   │   ├── __init__.py  # Blueprint 定义
│   │   ├── characters.py # 角色 CRUD + 模板 + AI 生成
│   │   ├── world.py     # 世界观 CRUD
│   │   ├── outline.py   # 大纲树 CRUD + 创建章节
│   │   └── foreshadowing.py # 伏笔 CRUD + 超时检测 + 状态推进
│   ├── short_story/     # 短篇 (子包)
│   │   ├── __init__.py  # Blueprint 定义 + 核心 CRUD
│   │   ├── prompts.py   # 体裁指导 + AI 调用 + 提示词构建
│   │   ├── generate.py  # 灵感发散/逐节点多轮创作/生成/润色/分段生成
│   │   ├── review.py    # 评审 + 反馈 + 基于反馈重写
│   │   ├── versioning.py # 版本管理
│   │   └── export.py    # TXT/DOCX/MD/HTML/EPUB 导出
│   ├── plagiarize/      # 借鉴改写 (子包)
│   │   ├── __init__.py  # Blueprint 定义 + CRUD + 保存
│   │   ├── style.py     # 风格模仿 + 风格分析 + 保存为 Skill
│   │   ├── plot.py      # 情节借鉴 + 情节骨架提取
│   │   ├── rewrite.py   # 改写洗稿 (轻度/中度/重度)
│   │   └── upload.py    # 文件上传 (TXT/DOCX/EPUB)
│   ├── pipeline.py      # 多 Agent 并行检查
│   ├── audit.py         # 17 维度质量审计
│   ├── story_state.py   # 故事状态引擎
│   ├── relations.py     # 角色关系
│   ├── optimizer.py     # 全书优化
│   ├── settings.py      # 全局 + Per-Agent 配置页面
│   ├── templates_lib.py # 提示词模板库
│   ├── export.py        # 长篇 TXT/DOCX/MD/HTML/EPUB 导出
│   ├── dashboard.py     # 仪表盘统计
│   ├── auth.py          # 认证已禁用（单用户模式，login_required 为 no-op）
│   ├── sample_data.py   # 示例数据生成
│   ├── outline_templates.py # 大纲模板库 API
│   └── llm_settings.py  # LLM 厂商配置 API（厂商 CRUD + 拉取模型 + 勾选）
│
├── services/            # 业务逻辑 (9 个模块 + 5 个含 API 的服务)
│   ├── prompt_builder/  # 提示词构建 (子包)
│   │   ├── __init__.py  # 统一导出 + DEFAULT_WRITER_CONSTRAINTS
│   │   ├── context.py   # 模板加载 + 上下文组装
│   │   ├── writer.py    # Writer 类提示词
│   │   ├── review.py    # Review 类提示词
│   │   └── keepers.py   # Keeper + Editor 类提示词
│   ├── llm.py           # 统一 LLM 调用层 (langchain-openai)
│   ├── deai_agent.py    # 去 AI 化处理逻辑
│   ├── deai_patterns.py # 120+ 禁用模式数据
│   ├── audit.py         # 17 维度审计引擎 (蓝)
│   ├── book_optimizer.py # 全书诊断
│   ├── causal_chain.py  # 因果链提取 (蓝)
│   ├── vector_memory.py # FTS5 语义检索 (蓝)
│   ├── info_boundary.py # 角色知识边界系统
│   ├── style_fingerprint.py # 风格学习 (蓝)
│   ├── skill_system.py  # 写作技巧系统 (蓝)
│   ├── temporal_truth.py # 时序真理库 (蓝)
│   ├── text_cleaner.py  # 文本清理
│   └── short_story_templates.py # 短篇结构模板
│
├── templates/           # 17 个 Jinja2 模板 (含 login.html + short_story/)
└── static/              # 静态资源
    ├── css/main.css     # 流光 · 月砚 主题·中秋版（夜幕深空 + 天青/桂金/霞流光，满月悬空）
    └── js/
        ├── aurora.js    # 全站环境月夜层（WebGL 满月+云纱+星子+双色流光；网关页自动让位）
        └── inkflow.js   # 网关沉浸页增强场景（Three.js 大满月+桂花雨粒子+鼠标扰动）
```

## 数据库模型 (21 个)

| 类别 | 模型 |
|------|------|
| **核心** | Novel, Chapter, ChapterVersion, CriticReview, PromptTemplate, Setting |
| **知识库** | Character, WorldSetting, OutlineNode, Foreshadowing |
| **高级** | CharacterRelation, StoryState, StoryStateSnapshot, ChapterMemory, ChapterSummary |
| **短篇** | ShortStory, ShortStoryVersion, ShortStoryReview |
| **借鉴** | PlagiarizeTask |
| **LLM 厂商** | LLMProvider, LLMModel |

## Key Patterns

### 用户认证（已禁用）
- **单用户模式**：登录模块已去除，所有页面/API/CLI 免登录直接访问
- `app/routes/auth.py`：`login_required` 为 no-op 装饰器，`/login` `/logout` 重定向首页
- `app/templates/base.html`：用户区（登录/注销链接）已删除
- `cli.py`：`check_cli_auth()` 直接放行默认用户
- 保留 `DEFAULT_USERS` 常量与 `auth_bp` 注册（兼容代码引用），恢复多用户时还原 `auth.py` 的 `require_login` 钩子即可

### 配置管理
- **厂商配置：** `/settings/llm` 添加厂商（key/base_url）+ 勾选模型，配好即全局生效
- **常用厂商预设：** 内置 11 个 OpenAI 兼容厂商预设（DeepSeek/OpenAI/Kimi/智谱/通义/硅基流动/火山方舟/OpenRouter/Groq/Ollama/自定义）--Web 弹窗「快速选择」或 CLI `provider-add --preset <type>`，填 key 即可拉模型使用；预设表在 `app/routes/llm_settings.py` 的 `PRESET_PROVIDERS`，含 base_url 与获取 key 的入口链接；Ollama 无需 key（自动填占位）
- **自动默认：** 未显式配置的 Agent 自动使用已启用厂商的模型 —— 快速生成类（writer/outline/summary/short_story 等）优先匹配 flash/lite/mini 关键词，深度分析类（critic/audit/rewrite/editor 等）优先匹配 pro/max/plus 关键词，无匹配用第一个勾选模型
- **Per-Agent 配置：** 16 种 Agent 可在 `/settings/` 显式指定厂商模型（`llm_model_{agent}`，格式 `provider_id:model_id`）及温度/Token
- **Per-Novel 配置：** 通过 `Novel.model_override` (JSON) 覆盖
- **优先级：** `Agent 指定厂商模型 > Agent 参数 > 小说覆盖 (model_override) > 自动默认（厂商勾选模型） > Setting 全局键（遗留） > .env`
- **回退保护：** 厂商被禁用/删除时 Agent 指定的模型自动回退默认；已入库模型的勾选状态同时约束显式指定——取消勾选即视为否决该模型(Per-Agent指定自动回退默认)；未入库的自由填入别名不受勾选影响；存在自动默认时忽略裸 `model_name_{agent}`（避免模型名与 key 错配 401）
- **多厂商多模型自由填入：** langchain 的 model_name 只是传给 API 的字符串，`llm_model_{agent}` 的 model_id 不要求存在于模型列表（自定义部署/代理别名/Ollama 本地模型均可），厂商存在即生效
- **推荐配置定位：** DeepSeek flash/pro 的推荐默认与关键词匹配是低成本开发参考，非硬约束 -- 换任意厂商/模型只需 agent-set 或 Web 设置即可
- **代码示例：**
  ```python
  from app.config_utils import get_effective_config
  cfg = get_effective_config(novel, agent_type="writer")  # 自动应用全部优先级
  ```

### 流式输出 (SSE)
- 通过 `data: {"token": "..."}` 和 `data: {"done": true}` 推送
- 实现位置：`app/routes/generate.py:17` (`_stream_to_sse`)
- 客户端使用 `fetch` + ReadableStream 接收

### 多 Agent 协作
- **Writer** (章节生成) → **Critic + 4 Keepers** (并行评审) → **Editor** (润色)
- 每个 Agent 调用时传入 `agent_type` 参数使用各自的模型配置
- Keepers: Character Keeper, Lore Keeper, Foreshadow Keeper

### 长篇上下文注入（相关性驱动）
- **出场角色勾选**：写作页右侧「本章出场角色」面板勾选登场角色，生成时只注入选中角色档案（减少无关设定稀释注意力）；全不勾 = 不注入任何角色档案；参数缺省（旧流程/MCP）= 全部角色
- **分层记忆**：上一章结尾原文 ~800 字（保障文风与钩子衔接）-> 近 3 章详细摘要 -> 更早章节合并压缩概要（>600 字截断），不再全量线性注入
- **摘要兜底**：`ChapterSummary` 只在审批时生成；生成前情提要时对无摘要章节自动截取正文开头 300 字做粗摘要
- **注入顺序**（`build_writer_prompt`）：约束(system) > 小说名称 > 小说类型 > 简介 > 世界观 > 大纲树规划 > 世界观补充 > 出场角色 > 上一章结尾 > 近章摘要 > 远章概要 > 待回收伏笔 > 因果链 > 相关记忆 > 章节标题 > 本章大纲 > 特别指示(末尾最高优先)
- **伏笔全态注入**：「待回收伏笔」注入全部未回收状态（open/planned/buried/advancing/reclaimable），仅排除 resolved/abandoned，渲染附标题+埋设章+状态
- **职责分离去重**：结构化上下文（摘要/伏笔）由 `assemble_chapter_context` 统一负责；`memory_context` 只做 FTS 语义检索，不再重复注入摘要和伏笔
- **FTS 中文检索**：unicode61 分词器不识别 CJK 词边界，`_cjk_tokenize` 对索引/查询两侧中文逐字加空格实现按字检索；`_sanitize_fts_query` 按字短语 OR 连接支持纯中文大纲查询召回。**重建索引**后旧数据才可被检索（`POST /api/novel/{id}/memory/index`）
- 角色选择持久化到 `localStorage`（按小说+章节键），同章刷新保留勾选

### 去 AI 化 (De-AI)
- **三层防御**：Prompt 约束（最高优先级）→ 文本后处理 → 质量审计
- 自动应用于章节保存：`deai_process(content)`（仅 `source == "ai"` 的版本）
- **全局开关**：Setting 键 `deai_auto = "0"` 可整体关闭自动去AI化（CLI `force=True` 不受影响）
- 120+ 禁用模式分 8 类：虚词、情感、副词、模式化描写、对话、过渡、解释性开头、成语
- 规则带负向断言守卫（如"坚持了三天""决定权"不会被误削），口语化剥离仅作用于话语连接词开头
- 5 步处理流程：禁用词 → 正则 → 句式节奏 → 口语化 → 段落流畅
- **Few-shot 对比示例**：8 个"AI味 vs 人味"具体对比，引导模型写出人味
- **Rewrite/Editor 约束**：明确指示"保留自然的不完美"，避免"修复"人味

### 一致性保障
- **因果链：** `cause → event → effect → decision`，跨章节追踪
- **向量记忆：** SQLite FTS5 全文检索，无需外部向量库
- **信息边界：** 角色只能知道 亲眼所见/被人告知/推断 的事
- **时序真理：** 追踪事实随时间的变化（角色状态、关系、世界状态）
- **风格指纹：** 从参考文本提取并应用写作风格
- **Skill 系统：** 13 内置 + 自定义写作技巧，默认激活 5 个去AI化核心技能
- **示例锚定：** 内置技能采用「短规则 + ❌AI味/✅技巧写法 中文对照锚例」结构（实证依据：规则+对照例执行率远高于纯规则堆叠）；协议包技能（江南等）自带完整文件协议不受影响
- **质量门禁 (skill_gate)：** 生成完成后对全文做确定性校验（正则/统计，零 LLM 成本），按当前激活技能选择性检查——对话修饰语、三连排比、首先其次模板、段末升华、直述情绪标签、抽象感官词；违规带原文摘录，前端在生成结果下方渲染报告；API `POST /api/skills/gate-check` 传 JSON `{text}`

### 质量审计 (17 维度)
| 组 | 维度 |
|----|------|
| 角色 | 性格一致性、行为合理性、对话自然度、成长轨迹 |
| 剧情 | 逻辑连贯性、节奏把控、冲突推进、悬念管理 |
| 世界观 | 世界观一致性、战力平衡、时间线正确性 |
| 文笔 | 文笔流畅度、感官描写、AI痕迹、信息密度 |
| 伏笔 | 伏笔推进、伏笔回收 |

### 短篇逐节点多轮生成（灵感+设定模式）
- **分阶段策划流程**（3 阶段可编辑确认 + 1 阶段创作）：
  1. **角色设计**：`POST /short/{id}/plan-characters` — AI 产出角色档案 → `plan_characters`（纯文本，可编辑）
  2. **剧情大纲**：`POST /short/{id}/expand` — AI 综合角色档案产出 JSON 大纲 → `concept` + `outline_nodes`
  3. **主题定调**：`POST /short/{id}/plan-theme` — AI 综合全部策划提炼主题 → `plan_theme`（纯文本，可编辑）
  4. **故事创作**：`POST /short/{id}/write-from-concept` — 逐节点写正文，注入全部策划作为上下文
  - 每阶段独立 AI 调用，产出后可编辑（`POST /short/{id}/save-plan`），确认后解锁下一阶段
  - 角色设计/主题定调可跳过；大纲是核心步骤
  - 设定模式：用户已有 character_desc 时，阶段 1 以此为基础深化
- **大纲生成**：一次 AI 调用输出 JSON `{"concept","nodes":[...]}`，存入 `concept` + `outline_nodes`；大纲提示词注入 plan_characters
- **节点数** = 目标字数 / 1100（向上取整），单节点目标 800-1500 字；1.5 万字以上自动分幕
- **节点内容存储**：每个节点有独立 `content` 字段（`outline_nodes` JSON），逐节点生成后 `deai_process` 存入；全文 = `_rebuild_content_from_nodes(nodes)`
- **节点提示词**：注入角色档案 + 场景设定 + 主题基调 + 大纲 + 前文，确保全文一致性
- **单节点重写**：`rewrite_node(story_id, node_id)` — 只重新生成指定节点，其余保持不变
- **根据评审重写（多轮逐节点二次生成）**：`rewrite_with_feedback` - 有节点结构时遍历每个已完成节点，用「评审意见 + 前文 + 节点原内容」孤立重写该节点（目标字数 = 节点原文长度，不缩水），其余节点保持；节点正文逐个更新后 `_rebuild_content_from_nodes` 汇总全文并保存 rewrite 版本。单节点失败保留原文不破坏结构。无节点结构时回退全文重写（动态 max_tokens + 5 轮续写补足字数）
- **断点恢复**：每完成一个节点持久化 `outline_nodes`（含 `content`）；暂停后从第一个 pending点续写
- **局部编辑**：续写（`continue_story`）、扩写选中（`expand_selection`）、重写选中（`rewrite_selection`）— 纯流式变换，前端替换选区
- **一致性保障**：手动保存与节点拼接不一致时自动清除节点正文（禁用单节点重写，防止覆盖编辑）
- **评审集成**：评审 + 17 维度审计并行；审计结果持久化到 `ShortStoryReview.audit_json`，页面加载时渲染审计 bars
- **前端**：3 阶段渐进卡片（角色→大纲→主题）+ 节点进度条 + `===NODE:id:title===` 流式标记 + 暂停/继续 + 编辑模式
- **列表页**：显示节点进度、体裁、更新时间、智能按钮（继续/查看/打开）
- 细心模式（careful）不变：旧单轮直接生成路径

## MCP Server & CLI

### MCP Server (26 个工具)
- **配置：** `.claude/settings.json` 中添加 `lingyan` 服务器
- **小说/章节/角色/世界观/伏笔/大纲/短篇** 全 CRUD
- **质量审计：** `quick_audit`, `get_knowledge_context`

### CLI (18 个命令组，免登录)
```bash
python cli.py whoami                 # 查看当前用户（恒为默认管理员）

# 业务命令
python cli.py novel list              # 小说列表
python cli.py novel create --title X  # 创建小说
python cli.py novel update --id 1 --title X --genre X  # 更新小说
python cli.py novel export --id 1 --format txt [--output 路径]  # 导出 txt/docx/md/html/epub（复用 Web 导出）
python cli.py novel delete-all -y     # 删除全部小说（危险）
python cli.py chapter list --novel 1  # 章节列表
python cli.py chapter content --novel 1 --number 1 --full  # 查看正文
python cli.py chapter update --novel 1 --number 1 --title X  # 更新章节
python cli.py chapter delete --novel 1 --number 1 -y  # 删除章节
python cli.py chapter version-list --novel 1 --number 1        # 章节版本列表
python cli.py chapter version-content --novel 1 --number 1 --version 2  # 查看指定版本
python cli.py chapter version-delete --novel 1 --number 1 --version 2   # 删除版本
python cli.py chapter deai --novel 1 --number 1 [--save]       # 去AI化诊断（--save 存新版本）
python cli.py character create --novel 1 --name X
python cli.py character update --id 1 --personality X  # 更新角色
python cli.py character delete --id 1 -y               # 删除角色
python cli.py character template-list                  # 角色模板列表（6 种）
python cli.py character create-from-template --novel 1 --template brave_hero [--name Y]  # 从模板建角色
python cli.py world create --novel 1 --category X --title X
python cli.py world update --id 1 --title X    # 更新世界观（用 --id，不需 --novel）
python cli.py world delete --id 1 -y           # 删除世界观
python cli.py foreshadow create --novel 1 --title X
python cli.py foreshadow update --id 1 --description Y --importance 8 --status planned  # 编辑伏笔
python cli.py foreshadow timeout-check --novel 1 [--chapter N]  # 超时伏笔检测
python cli.py foreshadow delete --id 1 -y      # 删除伏笔
python cli.py outline create --novel 1 --title X [--type scene --parent 卷ID]
python cli.py outline update --novel 1 --id N --summary Y      # 编辑大纲节点
python cli.py outline delete --novel 1 --id N -y               # 删除节点（递归级联子节点）
python cli.py outline create-chapter --novel 1 --id N          # 大纲节点预填建章（含分幕指引）
python cli.py relation create --novel 1 --char-a 1 --char-b 2
python cli.py relation update --id 1 --type rival              # 编辑关系
python cli.py relation event --id 1 --event betrayal [--intensity 1.5]  # 关系事件调整评分
python cli.py relation delete --id 1 -y        # 删除关系
# 故事状态引擎
python cli.py state get --novel 1               # 查看/自动创建故事状态
python cli.py state set --novel 1 --quest X --phase development --intensity 3 [--subplot Y] [--conflict Z]
python cli.py state auto-detect --novel 1 [--apply]     # 弧线阶段自动检测
python cli.py state snapshot --novel 1 [--chapter N] [--checkpoint]  # 创建快照
python cli.py state snapshots --novel 1         # 快照列表
python cli.py state rollback --novel 1 --snapshot ID -y # 回滚到快照
# 短篇
python cli.py short create --title X --mode inspiration
python cli.py short update --id 1 --genre Y --word-target 5000  # 更新元数据
python cli.py short version-list --id 1                 # 短篇版本列表
python cli.py short version-load --id 1 --version 2     # 历史版本载入为当前正文
python cli.py short approve --id 1 --version 2          # 审批版本
python cli.py short export --id 1 --format epub [--output 路径]  # 导出 5 格式
python cli.py short delete --id 1 -y           # 删除短篇
python cli.py setting list            # 查看配置（全局+Agent）
python cli.py setting apply-recommended  # 应用推荐配置
python cli.py setting clear-agent     # 清除所有 Agent 自定义配置（含 llm_model_*）
# LLM 厂商与模型配置（对齐 Web /settings/llm）
python cli.py llm preset-list                                   # 常用厂商预设表（11 个）
python cli.py llm provider-add --preset moonshot --api-key KEY  # 按预设添加，填 key 即用
python cli.py llm provider-add --preset ollama                  # 本地 Ollama 无需 key
python cli.py llm provider-list                              # 厂商列表
python cli.py llm provider-add --name X --base-url URL --api-key KEY --provider-type deepseek  # 全手动
python cli.py llm provider-update --provider 1 --enabled false
python cli.py llm provider-delete --provider 1
python cli.py llm fetch-models --provider 1                 # 拉取模型列表
python cli.py llm model-list [--provider 1]                 # 模型列表（●/○ 勾选状态）
python cli.py llm model-toggle --model 2                    # 勾选/取消单个模型
python cli.py llm model-toggle-all --provider 1 --enabled true
python cli.py llm test --provider 1                         # 测试厂商连接
# Per-Agent 模型配置
python cli.py llm agent-list                                # 16 个 Agent 生效模型+来源
python cli.py llm agent-set --agent-type critic --llm-model 1:deepseek-v4-pro   # model_id 可为任意模型名（自定义部署/别名，透传 API）
python cli.py llm agent-clear --agent-type critic           # 清除回退默认
python cli.py llm agent-param --agent-type writer --temperature 0.9 --max-tokens 4096
python cli.py llm effective --agent-type writer [--novel 1] # 实际生效配置（含 per-novel 覆盖）
# 写作技巧
python cli.py skill list              # 写作技巧列表（按分类：作者文风协议/通用/自定义）
python cli.py skill toggle --skill jiangnan_fingerprint  # 切换激活
python cli.py skill preview --task-type write           # 预览实际注入Writer的完整提示词
python cli.py audit run --novel 1 --number 1  # AI 痕迹审计
python cli.py optimize diagnose --novel 1     # 全书诊断
python cli.py optimize deai --novel 1 --number 2 [--save]  # 章节去AI化（--save 存新版本）
python cli.py sys info                # 系统统计
python cli.py sys sample-data         # 加载示例小说（对齐 Web 一键加载）
```

## 核心功能

### 📊 Dashboard 统计
- 6 个统计卡片（字数/进度/完成度/连续创作/本周/平均）
- 连续创作天数为真实计算：从今天（或昨天）起回溯连续有版本创建的天数
- 本周字数 = 近 7 天创建的版本正文字数之和
- 字数趋势 SVG 折线图
- 进度条 + 超时伏笔警告（口径与 `/api/foreshadowing/timeout-check` 一致：
  全部未回收状态，含 reclaimable，以最新章节号为基准）

### 📝 大纲模板 (4 种)
- 节拍式 (15 节点)
- 三幕式 (12 节点)
- 英雄之旅 (12 节点)
- 四幕式 (13 节点)
- API: `/api/outline-templates/list`

### 🎭 角色模板 (6 种)
- 热血少年、冷峻剑客、温婉少女、腹黑反派、智慧长者、搞笑担当
- AI 自动生成角色 API
- 应用模板 API: `/novel/<id>/characters/create-from-template`

### 📤 多格式导出
- TXT / DOCX / **Markdown** / **HTML** / **EPUB**
- 端点: `/novel/<id>/export/{txt,docx,md,html,epub}`

### 📱 移动端
- 汉堡菜单（< 768px 屏幕）
- 响应式统计卡片

### 💾 草稿自动保存
- 每 10 秒保存到 `localStorage`
- 页面加载时检测草稿，提供恢复

### 🔗 借鉴改写
- **风格模仿**：分析参考文本风格 → 生成风格分析报告 → 用该风格创作新内容 → 可保存为自定义 Skill
- **情节借鉴**：提取情节骨架 → 套用到新角色/世界观 → 生成全新故事
- **改写洗稿**：三档改写程度（轻度/中度/重度）→ 左右对比视图
- **文件上传**：支持 TXT/DOCX/EPUB 文件导入
- **输出**：保存为长篇章节或短篇
- 端点: `/plagiarize/`

## Key Files

- `.env` - API Key、Base URL、模型名称
- `pyproject.toml` - 项目配置和依赖 (uv)
- `data.db` - SQLite 数据库 (自动创建)
- `docs/README.md` - 文档索引（导航到所有文档）
- `docs/architecture.md` - 架构详细文档
- `docs/technical-design.md` - 技术设计文档（含数据库 DDL、API 接口）
- `docs/roadmap.md` - 实现状态与路线图
- `docs/mcp-cli-guide.md` - MCP/CLI 详细使用指南
- `docs/open-source-survey.md` - 45 个开源项目调研报告（归档）
- `docs/improvement-plan.md` - 产品整改计划（归档，大部分已完成）

## 配置参考

### DeepSeek V4 模型
| 模型 | 名称 | 用途 |
|------|------|------|
| V4 Pro | `deepseek-v4-pro` | 深度分析（评审/审计/改写） |
| V4 Flash | `deepseek-v4-flash` | 快速生成（章节/大纲/摘要） |

⚠️ **注意：** `deepseek-chat` 和 `deepseek-reasoner` 将于 **2026/07/24 弃用**。

### 推荐配置（Per-Agent）
| Agent | 模型 | 温度 | Max Tokens |
|-------|------|------|-----------|
| writer | V4 Flash | 0.9 | 4096 |
| outline | V4 Flash | 0.8 | 2048 |
| summary | V4 Flash | 0.5 | 1024 |
| critic | V4 Pro | 0.3 | 2048 |
| rewrite | V4 Pro | 0.7 | 4096 |
| editor | V4 Pro | 0.5 | 4096 |
| audit | V4 Pro | 0.3 | 2048 |
| character_check | V4 Pro | 0.3 | 2048 |
| lore_check | V4 Pro | 0.3 | 2048 |
| foreshadow_check | V4 Pro | 0.3 | 2048 |

## 常用操作

### 首次使用
```bash
# 1. 启动 Flask
python run.py > /tmp/flask.log 2>&1 &
# 2. 浏览器访问 http://127.0.0.1:5000（免登录，直接进入）
# 3. 点击「一键加载示例数据」
```

### CLI 首次使用
```bash
# 免登录，直接执行命令
python cli.py novel list
python cli.py short list
```

### 重启 Flask
```bash
pkill -9 -f "python run.py"
source .venv/bin/activate
python run.py > /tmp/flask.log 2>&1 &
```

### 重置数据库
```bash
rm data.db
python run.py  # 重新初始化
```

### 测试 De-AI 效果
```python
from app.services.deai_agent import deai_process, get_deai_stats
cleaned = deai_process(raw_text)
print(get_deai_stats(raw_text, cleaned))
```

## 注意事项

1. **生成操作**（AI 生成章节、评审、改写）需要通过 Web 页面进行，因为是流式输出
2. **MCP Server** 通过 stdio 协议通信，需要由 Claude Code 等 IDE 启动
3. **CLI** 直接操作数据库，免登录
4. 所有时间戳使用 UTC（`now()` 函数）
5. SSL 默认强制证书校验；仅内网地址（localhost/127.x/10.x/192.168.x/172.16-31.x/.local）自动豁免。对公网域跳过校验需显式设 `LINGYAN_INSECURE_SSL=1`（`app/services/llm.py`）
6. 中文 UI 字符串直接硬编码在模板中，未做 i18n
7. **单用户模式**：无登录环节，`g.user` 恒为默认管理员

## Troubleshooting

| 问题 | 解决 |
|------|------|
| 端口 5000 被占用 | `pkill -9 -f "python run.py"` |
| 数据库锁定 | 等待其他进程完成或重启 Flask |
| API 401 错误 | 到 `/settings/llm` 确认厂商 api_key 有效并已勾选模型（点「测试」验证） |
| SSL 错误 | 默认强制校验；自签证书的内网地址自动豁免。公网自签域可临时设 `LINGYAN_INSECURE_SSL=1` |
| 模型不生效 | `llm effective --agent-type X` 看实际生效来源；厂商是否禁用（禁用则回退默认）；该 Agent 是否显式指定了其他模型 |
| 短篇发散后无节点进度条 | 发散输出未按节点格式（旧 prompt 缓存），重新发散即可 |