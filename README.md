# 灵砚 (LingYan) — AI 小说创作系统

> 双盲审驱动的中文长篇 / 短篇小说创作工作台：写作、评审、一致性保障一站式完成。
> 借鉴开源社区（OpenWrite / jarvis-write / NovelForge / lieflat-less-ai-tone 等）的成熟机制，去其糟粕取其精华，沉淀为本项目的确定性工程能力。

Flask + Jinja2 后端，无需登录的单机应用，支持 DeepSeek / OpenAI / Kimi / 智谱 / Ollama 等 11 家 OpenAI 兼容厂商，按 Agent 类型配置不同模型。

## 📑 目录

- [功能特性](#-功能特性)
- [Web 端使用](#-web-端使用)
- [长篇完整工作流](#-长篇完整工作流)
- [短篇创作流程](#-短篇创作流程)
- [MCP / AI IDE 接入](#-mcp--ai-ide-接入)
- [CLI 快速上手](#-cli-快速上手)
- [项目结构](#-项目结构)
- [技术栈](#-技术栈)
- [快速开始](#-快速开始)
- [配置](#️-配置)
- [环境变量](#-环境变量)
- [数据与备份](#-数据与备份)
- [安全说明](#-安全说明)
- [测试](#-测试)
- [文档](#-文档)
- [常见问题 FAQ](#-常见问题-faq)
- [开源协议](#-开源协议)

---

## ✨ 功能特性

### 📝 创作链路（写 → 审 → 改 → 定稿）

**写作**
- **一键本章流水线**：缺大纲自动生成 → 正文 → 确定性门禁 → AI味收敛（人味分不升自动回滚保留原稿），停在人工审阅不自动审批；可 `--save` 落 AI 版本
- **流式生成**：SSE 逐字输出；字数双向保障——不足 2000 字自动续写补足，超目标 1.3 倍可一键「压缩超标」（保留情节节拍/对话/因果，压描写冗余）
- **创作罗盘**（借鉴 OpenWrite）：`author_intent`（全书承诺）+ `current_focus`（阶段目标）注入 writer/outline/rewrite/focus 四条链路的最高优先位置，上下文压缩永不裁掉；章节列表页内联编辑，防长篇写歪
- **上下文预算渐进压缩**：超 14000 字符按稳定优先级收缩（远章概要→近章摘要→世界观→检索记忆→角色次要字段）；罗盘/信息边界/上章结尾/大纲/伏笔/因果链永不压缩
- **大纲失配标记**：保存正文时记录大纲指纹，事后改纲自动标「⚠ 大纲已变更」，章节列表与写作页可见——改纲不再静默漂移
- **@skill-id 按需启用**：特别指示里写 `@chapter_hook` 临时附加技能（仅本次生效，不改全局）；只摘除已注册技能 id，未知 @词原样保留，邮箱不误判

**评审**
- **统一评审**：一键完成 Critic 结构化评分 + 阎浮×白骨双盲审并行；报告合并为统一意见清单
- **双盲审两角色**：阎浮（市场毒舌）× 白骨（文学刻薄）零上下文盲审——不给大纲设定，每条批评必须引用原文，只给「追读/弃稿」二值判决
- **意见勾选改写**：Critic 分项与两位编辑的意见统一降维成同一 Schema，评审面板勾选后「重写」逐条落实，不再漏损
- **盲审工作台**：全局 `/blind/` 页对任意短篇 / 章节 / 自由文本开审，结果独立存档可回看；「盲审 → 重写 → 再盲审」循环打磨

**定稿**
- **审批事务单一真源**：Web / MCP / CLI 三入口共用同一审批服务——空内容拒绝、LLM 摘要失败自动截取正文开头 300 字兜底、结构化记忆生成、故事状态推进
- **文风锚例反向提取**：人工版本审批时自动提取含对话段落为锚例候选，前端确认入库——你的手改直接变成下一次生成的风格锚

### 🧬 去 AI 化体系（基于 283 万字对照语料研究）

- **三层防御**：提示词约束（词库按预算装配）→ 文本后处理（120+ 规则带防误伤守卫，可全局开关）→ AI 痕迹检测 + 盲审把关
- **篇章 AI 痕迹检测**（ai_metric）：10 项对照语料验证（R≥2）的确定性检测——段首零回指、拟人化喻体、提示语冒号、破折号揭晓式、译文腔、翻案腔、相邻句同构、跨段重复、顿号过密、起首语；输出 0-100 人味分 + 违规摘录
- **困惑度雷达**：厂商 logprobs 拿逐 token 对数概率 → 逐句 ppl，定位「选词过于可预测」的句子——补上选词分布层（朱雀第一维信号），构式层检测覆盖不到的地方（数据集不够还只是测试）
- **AI味收敛回滚环**：检测 → 违规指令定向重写 → 复测 → **人味分不升自动回滚**（绝不保留更差版本）
- **修正指令自动注入**：检测违规转为修正指令，注入长篇章节 / 短篇逐节点 / 评审重写三条生成链路
- **采样惩罚**：writer / short_story 默认 frequency+presence 0.5/0.5，全链路透传，设置页可调
- **文风锚例**：真人原文直插 prompt 做风格锚定，覆盖全部正文生成链路
- 完整方法论与朱雀实测校准记录见 [docs/ai-tone-research.md](docs/ai-tone-research.md)

### 🧩 长篇一致性保障

- **因果链追踪**：`cause → event → effect → decision` 跨章因果提取与注入
- **FTS5 语义记忆**：中文逐字全文检索，相关性召回历史片段（零依赖，拒绝引入向量库）
- **信息边界**：角色只知道亲眼所见 / 被告知 / 可推断的事——独立字段注入且豁免压缩
- **时序真理库**：同一属性的事实变更自动闭合旧记录；旧值回潮会被一致性链检出
- **伏笔状态机**：`open → planned → buried → advancing → reclaimable → resolved` 全生命周期 + 超时预警（含 reclaimable）
- **一致性链**（Agent 协同 P2）：确定性三查先行——时序真相旧值回潮 / 伏笔回收逾期、推进脱班 / 已回收伏笔复现；疑点才交 Keepers 三 Agent 只裁疑点（不重读全文），人工定夺「改文 / 改设定 / 忽略」
- **抽取待确认队列**：时序真相自动抽取先入队，人工核验采纳才落真源——错抽不污染一致性注入

### 🎬 短篇工坊

- 三阶段可编辑策划（角色 → 大纲 → 主题）+ 逐节点多轮创作
- 断点续写、单节点重写、按评审意见逐节点二次生成
- 评审卡直出两位编辑判决，存档后可在盲审工作台勾选意见循环打磨
- 一致性保障：手动编辑与节点拼接冲突时自动保护

### 📂 知识库

- **角色库**：CRUD + 6 套模板 + AI 生成，出场角色勾选注入（减少无关设定稀释注意力）
- **世界观**：分类设定，补充设定超预算自动截断
- **大纲树**：卷/章/场三级树 + 拖拽排序 + 一键生成章节；编辑章大纲触发下游失配标记
- **角色关系**：多维评分 + 事件驱动演化，创建时自动校验自连 / 镜像重复 / 跨书
- **创作偏好档案**：文风偏好 / 写作禁忌 / 目标读者，长期有效注入全部写作链（与每章特别指示区分）

### 🛠️ 其他能力

- 📤 五格式导出（TXT / DOCX / Markdown / HTML / EPUB），HTML 导出全转义 + CSP
- 🔗 借鉴改写：风格模仿 / 情节骨架移植 / 三档洗稿
- 🧠 提示词模板库 + 13 个内置写作技巧（Skill）+ 作者文风协议（江南三技巧），生成后自动跑「技巧门禁」确定性验收
- 🖥️ **MCP Server（27 工具）**：含 `run_chapter_pipeline` 一键本章、`approve_chapter` 审批、全套知识库 CRUD
- ⌨️ **CLI（27 命令组）**：与 Web 同源复用，见下节
- 📱 移动端响应式布局

### 🌙 界面主题：朱金 · 玄漆 ——「夜幕下摊开的稿纸」

- **双层设计**：夜幕区保留玄漆暖黑底 + 朱砂/泥金主色（毛笔题字 + 朱印落款）；阅读面（卡片/列表/表单/输出区）转宣纸底 + 墨字
- **稿纸令牌影射**：容器内 CSS 变量自动解析为纸上深调，子规则与模板零改动适配；写作区为真稿纸（界格线 + 白瓷底控件 + 朱砂聚焦）；`color-scheme: light` 锁死纸面配色，浏览器深色模式不再把文字重绘成看不清的淡色
- **全站月夜氛围层**（`aurora.js`）：WebGL 暖玉满月、云纱掠面、烛光星子、朱金双色流光——半分辨率渲染 + 标签页隐藏即暂停，只做氛围不抢正文对比度
- **网关沉浸页**（`inkflow.js`）：Three.js 大满月 + 桂花雨粒子 + 朱金光尘 + 鼠标扰动
- 尊重 `prefers-reduced-motion`：减弱动效偏好下全部场景退化为静帧；WebGL 不可用时自动回退 CSS 光斑层

---

## 🖥️ Web 端使用

启动后访问 http://127.0.0.1:5000（免登录），核心页面：

| 页面 | 路径 | 说明 |
|------|------|------|
| 网关首页 | `/` | 功能导航卡、示例数据、快捷入口 |
| 小说列表 | `/novel/` | 长篇列表 + 创作罗盘卡 + 导出 |
| 写作页 | `/novel/<id>/chapter/<n>/write` | 核心：生成 / 门禁 / 全面评审 / 双盲审 / 批准 / AI味收敛 / 一致性核查 |
| 章节列表 | `/novel/<id>/` | 章节网格 + 大纲失配徽标 |
| 知识库 | `/novel/<id>/characters` `/world` `/outline` `/foreshadowing` | 角色 / 世界观 / 大纲树 / 伏笔 |
| 双盲审工作台 | `/blind/` | 任意文本 / 短篇 / 章节开审，结果存档回看 |
| 设置 | `/settings/` | 厂商 / Per-Agent 模型 / 文风锚例 / 创作偏好档案 |
| 短篇工坊 | `/short/` 及子页 | 三模式创作、逐节点多轮、评审卡 |

**写作页一个完整的章**：`AI 生成本章` → 看门禁报告与 AI 痕迹人味分 → `全面评审`（Critic + 双盲审并行）→ 勾选意见 → `重写` → `批准`（自动生成摘要 + 结构化记忆）。需要深度打磨时用顶部 `AI味收敛`（人味分不升自动回滚）和 `一致性核查`（确定性三查）。

---

## 🎯 长篇完整工作流

```
1. 新建小说           novel create → 填类型 / 简介 / 世界观
2. 设定创作罗盘       章节列表页「创作罗盘」卡：全书承诺 + 阶段目标（防写歪的锚）
3. 搭知识库           角色（可模板/AI生成）→ 世界观 → 大纲树（卷/章/场）→ 伏笔
4. 生成正文           「AI 生成本章」→ SSE 流式 → 门禁束自动检测 AI 痕迹
5. 打磨               人味分不达标 → AI味收敛；超字数 → 压缩超标；改大纲 → 失配标记提示
6. 评审               「全面评审」= Critic 结构化评分 + 阎浮×白骨双盲审并行
7. 修订               勾选评审意见 → 重写 → 复评（至多一轮，分数不升回滚）
8. 定稿               批准 → 摘要 / 结构化记忆 / 故事状态推进 / 风格备忘录累积
9. 一致性保障          审批时事实入队（queue 采纳）→ 后续章节一致性链三查
10. 导出              TXT / DOCX / MD / HTML / EPUB
```

每一步既可用 Web 也可用 CLI（复用同一服务层），全自动批量的新章用 `chapter pipeline`：

```bash
python cli.py chapter pipeline --novel 1 --number 5 --save
```

---

## 🎬 短篇创作流程

1. 选模式：**灵感模式**（发散 → 逐节点多轮生成）/ **设定模式**（先设定后生成）/ **细心模式**（单轮直出）
2. 三阶段策划：角色 → 大纲 → 主题（可编辑，AI 生成后手动调整）
3. 逐节点生成 → 断点续写 / 单节点重写 / 选中扩写
4. 评审卡直出阎浮×白骨判决 → 勾选意见返还 Writer 生成第二稿 → 存档后在 `/blind/` 工作台循环打磨
5. 批准 / 导出（TXT/DOCX/MD/HTML/EPUB）

---

## 🤖 MCP / AI IDE 接入

MCP Server 走 stdio 协议，27 个工具覆盖小说/章节/角色/世界观/伏笔/大纲/短篇/设置/审计 + 一键本章编排。在 Claude Code 的 `~/.claude/settings.json` 添加：

```json
{
  "mcpServers": {
    "lingyan": {
      "command": "python",
      "args": ["/绝对路径/到/mcp_server.py"],
      "env": {}
    }
  }
}
```

Cursor 等其他支持 MCP 的 IDE 同理。典型用法（Claude Code 里）：

```
用 mcp__lingyan__list_novels 看有哪些小说
用 mcp__lingyan__run_chapter_pipeline 给第 1 本小说生成第 5 章（缺大纲自动补）
用 mcp__lingyan__approve_chapter 审批最新版本（空内容会被拒绝）
```

---

## 🏗️ 项目结构

```text
lingyan/
├── run.py / cli.py / mcp_server.py   # 三个入口（Web / CLI 27 命令组 / MCP 27 工具）
├── app/
│   ├── __init__.py                   # Flask app 工厂，注册 25 个蓝图
│   ├── config.py / config_utils.py   # 配置加载与解析
│   ├── models/                       # 23 个 SQLAlchemy 模型（按领域拆分）
│   ├── routes/                       # 20 个路由蓝图（novel/chapter/generate/review/blind/...）
│   ├── services/                     # 24 个业务模块（writer_chain/chapter_runner/ai_metric/...）
│   ├── templates/                    # 23 个 Jinja2 模板
│   └── static/                       # 主题 CSS + 月夜氛围 JS
├── docs/                             # 架构/设计/路线/方法论文档（见文末索引）
└── tests/                            # 151 个用例（独立临时库，不碰开发数据）
```

---

## 🧱 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.14, Flask（app factory） |
| ORM | Flask-SQLAlchemy（SQLite 单文件 + FTS5 全文检索） |
| AI 接口 | langchain-openai，OpenAI 兼容协议（11 家厂商） |
| 流式 | SSE（`text/event-stream`） |
| 前端 | Jinja2 + 原生 JS + 响应式 CSS（朱金·玄漆主题） |
| 视觉 | Three.js 月夜氛围层（WebGL + 降级 CSS） |
| MCP | `mcp` Python SDK（stdio） |
| 检测 | 零 LLM 成本确定性规则（正则 + 统计特征） |

---

## ⌨️ CLI 快速上手

CLI 与 Web 复用同一套服务层，行为一致（不是各写一套）。27 个命令组：

| 命令组 | 用途 | 示例 |
|--------|------|------|
| `novel` | 小说 CRUD + 导出 | `python cli.py novel list` |
| `chapter` | 章节 CRUD + 版本 + 大纲失配 + **一键本章/收敛/压缩/一致性核查** | `python cli.py chapter pipeline --novel 1 --number 5 --save` |
| `compass` | 创作罗盘 | `python cli.py compass set --novel 1 --intent "复仇外壳写救赎"` |
| `tone` | AI 痕迹检测 / 收敛 / 困惑度雷达 | `python cli.py tone radar --novel 1 --number 5` |
| `consistency` | 一致性链核查（`--adjudicate` 交 AI 裁决） | `python cli.py chapter consistency --novel 1 --number 5` |
| `queue` | 抽取待确认队列（采纳/丢弃） | `python cli.py queue list --novel 1` |
| `preferences` | 创作偏好档案 | `python cli.py preferences set --style "冷峻克制"` |
| `blind` | 双盲审（run/latest/rewrite） | `python cli.py blind run --novel 1 --number 5` |
| `skill` / `constraint` | 写作技巧 / 去AI味约束词库 | `python cli.py constraint show --agent writer` |
| `llm` | 厂商/模型/Per-Agent 配置 | `python cli.py llm provider-add --preset deepseek` |
| `sys` | 系统信息 / **安全备份**（SQLite 备份 API） / 重置 | `python cli.py sys backup` |
| … | 完整清单 | `python cli.py --help` |

新章一条龙：
```bash
python cli.py chapter pipeline --novel 1 --number 5 --save
# 缺大纲生成 → 正文 → 门禁 → AI味收敛 → 保存 AI 版本（未审批），停在人工审阅
```

---

## 🚀 快速开始

**环境要求**：Python 3.14+、[uv](https://docs.astral.sh/uv/)

```bash
# 1. 安装依赖
uv sync --extra export        # export 含 DOCX/EPUB 导出所需库

# 2. 启动
uv run python run.py          # 打开 http://127.0.0.1:5000（免登录）

# 3. 配置厂商
#    进入「设置 → 模型配置」添加厂商并勾选模型，即配即用；
#    配置保存在数据库中，无需任何配置文件
```

首次进入点击「一键加载示例数据」即可体验完整流程。

> **可选**：想跳过页面配置、直接用单个 DeepSeek key 快速体验的话，`cp .env.example .env` 并填入 key。`.env` 只是最低优先级的兜底配置——应用在没有它时完全正常运行，所有模型配置以「设置」页面的厂商配置为准。

---

## ⚙️ 配置

| 层级 | 方式 | 说明 |
|------|------|------|
| 厂商配置 | `/settings/llm` 页面或 `cli.py llm provider-add --preset deepseek` | 内置 11 家预设，填 key 即拉取模型；**推荐方式，存数据库** |
| Per-Agent | `/settings/` 页面或 `cli.py llm agent-set` | 16 种 Agent 各自指定厂商/模型/温度/Token/采样惩罚 |
| 自动默认 | 无需配置 | 未显式配置的 Agent 自动匹配已勾选模型（快速类偏好 flash/lite，深度类偏好 pro/max）|
| 去 AI 化开关 | Setting 键 `deai_auto = "0"` 关闭 | 默认开启；仅对 AI 来源内容生效 |
| 创作偏好档案 | `/settings/` 页面卡片或 `cli.py preferences set` | 全书级长期约束（文风/禁忌/读者），注入全部写作链 |
| 环境变量兜底 | `.env`（可选） | 仅快速体验用；另有 `LINGYAN_DEBUG` / `LINGYAN_INSECURE_SSL` / `MAX_UPLOAD_MB` / `DATABASE_PATH` 运行参数 |

---

## 🌐 环境变量

`.env` 全部可选（见 `.env.example`），是**最低优先级**兜底——应用没有它也能跑，真正的配置在数据库（设置页）。运行参数：

| 变量 | 默认 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek key（仅免配置快速体验用） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek 接口地址 |
| `MODEL_NAME` | `deepseek-v4-pro` | 兜底模型 |
| `SECRET_KEY` | 随机 | Flask session 密钥（单用户场景可忽略） |
| `LINGYAN_DEBUG` | `0` | 调试模式（仅显式 =1 开启） |
| `LINGYAN_INSECURE_SSL` | `0` | =1 时跳过 LLM 接口证书校验（仅公网自签域需要） |
| `MAX_UPLOAD_MB` | `50` | 上传文件大小上限 |
| `DATABASE_PATH` | `data.db` | 数据库文件路径（支持覆盖，测试/多实例用） |

---

## 💾 数据与备份

- 全部数据（小说/章节/记忆/配置/厂商）都在 `data.db` 单文件里，直接拷贝即备份
- CLI 提供安全备份：`python cli.py sys backup`（走 SQLite 备份 API，WAL/并发下也是完整快照，优于裸文件拷贝）
- 开发库与测试库隔离：测试自动用 `.tmp-test/test.db`，`pytest` 永远不碰你的写作数据
- 数据库可随时重建（应用启动时自动建表 + 自动迁移旧库）

---

## 🔒 安全说明

本项目定位为**本机单人使用**的工具：

- 默认只绑定 `127.0.0.1`，无登录体系
- 自带 CSRF 轻防护（拒绝浏览器标记为跨站的写请求）
- LLM 接口默认强制 SSL 证书校验，内网地址自动豁免，公网自签域需显式设 `LINGYAN_INSECURE_SSL=1`
- 上传文件重命名存储、请求体默认上限 50MB
- CLI 与 MCP 不持久化 API key（仅命令行参数 / 数据库内打码展示）

请勿直接暴露到公网；如需远程访问，建议套一层带认证的反向代理。

---

## 🧪 测试

```bash
uv sync --group dev
uv run pytest            # tests/ 目录（151 例），独立临时数据库，不碰开发数据
```

测试覆盖：路由级接线（罗盘/意见/审批）、困惑度雷达对齐算法、收敛回滚环、一致性三查、编排器全阶段、抽取队列、写作包注入等。

---

## 📚 文档

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 系统架构、技术栈、数据模型 |
| [docs/technical-design.md](docs/technical-design.md) | 完整技术设计（功能模块 / 数据库 DDL / API 接口）|
| [docs/roadmap.md](docs/roadmap.md) | 版本实现状态与路线图（V1.0→V3.7）|
| [docs/mcp-cli-guide.md](docs/mcp-cli-guide.md) | MCP Server 与 CLI 完整用法 |
| [docs/ai-tone-research.md](docs/ai-tone-research.md) | 去 AI 味方法论：283 万字语料研究 + 朱雀实测校准 + 困惑度雷达 |
| [docs/agent-collaboration.md](docs/agent-collaboration.md) | Agent 协同方案：四条链拓扑 / 统一意见契约 / 编排器（P1-P4 已实施）|
| [docs/merge-assessment.md](docs/merge-assessment.md) | 第二轮开源扫描：jarvis-write / NovelForge 机制拆解与逐项裁决 |
| [docs/code-review.md](docs/code-review.md) | 全面代码审查报告（120+ 发现）|
| [docs/fix-report.md](docs/fix-report.md) | 上述审查的修复报告（47 文件，含验证记录）|
| [CLAUDE.md](CLAUDE.md) | 开发者速查：架构总览、开发规范、常用操作 |

---

## ❓ 常见问题 FAQ

**Q：需要先注册/登录吗？**
A：不需要。设计为**本机单人使用**，免登录直接可用；Web / CLI / MCP 三端都免登录。

**Q：生成了「AI 味」很重的文字怎么办？**
A：三连招：① 顶部「AI味收敛」——检测→定向重写→复测，人味分不升自动回滚原稿；② 设置页贴「文风锚例」（你的真人文字，越像越好）并开启；③ 检查采样惩罚（writer 默认 0.5/0.5）。方法论见 [docs/ai-tone-research.md](docs/ai-tone-research.md)。

**Q：长篇越写越乱、设定前后矛盾怎么办？**
A：一致性链四件套：① 写前「创作罗盘」定承诺；② 审批时事实入「待确认队列」人工采纳；③ 每章生成后跑「一致性核查」（时序真相回潮/伏笔排期/已回收复现）；④ 改大纲后看「失配标记」并按新纲重生成。

**Q：生成很慢？**
A：`chapter pipeline` 或「AI 生成本章」是串行多次大 LLM 调用（大纲→正文→门禁→收敛），分钟级属正常。要快：先用已有大纲（跳过大纲生成）、收敛可稍后再点、`--no-converge` 场景在 CLI 用 `tone check` 只查不改。

**Q：模型怎么配？**
A：设置 → 模型配置 → 添加厂商（11 家预设）→ 填 key → 拉取模型 → 勾选启用。未显式配置的 Agent 自动匹配已勾选模型，通常加一个厂商勾几个模型就能用。

**Q：CLI 和 Web 行为会不一致吗？**
A：不会。CLI 复用 Web 同一套服务层（`app/services/`），不是各写一套；Web/MCP/CLI 三入口共用审批、抽取、门禁等核心逻辑。

**Q：数据会丢吗？**
A：开发库是 `data.db`，测试永远不碰它；建议每天 `python cli.py sys backup`。数据库可重建（自动建表 + 迁移），但写作数据不可再生——备份习惯要养。

---

## 📄 开源协议

本项目采用 **[CC BY-NC-SA 4.0](LICENSE)**（署名—非商业性使用—相同方式共享 4.0 国际版）协议开源：

- ✅ **允许**：个人学习、研究、修改与分享（须署名，衍生作品以相同协议开源）
- ❌ **禁止商用**：不得将本项目或其衍生作品用于任何商业目的（出售、付费服务、商业产品集成等），除非获得作者单独授权
- 商业合作请通过 GitHub Issues 联系作者
