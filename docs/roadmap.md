# 灵砚 — AI 小说创作系统 实现状态

> **更新于 2026-08-20** - V1.0 ~ V3.0 全部完成，V4.0 规划中

## Current State

所有 4 个 Phase + 扩展功能 + 后续迭代 + V3.0 体验优化均已完成。系统是一个功能完备、体验优良的 AI 小说创作平台。

**当前评分：9.0/10** ⭐

---

## V3.2 迭代（2026-08）✅

本阶段完善短篇多阶段策划、长篇上下文注入、LLM 多厂商配置：

### 短篇模块
- [x] **3+1 阶段策划流程**：角色设计 → 剧情大纲 → 主题定调 → 故事创作（每阶段可编辑确认，删除了场景构建阶段）
- [x] **逐节点多轮生成**：节点独立正文存储、断点恢复、单节点重写
- [x] **根据评审重写 = 多轮逐节点二次生成**：评审意见 + 前文 + 节点原内容孤立重写每节点，其余保持
- [x] **局部编辑**：续写 / 扩写选中 / 重写选中（编辑模式内流式变换）
- [x] **评审集成 17 维度审计**：审计结果持久化到 `ShortStoryReview.audit_json`
- [x] **UI 状态同步修复**：生成/续写/保存/载入后评审按钮、润色按钮、字数、草稿横幅等同步

### 长篇模块
- [x] **相关性上下文注入**：出场角色勾选（前端面板）+ 分层记忆（上章结尾原文/近章摘要/远章压缩）+ 摘要兜底
- [x] **版本对比修复**：解决静默失败 + unified diff 着色显示

### LLM 配置
- [x] **多厂商配置**：`/settings/llm` 厂商页（DeepSeek/OpenAI/Ollama/自定义），key + base_url + 拉取模型 + 勾选启用
- [x] **自动默认模型**：未显式配置的 Agent 自动匹配已启用厂商模型（快速类匹配 flash/lite/mini，深度类匹配 pro/max/plus）
- [x] **LangChain 迁移**：统一 `app/services/llm.py`（langchain-openai），DeepSeek thinking 参数经 `extra_body` 传递
- [x] **配置优先级**：Agent 厂商模型 > Agent 参数 > 小说覆盖 > 自动默认 > Setting 遗留 > .env

---

## Phase 1 — 最小闭环 ✅

单章节生成 + 流式输出 + 版本存储。

- [x] Flask + SQLite + Jinja2
- [x] DeepSeek API 集成（OpenAI 兼容）
- [x] SSE 流式生成
- [x] 版本管理（AI / human / edit）

## Phase 2 — 知识库 ✅

- [x] 角色卡片（性格、说话风格、背景、动机、弧光）
- [x] 世界观卡片（分类管理）
- [x] 大纲树（卷 → 章 → 场景，三级）
- [x] 伏笔追踪（状态机 + 超时告警）
- [x] 上下文自动组装到 Writer prompt

## Phase 3 — 评审 + 修订循环 ✅

- [x] 评审结构化 JSON 输出
- [x] 维度分数 + 注释
- [x] 审批 → 自动生成摘要
- [x] 基于评审意见的改写
- [x] 用户对评审的反馈

## Phase 4 — 高级交互 ✅

- [x] 版本 diff（difflib unified diff）
- [x] 渐进式摘要生成（审批时触发）
- [x] 提示词模板库（含约束）
- [x] 仪表盘统计

---

## 扩展功能（超出原计划）

### StoryForge 启发功能 ✅

- [x] **故事状态引擎** — 弧阶段追踪（setup / development / climax / resolution）
- [x] **角色关系** — 5 维度量化（信任/好感/尊重/恐惧/依赖）
- [x] **伏笔状态机** — planned → buried → advancing → reclaimable → resolved
- [x] **多 Agent 流水线** — Writer + Critic + 4 Keepers 并行
- [x] **17 维度审计** — 6 个并行审计 Agent，5 个分组

### 质量控制 ✅

- [x] **De-AI Agent** — 120+ 禁用模式（8 大类），句式节奏修复，口语化润色
- [x] **写作约束** — 可注入到每个模板的质量规则
- [x] **文本清理** — Markdown 残留移除

### 研究启发功能 ✅

- [x] **因果链引擎** — cause → event → effect → decision
- [x] **向量记忆** — SQLite FTS5 语义检索
- [x] **信息边界** — 角色知识追踪（亲历/听闻/推断）
- [x] **风格指纹** — 从参考文本提取并应用风格
- [x] **Skill 系统** — 7 内置 + 自定义写作技巧
- [x] **时序真理库** — 追踪事实随时间的变化
- [x] **全书优化器** — 完成后诊断 + 自动修订

### 短篇模块 ✅

- [x] **3 种创作模式** — Inspiration（双 Agent）/ Setting / Careful
- [x] **版本管理 + 评审 + 审计**
- [x] **De-AI 处理**
- [x] **TXT / DOCX 导出**

### MCP Server & CLI ✅

