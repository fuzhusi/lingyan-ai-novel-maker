# 灵砚 (LingYan) — AI 小说创作系统

> 多 Agent 协作的中文长篇 / 短篇小说创作工作台：写作、评审、审计、一致性保障一站式完成。

Flask + Jinja2 后端，无需登录的单机应用，支持 DeepSeek / OpenAI / Kimi / 智谱 / Ollama 等 11 家 OpenAI 兼容厂商，按 Agent 类型配置不同模型。

---

## ✨ 功能特性

### 创作链路
- **多 Agent 协作**：Writer 生成 → Critic 评审 → 4 Keeper（角色/设定/伏笔守卫）并行检查 → Editor 润色
- **17 维度质量审计**：角色 / 剧情 / 世界观 / 文笔 / 伏笔五组维度加权评分，输出问题清单与改写建议
- **流式生成**：SSE 逐字输出，章节大纲→正文一键流水线
- **去 AI 化三层防御**：提示词约束 → 文本后处理（120+ 规则带防误伤守卫，可全局开关）→ AI 痕迹审计

### 长篇一致性
- **因果链追踪**：`cause → event → effect → decision` 跨章因果提取与注入
- **FTS5 语义记忆**：中文逐字全文检索，相关性召回历史片段
- **信息边界**：角色只知道亲眼所见 / 被告知 / 可推断的事
- **时序真理库**：同一属性的事实变更自动闭合旧记录
- **伏笔状态机**：`open → planned → buried → advancing → reclaimable → resolved` 全生命周期 + 超时预警

### 短篇工坊
- 三阶段可编辑策划（角色 → 大纲 → 主题）+ 逐节点多轮创作
- 断点续写、单节点重写、按评审意见逐节点二次生成
- 一致性保障：手动编辑与节点拼接冲突时自动保护

### 其他
- 📤 五格式导出（TXT / DOCX / Markdown / HTML / EPUB），HTML 导出全转义 + CSP
- 🔗 借鉴改写：风格模仿 / 情节骨架移植 / 三档洗稿
- 🧠 提示词模板库 + 13 个内置写作技巧（Skill）
- 🖥️ MCP Server（26 工具）+ CLI（18 命令组）
- 📱 移动端响应式布局

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
| Per-Agent | `/settings/` 页面或 `cli.py llm agent-set` | 16 种 Agent 各自指定厂商/模型/温度/Token |
| 自动默认 | 无需配置 | 未显式配置的 Agent 自动匹配已勾选模型（快速类偏好 flash/lite，深度类偏好 pro/max）|
| 去 AI 化开关 | Setting 键 `deai_auto = "0"` 关闭 | 默认开启；仅对 AI 来源内容生效 |
| 环境变量兜底 | `.env`（可选） | 仅快速体验用；另有 `LINGYAN_DEBUG` / `LINGYAN_INSECURE_SSL` / `MAX_UPLOAD_MB` / `DATABASE_PATH` 运行参数 |

---

## 🔒 安全说明

本项目定位为**本机单人使用**的工具：

- 默认只绑定 `127.0.0.1`，无登录体系
- 自带 CSRF 轻防护（拒绝浏览器标记为跨站的写请求）
- LLM 接口默认强制 SSL 证书校验，内网地址自动豁免，公网自签域需显式设 `LINGYAN_INSECURE_SSL=1`
- 上传文件重命名存储、请求体默认上限 50MB

请勿直接暴露到公网；如需远程访问，建议套一层带认证的反向代理。

---

## 🧪 测试

```bash
uv sync --group dev
uv run pytest            # tests/ 目录，独立临时数据库，不碰开发数据
```

---

## 📚 文档

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 系统架构、技术栈、数据模型 |
| [docs/technical-design.md](docs/technical-design.md) | 完整技术设计（功能模块 / 数据库 DDL / API 接口）|
| [docs/roadmap.md](docs/roadmap.md) | 版本实现状态与路线图 |
| [docs/mcp-cli-guide.md](docs/mcp-cli-guide.md) | MCP Server 与 CLI 完整用法 |
| [docs/code-review.md](docs/code-review.md) | 全面代码审查报告（120+ 发现）|
| [docs/fix-report.md](docs/fix-report.md) | 上述审查的修复报告（47 文件，含验证记录）|
| [CLAUDE.md](CLAUDE.md) | 开发者速查：架构总览、开发规范、常用操作 |

## 🗺️ 路线图

详见 [docs/roadmap.md](docs/roadmap.md)。当前 V3.x；V4.0 方向包括多用户、向量检索升级、协作编辑。

---

## 📄 开源协议

本项目采用 **[CC BY-NC-SA 4.0](LICENSE)**（署名—非商业性使用—相同方式共享 4.0 国际版）协议开源：

- ✅ **允许**：个人学习、研究、修改与分享（须署名，衍生作品以相同协议开源）
- ❌ **禁止商用**：不得将本项目或其衍生作品用于任何商业目的（出售、付费服务、商业产品集成等），除非获得作者单独授权
- 商业合作请通过 GitHub Issues 联系作者
