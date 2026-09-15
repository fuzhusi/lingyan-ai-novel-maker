# 灵砚 — AI 小说创作系统 实现状态

> **更新于 2026-09-12** - V1.0 ~ V3.8 全部完成，V4.0 规划中（Agent 协同 P1-P4 已实施）

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
- [x] **测试** — 149 个用例全过（test_compass_budget.py 20；test_perplexity_radar.py 9；test_merge_writes.py 12；test_agent_collab.py 14；CLI code review 修复后全量回归）

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
- [x] **测试** — 151 个用例全过（本版：CLI code review 20 项修复全量回归 + Agent 协同 P1-P4 各链路 smoke，全绿）

---

## V3.8 - 拆书复刻 (2026-09-12) ✅

> 借鉴模块改造为工业化拆书流水线；旧版风格模仿/情节借鉴/三档洗稿下线（由拆书复刻覆盖）。
> 方案调研：NovelForge 三级压缩管线、qidian 开篇拆解 schema、jarvis-write 待确认入库、ProseForge 审改批准。

### 拆书管线
- [x] **六维拆解** — 开篇节奏（first_200/500/1000 字 + hook + 节奏链）/ 金手指（规则/成长线/爽点枚举）/ 整体架构（阶段/关键事件/转折）/ 人物（多条结构化）/ 世界观（多条）/ 文风；提示词强制「可迁移方法」，拆解导向复刻
- [x] **整本拆 + 摘要压缩** — 超长源文本（>2万字）先逐章切分 + LLM 摘要压缩（400-600字/章）再拆解，解决长文超上下文
- [x] **拆解 JSON 稳健解析** — 明文/代码围栏/尾部杂音均兜底，失败明确报错

### 待确认采纳（错拆不污染知识库）
- [x] **DeconstructItem 待确认队列** — 人物/世界观/大纲各条先进队列，逐条编辑「采纳/丢弃」，与 PendingExtraction 同思路
- [x] **修改机制** — 采纳可携带用户修改稿（modified_content），复刻生成时统一落库并回填 target_id
- [x] **复刻为长篇** — 建/选小说 + 创作罗盘注入 + 已采纳条目写角色库/世界观/大纲树（卷/章两级）+ 章节建连，可选串行跑章节流水线（门禁+AI味收敛）
- [x] **复刻为短篇** — 建短篇 + 策划字段（角色/设定/主题）+ 大纲节点，接入短篇工坊逐节点生成

### 入口
- [x] Web 拆书工作台（`/plagiarize/`：任务列表/新建上传/工作台流式拆解/条目编辑采纳/生成弹窗）
- [x] CLI `deconstruct` 命令组（create/run/show/items/adopt/discard/adopt-all/generate-long/--run/generate-short/delete）
- [x] MCP 6 个新工具（deconstruct_book/list_deconstruct_tasks/get_deconstruct_task/list_deconstruct_items/adopt_deconstruct_item/generate_from_blueprint）

### 测试与文档
- [x] `tests/test_deconstruct.py` 16 例（解析/切分/报告/采纳/拆解路由/复刻接线）+ 全量回归 167 例全绿
- [x] README 功能特性/页面/CLI/MCP 清单同步；本文件 V3.8 记录

### P0 强化（2026-09-12 流程审核后）
> 独立流程审核发现三处关键断点（拆了不生成/承诺不兑现/长书拆不准），全部修复：