- [x] **26 个 MCP 工具** — 完整 CRUD + 审计
- [x] **15 个 CLI 命令组** — 含 auth/whoami 认证
- [x] **脚本化操作** — 支持批量任务

---

## V2.5 - Per-Agent 配置 (2026-07) ✅

- [x] **16 种 Agent 类型** — writer/outline/summary/critic/rewrite/editor/audit/character_check/lore_check/foreshadow_check/causal_chain/temporal_truth/memory/style/optimizer/short_story
- [x] **三级配置优先级** — Agent 特定 > 小说覆盖 > 全局
- [x] **一键应用推荐配置** — 快速设置最佳实践
- [x] **UI 表格化编辑** — settings.html 中可视化配置

## V2.6 - 兼容性修复 (2026-07) ✅

- [x] **DeepSeek V4 模型适配** — V4 Pro / Flash 分组
- [x] **SSL 容错** — http_client.py 统一处理
- [x] **Linux venv 兼容** — bin/ 风格虚拟环境
- [x] **De-AI 扩充** — 从 40+ 升级到 120+ 模式

## V3.0 - 用户体验优化 (2026-07) ✅

### 用户认证 (P0-3) ✅
- [x] Session-based 认证（默认 7 天）
- [x] 全局 `before_app_request` 鉴权钩子
- [x] 公开路径白名单 (`/login`, `/static`)
- [x] API 未登录返回 JSON 401
- [x] 默认账号 admin/admin, user/user

### 新手引导 (P0-1) ✅
- [x] 首页「第一次使用灵砚？」引导卡片
- [x] 一键加载 3 部示例数据（玄幻/科幻/悬疑）
- [x] 关闭后通过 localStorage 记忆

### 仪表盘升级 (P1-2 + P2-5) ✅
- [x] 6 个统计卡片（字数/进度/完成度/连续/本周/平均）
- [x] 字数趋势 SVG 折线图
- [x] 进度条 + 目标完成度
- [x] 超时伏笔警告

### 模板库 (P2-1 + P1-4) ✅
- [x] 4 种大纲模板（节拍/三幕/英雄之旅/四幕）
- [x] 6 种角色模板（热血少年/冷峻剑客/温婉少女等）
- [x] AI 自动生成角色 API

### 多格式导出 (P2-2) ✅
- [x] TXT / DOCX（原有）
- [x] Markdown / HTML（新增）
- [x] EPUB（需要 ebooklib）

### 移动端适配 (P2-3) ✅
- [x] 汉堡菜单（< 768px）
- [x] 响应式统计卡片
- [x] 移动端登录菜单

### 草稿自动保存 (P1-3) ✅
- [x] 每 10 秒保存到 localStorage
- [x] 页面加载检测草稿，提供恢复
- [x] 成功保存后清除草稿

### CLI 认证 (P0-3) ✅
- [x] `auth login/logout/status/list` 命令
- [x] `whoami` 命令
- [x] 认证状态存储 `~/.lingyan_cli_auth.json`
- [x] 未登录命令直接退出

---

## Tech Stack

| 层 | 选型 |
|----|------|
| 后端 | Python 3.14, Flask |
| 数据库 | SQLite (SQLAlchemy ORM) |
| 前端 | Jinja2 + 原生 JS + 响应式 CSS |
| AI API | DeepSeek V4 (OpenAI 兼容) |
| 流式传输 | SSE via `flask.Response` |
| HTTP 客户端 | httpx (SSL 容错) |
| CSS | 自定义 "Ink & Shadow" 主题 + 响应式 |
| MCP | `mcp` Python SDK |
| 认证 | Flask Session (Cookie-based) |

---

## 项目指标

| 项目 | 数量 |
|------|------|
| 数据库模型 | 18 |
| Flask Blueprint | 22 (含 6 个服务蓝图) |
| 路由模块 | 16 |
| 业务服务 | 12 + 通用 HTTP 客户端 |
| MCP 工具 | 26 |
| CLI 命令组 | 15 (含 auth/whoami) |
| 禁用模式 (De-AI) | 120+ (8 大类) |
| 质量审计维度 | 17 (5 分组) |
| Agent 类型 | 16 |
| 短篇创作模式 | 3 |
| 大纲模板 | 4 |
| 角色模板 | 6 |
| 导出格式 | 5 (TXT/DOCX/MD/HTML/EPUB) |
| 综合评分 | 9.0/10 |

---

## V4.0 - 未来规划

### 多用户协作 (3 个月)
- [ ] 用户注册/登录
- [ ] 团队空间
- [ ] 协作者权限管理
- [ ] 实时编辑同步

### 移动 App (6 个月)
- [ ] React Native / Flutter
- [ ] 离线创作
- [ ] 语音输入

### AI 增强 (持续)
- [ ] 智能大纲生成（基于剧情关键词）
- [ ] 自动封面图生成
- [ ] 故事灵感推荐
- [ ] 角色对话模拟

### 商业化 (6 个月)
- [ ] SaaS 订阅版
- [ ] 模板市场
- [ ] 企业版 + 私有部署