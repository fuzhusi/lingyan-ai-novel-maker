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
- [x] **评审集成双盲审**：写作页评审卡直接跑两角色盲审（阎浮×白骨），结果持久化到独立 `BlindReview` 表，`/api/blind-review/latest` 恢复展示
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
- [x] **双盲审两角色审评** — 阎浮×白骨零上下文盲审（原 17 维审计已由其取代，引擎 `services/blind_review.py`）

### 质量控制 ✅

- [x] **De-AI Agent** — 120+ 禁用模式（8 大类），句式节奏修复，口语化润色
- [x] **写作约束** — 可注入到每个模板的质量规则
- [x] **文本清理** — Markdown 残留移除

### 研究启发功能 ✅

- [x] **因果链引擎** — cause → event → effect → decision
- [x] **向量记忆** — SQLite FTS5 语义检索
- [x] **信息边界** — 角色知识追踪（亲历/听闻/推断）
- [x] **风格指纹** — 从参考文本提取并应用风格
- [x] **文风锚例 (Style Anchor)** — 真人原文直插 prompt 风格锚定；长篇+短篇全部正文生成链路（生成/改写/润色/局部编辑）；设置页粘贴 + 短篇写作页圆点开关
- [x] **篇章 AI 痕迹检测 (ai_metric)** — 10 项确定性检测 + 人味分，修正指令自动注入三条生成链路
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
- [x] **18 个 CLI 命令组** — 含 auth/whoami 与故事状态引擎 state
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

## V3.5 - 去 AI 化攻坚 (2026-08) ✅

> 目标：降低朱雀检测的 AI 判定率。基于 283 万字对照语料研究（`docs/ai-tone-research.md`）。

### 检测与修正闭环 ✅
- [x] **篇章 AI 痕迹检测 (ai_metric)** — 10 项特征确定性检测（零 LLM 成本）+ 0-100 人味分 + 违规摘录 + 统计指标；随 gate-check 返回，长篇/短篇写作页渲染
- [x] **修正指令自动注入** — `build_tone_instructions()` 把检测结果转为定向修正指令，注入长篇章节/短篇逐节点/评审重写三条生成链路

### 生成层干预 ✅
- [x] **采样惩罚** — writer/short_story 默认 frequency_penalty=0.5 + presence_penalty=0.5，全链路透传；Web 设置页可视化配置 + CLI `agent-param`
- [x] **Phase 0 止血** — 停用比喻简化规则（人类比喻频率是 AI 的 2.4 倍）；skill_gate 排比判定改为仅跨句（句内排比人类更高频）
- [x] **文风锚例 (Style Anchor)** — 真人原文直插 prompt 做风格锚定（一手 token 级质感）；按段落边界截断上限 2000 字符；注入长篇+短篇全部正文生成链路（章节生成/聚焦生成/评审改写/Editor 润色、逐节点生成/单节点重写/全文重写/AI 润色/续写/扩写选中/重写选中/分段生成）；API `GET/POST /api/style-anchor` + `/toggle`；设置页粘贴卡 + 短篇写作页「文风锚定」圆点开关（同源联动）
- [x] **约束纠偏** — 人味红线负向清单（勿删比喻/设问/句内排比）；DeepSeek 破折号/冒号约束；材料密度指令
- [x] **测试** — 96 个用例全过（含 test_style_anchor.py 7 个）

---

## V3.6 - 长篇创作罗盘与上下文工程 (2026-08) ✅

> 借鉴 LiPu-jpg/OpenWrite（本地长篇小说 AI 工作台，L 站社区项目）的四项核心机制，去其糟粕取其精华。
> 不复刻：文件系统真源（SQLite 是灵砚根基）、LightRAG（FTS5 零依赖够用）、37 维审稿（与双盲审定位重叠）。

### 创作罗盘 ✅
- [x] **Novel.author_intent / current_focus 字段** — 全书承诺（长期不变，≤500 字）+ 阶段目标（手动更新，≤300 字）；SQLite 自动迁移；罗盘注入每次生成且豁免压缩，必须限长防 prompt 膨胀
- [x] **注入四条生成链路** — writer / outline / rewrite / focus 聚焦生成，位于上下文最高优先位置；`build_compass_block()` 单点拼装防文案漂移；路由级接线测试锚定（`test_generate_stream_wires_compass`，writer 主链路曾漏接罗盘）
- [x] **永不压缩** — 罗盘在上下文预算收缩中豁免
- [x] **章节列表页「创作罗盘」编辑卡** — `POST /novel/<id>/compass`，未设定时提示防写歪