- [x] **三层漏斗拆解管线** — L0 开篇精读（前2章原文直拆节奏/文风/金手指，摘要还原不了的证据给真原文）+ L1 逐章摘要（上限 600 章、逐章落库断点续跑、截断显式警告）+ L2 卷级归并（每 50 章归并一条卷级摘要，全量信息进入全局拆解，消灭 3 万字符静默截断）+ L3 全局拆解（卷级摘要+开篇结论 → 全书架构/人物/世界观/金手指成长线）；短书（≤2万字）快路单次直拆
- [x] **节奏/文风注入生成链** — 修复 `apply_blueprint_long` 死参数：开篇钩子/节奏特征/节奏手法/文风基调与手法经创作罗盘 author_intent 注入 writer/outline/review 三链（上下文压缩永不裁），带 480 字预算
- [x] **微创新指令兑现注入** — 长篇：罗盘 author_intent 带「微创新方向（必须执行）」+ run=1 时作为 user_directive 下传章节流水线（Web/CLI/MCP 三入口）；短篇：写入 extra_instructions
- [x] **拆解产物合并策略** — L0 拥有节奏/文风/金手指，L3 拥有架构，人物/世界观两边合并去重（开篇优先），金手指成长线用 L3 全书视角覆盖
- [x] **摘要提速（调研 NovelForge/LangChain 生态后落地）** — 逐章串行 → **合批（4 章/次）× 线程池并发（8）× 模型分级**（摘要/归并走 summary agent=fast 挡，L0/L3 拆解仍用 audit=deep 挡）；工作线程纯 LLM 调用无 DB 访问；批完成即落库断点续跑；单章失败截断兜底不炸批；chapter_no 串号防护。500 章书预估从 30-60 分钟 → 3-5 分钟
- [x] **AI 差异化改写（v2，调研 jarvis-write/Maliang/affweb 后落地）** — 保功能换皮肉：条目卡「AI 改写」（改写稿进修改稿人工签字）+ 侧边栏「AI 全部改写」**成套一致性**（先出全员改名映射表 + 差异轴，关系不断线）；提示词带保真边界（❗保留定位/弧光/节奏钩子 vs 必换专名/情节，"仅改名不算改写"）+ 上下文卫生（原书名不进 prompt）；确定性校验 advisory：同名未换 ⚠ 标、伏笔/阶段锚点被改 ⚠ 标；「还原原稿」一键撤销
- [x] **落库时间轴第一期（调研报告 §5.4）** — L3 拆解增产：伏笔候选（5-20 条，埋/收**锚定关键事件**）+ 人物生命周期计划（首现/退场事件 + 退场方式）；新 `kind="foreshadow"` 条目进待确认队列（支持 AI 改写：描述换皮、锚点保留）；落库确定性换算：**事件名 → 章节号查表** → Foreshadowing 双锚点（earliest 不可提前收 + expected 预期收，jarvis-write 语义）+ Character.status_json.plan；锚点未建章降级 null + 警告（StoryForge"不瞎猜"纪律）；采纳改合并语义（表单不可见的锚点键从现稿保留）
- [x] 测试扩至 70 例（改写/映射表/同名校验/伏笔换算/计划落库/孤儿清理），全量 216 例全绿

### 系统审查修复(2026-09-14,产品×技术双视角审查后全量落地)

**技术 P0 全清**:
- [x] P0-1 `run.py` debug=True 回归(RCE 面)——修复并接线;生产形态改 waitress(多线程 WSGI)
- [x] P0-2 LLM 层瞬态错误重试(指数退避+429 Retry-After;流式仅未吐字前重试)+ 摘要/归并兜底文本打 fallback 标记,续跑自动重做
- [x] P0-3 长任务执行器:LongTask 表+后台线程+进度落库+`GET /plagiarize/long-tasks/<id>` 轮询;启动时僵尸 running 置可重试失败态;拆书/复刻生成/批量改写三链路脱离 HTTP 请求生命周期
- [x] P0-4 迁移版本化:schema_migrations 表(旧库引导宽松、新迁移失败即抛,不再吞错)
- [x] P0-5 **PRAGMA foreign_keys=ON**(全库首次真开)+ Novel 级联关系补全 + 孤儿一次性清理迁移 + 删除单一真源 `delete_service`(Web/MCP/CLI 三入口收敛,补齐 BlindReview/PendingExtraction 漏删)
- [x] P0-6 拆书认领改原子 UPDATE+WHERE,双标签页竞窗消除;LongTask has_running 二级守卫

**P1**:上传 zip 解压比/总量防护(DOCX/EPUB 解压炸弹);author_intent 注入式语句清洗 + 拆书报告来源声明;writer_chain 9 段 try/pass → logger.warning;审批后 FTS 增量索引;**LLM 调用计量表 llm_calls**(`cli.py llm usage --days N` 汇总次数/成功率/字符量/耗时);busy_timeout 10s;CI 加 ruff 门禁(E9/F)

**产品快赢五件套**:网关「拆书复刻」主推卡 + 模型配置三态检测引导(第0步/补勾选/推荐路径);「全部采纳」差异化门槛(微创新为空强确认);人味分分档行动建议(≥75 良好/≥60 建议收敛/<60 不投稿);拆书页合规提示条(⚖ 边界声明)

> 未尽事项(功能级,非修复):投稿包/发布前自检、多本连载看板、题材配方库、人味分校准、粒度 prompt 版本化——见 [系统审查报告](系统审查报告-2026-09.md) 战略押注节

### 生成上下文经济化(2026-09-14,档0+档1 落地;调研见 [上下文注入调研](上下文注入调研.md))

- [x] **档0 纯排序** — `build_node_prompt` 四层重排:全站静态(规则/技巧/体裁/文风指纹/锚例)→system;篇级静态(角色筛选后/场景/主题/概念/**静态大纲**)→user 前;节点卡+前文+**tone_inst(移出 system)**+写作指令→user 尾。去掉大纲行 ✓/★/○ 动态标记——前缀逐字节稳定才能命中 DeepSeek 前缀缓存(命中价 1/30~1/50,此前动态标记夹中间命中率≈0);"指令放尾部"同时是注意力最佳实践
- [x] **档1 联合筛选** — 大纲 Agent 增产每节点 `entities` 出场名单(零额外调用);角色设定按**全书大纲联合**筛选(`### 分节解析`,首节常驻兜底,全书未提及不注入)——集合对同篇所有节点一致,前缀稳定;无结构整块回退
- [x] 测试 224 例(排序/无标记/静态前缀跨节点一致/tone 位置/选择器/entities 保留)
- [x] **档2+计划值接入(2026-09-14 完成)** — 新服务 `narrative_plan.py`:①计划解析(人物 plan 事件锚→章节号,幂等);②**写作包计划块注入**(writer_chain→writer prompt 硬约束区):must_payoff 伏笔(预期回收章==本章,≤2条,含写法指导)+悬挂提醒(≤5)+**禁埋令**(容量 max(2,目标章数//20*3))+本章登场/退场角色(人物也要回收);③**死人复活确定性检查**(退场章后名字命中即 advisory 报告,零 LLM,保存版本时触发)——拆书蓝图自此真正进入每一次生成的上下文

### 生成期差异化与防雷同(2026-09-15,调研 jarvis-write/ASP 论文/知网标准后落地)

- [x] **差异化红线注入** — `narrative_plan.build_plan_block` 对拆书来源的本书注入「原创性红线」:R1 节拍只定功能不定做法(具体形态必须自创)/ R2 禁来源专名 / R3 禁梗概式复述;原创细节配额(≥3 处「拔掉会心疼」)+ 切入角置换 + 矫枉过正校准;**差异轴**持久化(`axes_text` 列,批量改写时生成)随红线注入全篇基调——约束少而硬(3 红线 + 1 配额 + 1 置换,ASP 论文:堆软约束反而劣化)
- [x] **雷同检测服务**(`similarity_check.py`,零 LLM) — 生成章 vs 对标书逐章摘要:**8-gram containment**(生成侧分母,"短抄长"方向性)+ **13 字连续红线**(知网标准,≥20 字高危);结果分 pass/warn/alarm 三级,**advisory 不拦截**
- [x] **触发式重生** — generate_long 逐章检测,alarm 时自动带整改清单(红线片段)重生一次,雷同度下降则保留新稿,未降则提示人工;`check_chapter_vs_blueprint` 可独立调用供流水线/CLI 复用
- [x] 测试 241 例(逐字抄→alarm+红线/同节拍异皮肉→pass/containment 方向性/红线合并/entities 联合筛选/差异轴持久化/红线块注入),全量 241 例全绿

### 双视角审查修复(2026-09-15,技术总监+网文写手并行审查后落地)

- [x] **R1 矛盾消解** — DIFF_REDLINE R1 改为「大纲节拍必须执行;具体承载方式必须自创」,消除「大纲说用A、红线说别用A」的自相矛盾指令
- [x] **切入角减频** — 从每章强制改为「不强制，视节奏自然选用」(写手:中段70%就该直入事件，花活开局是开篇/转折章特权)
- [x] **yield 消息去黑话** — 「红线命中」→「连续13字相同」、「跨档」→「雷同度从X%降至Y%」、全部带章号
- [x] **长书检测源** — `check_chapter_vs_blueprint` 无摘要时回退 source_text(技术:长书摘要路径 13 字红线不可命中→补原文对比);此前已在快路回退,此处是路由级确认
- [x] 测试 252 例(模板回归锁/资源库/语义检索/雷同检测/差异化红线)

### 语义检索层（2026-09-15，长篇知识库"按需解锁"架构）

- [x] **EntityEmbedding 统一嵌入表** — `entity_embeddings`(novel_id + entity_type + entity_id 唯一索引 + content_hash + embedding BLOB)；角色/世界观/伏笔/章节摘要四类实体统一入索引
- [x] **semantic_service.py** — 批量嵌入(`embed_novel_entities`)+ 语义检索(`search_relevant`)+ 写作包精选(`select_relevant_entities`: 返回相关 character_ids/world_ids 供精准注入替代全量塞)
- [x] **writer_chain 语义选角色/设定** — 全量注入后按语义相似度过滤，只保留 top-5 相关实体（降级回退全量）
- [x] **自我重复检测** — `similarity_check.check_self_repetition`: 生成章 vs 自己前 2 章 13 字红线，防 AI 口头禅跨章复用
- [x] **测试 263 例全绿**(新增语义检索测试 5 例)

### 写手二次测试修复(2026-09-15)
> 网文写手人设二次测试发现三个断链 + 阈值/判据问题,全部修复:

- [x] **金手指规则/爽点注入写作包** — `narrative_plan._golden_finger_block` 从拆书 elements_json 提取金手指规则与爽点类型(≤8行),写手复审:"金手指是网文命根子,拆了要接上"
- [x] **快路雷同检测回退** — 短书(≤2万字)无逐章摘要时,`check_chapter_vs_blueprint` 回退用 source_text 全文做对比源(此前静默跳过,写手:"测试期都用短书,会得出检测没用的错误结论")
- [x] **重生保留判据改跨档制** — alarm→alarm 不可保留(旧:`pct2<pct` 保留 18.4%→17.6% 仍在 alarm 区间);alarm→warn/pass 才保留新稿,否则标记待人工审阅
- [x] 测试 250 例(快路回退/跨档保留/金手指注入/红线块/差异轴)
- [ ] 第二版待办：多书元素库组合（4书×4要素）、金手指/节奏/文风蓝图卡进确认队列、专名合规防护、"复刻像不像"节奏 rubric 复审、Web 一键全自动

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
| 数据库模型 | 24 |
| Flask Blueprint | 25 (含 5 个服务蓝图) |
| 路由模块 | 20 |
| 业务服务 | 25 个模块 (含 __init__ 共 26 个 .py) |
| MCP 工具 | 33 |
| CLI 命令组 | 28 |
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