### 上下文预算渐进压缩 ✅
- [x] **apply_context_budget(kw, budget=14000)** — 超预算按稳定优先级收缩：远章概要 → 近章摘要逐章降级 → 世界观补充截断 → 检索记忆截半 → 角色次要字段；罗盘/boundary_context(信息边界+时序真相)/上章结尾/本章大纲/特别指示/伏笔/因果链永不压缩
- [x] **信息边界独立注入** — 信息边界+时序真相拆入 `boundary_context` 独立字段（原混入 memory_context 会被截半拦腰，破坏一致性红线）

### 写章事务保护 ✅
- [x] **审批空内容拒绝** — `chapter_approval.approve_chapter_version()` 单一真源，Web / MCP / CLI 三入口统一防护；Web 空 version 返回 400，前端提示错误（不再静默）
- [x] **摘要兜底** — 审批时 LLM 摘要失败自动截取正文开头 300 字粗摘要，前情提要链路不断

### @skill-id 按需启用 ✅
- [x] **特别指示临时附加技能** — `@chapter_hook` 语法仅本次调用生效，不改全局激活状态；只摘除已注册技能 id，未知 @词（如社交 handle）原样保留；邮箱类不误判；writer/rewrite 链路支持
- [x] **测试** — 149 个用例全过（test_compass_budget.py 20 含路由级接线；test_perplexity_radar.py 9；test_merge_writes.py 12；test_agent_collab.py 13 覆盖意见契约/一致性链/编排器/写作包）

---

## V3.7 - 检测与协同强化 (2026-09-04) ✅

> OpenWrite 集成收尾修复 + 融合评估（[merge-assessment.md](merge-assessment.md)）快赢四项 + 困惑度雷达。
> Agent 协同 P1-P4 见上方 V4.0 段与 [agent-collaboration.md](agent-collaboration.md)。

### 检测层
- [x] **困惑度雷达 (perplexity_radar)** — 厂商 logprobs 逐 token 对数概率 → 逐句 ppl，定位「选词过于可预测」的句子（选词分布层，ai_metric 构式层不覆盖）；gate-check `with_ppl=1` 可选开启，厂商不支持自动降级；阈值待朱雀分回填校准
- [x] **去AI味收敛回滚环 (tone_convergence)** — 检测 → 违规指令定向重写 → 复测 → 人味分不升自动回滚保留原稿；`POST /api/tone-converge` + 写作页「AI味收敛」按钮
- [x] **字数超标压缩** — `POST /api/condense` + 写作页「压缩超标」按钮（超目标 1.3 倍触发，与「不足续写」对偶成字数双向保障）

### 协同与一致性
- [x] **大纲失配标记** — `chapters.outline_hash` 记录生成正文时的大纲指纹（Web/MCP 双入口打点），改纲后 `outline_stale()` 失配、双页徽标提示
- [x] **锚例反向提取** — 人工版本审批时提取文风锚例候选（含对话段落优先），前端确认入库
- [x] **抽取待确认队列** — `PendingExtraction` 表 + truths/extract `queue=1` 模式，错抽不落真源
- [x] **测试** — 149 个用例全过（本版净增 41：雷达 9 / 快赢 12 / 协同 13 / V3.6 修复 7）

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
| CSS | 自定义 "朱金 · 玄漆" 主题（夜幕 + 宣纸稿纸面）+ 响应式；Three.js 环境月夜层 |
| MCP | `mcp` Python SDK |
| 认证 | Flask Session (Cookie-based) |

---

## 项目指标

| 项目 | 数量 |
|------|------|
| 数据库模型 | 23 |
| Flask Blueprint | 22 (含 6 个服务蓝图) |
| 路由模块 | 16 |
| 业务服务 | 12 + 通用 HTTP 客户端 |
| MCP 工具 | 27 |
| CLI 命令组 | 27 |
| 禁用模式 (De-AI) | 120+ (8 大类) |
| 双盲审角色 | 2（阎浮/白骨，追读-弃稿判决） |
| Agent 类型 | 16 |
| 短篇创作模式 | 3 |
| 大纲模板 | 4 |
| 角色模板 | 6 |
| 导出格式 | 5 (TXT/DOCX/MD/HTML/EPUB) |
| 综合评分 | 9.0/10 |

---

## V4.0 - 未来规划

### Agent 协同编排 (2026-09) ✅
- [x] 统一意见 Schema + rewrite 按勾选注入合并意见（P1，`opinions.py`）
- [x] 一致性链：确定性交叉核对（时序回潮/伏笔排期/复现）+ Keepers 复活为裁决者 + 抽取待确认队列（P2，`consistency_check.py` + `PendingExtraction`）
- [x] chapter_runner 编排器：写作链自动化到人工闸门 + MCP `run_chapter_pipeline`（P3，`writer_chain.py` 公共层）
- [x] 写作包契约 + 风格备忘录（B3）+ 创作偏好档案设置卡（P4）
- [ ] 观察项：长篇场景节拍生成、评分收敛环
- 完整设计见 [Agent 协同方案](agent-collaboration.md)

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