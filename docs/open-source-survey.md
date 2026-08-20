# AI 小说生成系统 — 开源项目调研报告

> 调研时间：2026-06-07
> 调研范围：GitHub 开源项目、Agent 框架、记忆管理方案、质量控制系统
> 调研目标：为「灵砚」系统的后续迭代提供技术参考

---

## 一、调研概览

共调研 **45 个开源项目**，覆盖 7 个类别：

| 类别 | 数量 | 代表项目 |
|------|------|----------|
| AI 小说写作系统 | 9 | InkOS, AI-Novel-Writing-Assistant, RecurrentGPT |
| 多 Agent 写作框架 | 13 | show-me-the-story, Dramatica-Flow, knowrite |
| 长文本生成研究 | 3 | Recurrent-LLM, chunk_wise_data_synthesis |
| 记忆/上下文管理 | 4 | Agent_Memory_Techniques, Smallville |
| 质量控制系统 | 4 | Novel-Consistency-Checking-System |
| 特色/创新项目 | 8 | Novel-Claude, ElyHa, Web_Novel_OS |
| 通用 Agent 框架 | 3 | MetaGPT, ChatDev, OpenAI Swarm |

---

## 二、Top 15 最具影响力项目

| 排名 | 项目 | Stars | 核心差异点 | 技术栈 |
|------|------|-------|-----------|--------|
| 1 | **InkOS** | 7,402 | 最完整系统：长/短/互动/封面，Studio/TUI/CLI | TypeScript |
| 2 | **AI-Writer** | 3,770 | RWKV 自定义架构，中文网文专用 | Python, RWKV |
| 3 | **AI-Novel-Writing-Assistant** | 1,686 | 全流程生产线 + AI 导演模式 | TypeScript, React, LangChain |
| 4 | **Terminal Velocity** | 1,104 | 10 Agent 自主协作写小说 | Python |
| 5 | **RecurrentGPT** | 999 | 循环记忆机制，任意长度文本 | Python |
| 6 | **ainovel-cli** | 664 | Go 高性能 CLI | Go |
| 7 | **kimi-writer** | 572 | 推理模型驱动 | Python, Kimi K2 |
| 8 | **AI_Gen_Novel** | 419 | 多 Agent 边界探索 | Python |
| 9 | **WenShape** | 390 | 深度上下文感知 | Python, RAG |
| 10 | **NovelClaw** | 327 | 可检查的动态记忆工作区 | Python, FastAPI |
| 11 | **gemini-writer** | 280 | Gemini 驱动 | Python |
| 12 | **awesome-novel-skill** | 260 | 可复用 Skill 集合 | Claude Code Skills |
| 13 | **show-me-the-story** | 178 | 单二进制，伏笔生命周期 | Go, Svelte |
| 14 | **Dramatica-Flow** | 169 | Dramatica 叙事理论 + 因果链 | Python, FastAPI |
| 15 | **knowrite** | 16 | 时间真相库 + 指纹风格 + 5D 评分 | Node.js, SQLite |

---

## 三、核心架构模式分析

### 3.1 记忆管理（7 种模式）

| 模式 | 代表项目 | 原理 | 适用场景 |
|------|----------|------|----------|
| **RAG + 向量库** | AI-Novel-Writing-Assistant, WenShape | Qdrant/Pinecone 语义检索 | 最通用，适合大多数项目 |
| **循环记忆** | RecurrentGPT | 滚动记忆缓冲 + 大纲，每步更新 | 学术研究，任意长度 |
| **三层记忆** | Morpheus | 短/中/长期记忆分层 | 需要精细记忆控制 |
| **时间真相库** | knowrite | 追踪每个时间点的"真相" | 长篇连载，防止矛盾 |
| **保护/可压缩** | InkOS | 关键事实不可压缩，次要信息可压缩 | 资源受限场景 |
| **世界状态快照** | Dramatica-Flow | 每章保存完整世界状态 | 需要回滚/审计 |
| **向量 + 知识图谱** | rag-story-agent | 混合检索，更丰富的关联 | 复杂人物关系 |

**灵砚现状（2026-07 更新）**：已实现向量记忆 (FTS5)、因果链、信息边界、时序真理库。详见 [第八节](#八灵砚借鉴实现情况-2026-07-更新)。

### 3.2 一致性保障（6 种模式）

| 模式 | 代表项目 | 原理 |
|------|----------|------|
| **因果链引擎** | Dramatica-Flow | 每个事件必须有 因→事→果→策 |
| **信息边界系统** | Dramatica-Flow | 角色只知道亲历/听闻/推断的事 |
| **伏笔生命周期** | show-me-the-story, Dramatica-Flow | 埋设→推进→回收 + 超时告警 |
| **章节事实检查** | show-me-the-story, knowrite | 每章自动一致性校验 |
| **设定协调** | show-me-the-story | 修改设定后自动与已写内容协调 |
| **角色一致性检查** | Character-Consistency-Checker | 检测 + 自动修复 OOC |

**灵砚现状（2026-07 更新）**：已实现因果链引擎和信息边界系统。详见 [第八节](#八灵砚借鉴实现情况-2026-07-更新)。

### 3.3 质量控制（5 种模式）

| 模式 | 代表项目 | 原理 |
|------|----------|------|
| **多 Agent 接力** | knowrite | Writer→Editor→Humanizer→Proofreader→Reader→Summarizer |
| **5D 适应度评分** | knowrite | 字数/重复/评审/读者反馈/综合 五维量化 |
| **去 AI 化** | show-me-the-story, knowrite | 23 种禁用模式 + 高频陈词替换 + 口语化改写 |
| **三层审计** | Dramatica-Flow | 规则校验→叙事审计→修订循环 |
| **全书优化** | show-me-the-story | 完成后诊断→一致性检查→自动修订→diff 查看 |

**灵砚现状（2026-07 更新）**：已实现去 AI 化 (120+ 模式) 和全书优化器。详见 [第八节](#八灵砚借鉴实现情况-2026-07-更新)。

### 3.4 风格控制（4 种模式）

| 模式 | 代表项目 | 原理 |
|------|----------|------|
| **写作方法引擎** | AI-Novel-Writing-Assistant | 从样本提取风格特征，存储复用 |
| **作者指纹** | knowrite | 捕获并强制执行写作风格 |
| **风格 RAG** | AI_Gen_Novel_Style_RAG | 专用 RAG 系统学习风格 |
| **Skill 系统** | show-me-the-story, InkOS | 模块化写作技巧插件 |

**灵砚现状（2026-07 更新）**：已实现风格指纹和 Skill 系统 (7 内置 + 自定义)。详见 [第八节](#八灵砚借鉴实现情况-2026-07-更新)。

---

## 四、灵砚 vs 竞品对比

> 更新时间：2026-07

| 功能维度 | 灵砚 | InkOS | show-me-the-story | Dramatica-Flow | knowrite |
|----------|------|-------|-------------------|----------------|----------|
| **多 Agent 流水线** | ✅ Writer+Critic+4Keeper+Editor | ✅ 8 Agent | ✅ 写→审→查 | ✅ 5 层 Agent | ✅ 7 Agent 接力 |
| **17+ 维审计** | ✅ 17 维度（5 分组） | ✅ 33 维度 | ✅ 事实检查 | ✅ 三层审计 | ✅ 5D 评分 |
| **伏笔系统** | ✅ 状态机+超时+重要度 | ✅ | ✅ 生命周期 | ✅ 生命周期 | ❌ |
| **故事状态引擎** | ✅ 阶段推进+快照 | ✅ | ❌ | ✅ 世界快照 | ❌ |
| **角色关系** | ✅ 5 维度量化 | ✅ | ✅ | ✅ 自动更新 | ❌ |
| **因果链** | ✅ cause→event→effect | ❌ | ❌ | ✅ | ❌ |
| **信息边界** | ✅ 亲眼/听闻/推断 | ❌ | ❌ | ✅ | ❌ |
| **向量记忆** | ✅ SQLite FTS5 | ✅ SQLite | ❌ | ❌ | ✅ SQLite 向量 |
| **去 AI 化** | ✅ 120+ 模式（8 类） | ✅ | ✅ 23 种模式 | ❌ | ✅ |
| **风格学习** | ✅ 风格指纹 | ✅ | ✅ Skill | ❌ | ✅ 指纹 |
| **Skill 系统** | ✅ 7 内置+自定义 | ✅ | ✅ | ❌ | ❌ |
| **时间真相库** | ✅ 章节+状态 | ❌ | ❌ | ❌ | ✅ |
| **全书优化** | ✅ 诊断+自动修订 | ❌ | ✅ | ❌ | ❌ |
| **Per-Agent 模型** | ✅ 16 种独立配置 | ❌ | ❌ | ❌ | ❌ |
| **短篇模式** | ✅ 3 模式 | ✅ | ❌ | ❌ | ❌ |
| **导出** | ✅ TXT/DOCX | ✅ 封面 | ❌ | ❌ | ❌ |
| **Web UI** | ✅ Flask | ✅ Studio | ✅ Svelte | ❌ | ❌ |
| **MCP 接口** | ✅ 26 工具 | ❌ | ❌ | ❌ | ❌ |
| **CLI 工具** | ✅ 15 命令组 | ✅ | ✅ | ❌ | ❌ |

### 灵砚核心优势

1. **唯一支持 Per-Agent 模型配置**：16 种 Agent 可独立配置模型/温度/Tokens，灵活的成本与质量权衡
2. **完整 MCP + CLI 双接口**：26 MCP 工具 + 15 CLI 命令组，AI 与自动化无缝集成
3. **去 AI 化最丰富**：120+ 禁用模式（8 大类），远超竞品 23 种
4. **17 维度审计 + 6 个并行 Agent**：比竞品更快更细

---

## 五、建议优先借鉴的功能

### P0 — 核心差距（应尽快实现）

| 功能 | 参考项目 | 实现难度 | 预期收益 |
|------|----------|----------|----------|
| **向量记忆** | InkOS, knowrite | 中 | 解决长期上下文遗忘 |
| **因果链引擎** | Dramatica-Flow | 中 | 情节逻辑自洽 |
| **去 AI 化 Agent** | show-me-the-story, knowrite | 低 | 显著提升文字质量 |
| **全书优化** | show-me-the-story | 中 | 完成后整体质量提升 |

### P1 — 重要增强

| 功能 | 参考项目 | 实现难度 | 预期收益 |
|------|----------|----------|----------|
| **信息边界系统** | Dramatica-Flow | 中 | 防止角色"全知" |
| **风格学习/指纹** | knowrite, AI-Novel-Writing-Assistant | 中 | 个性化风格 |
| **Skill 系统** | InkOS, show-me-the-story | 低 | 可扩展写作技巧 |
| **时间真相库** | knowrite | 中 | 防止时间线矛盾 |

### P2 — 架构优化

| 功能 | 参考项目 | 实现难度 | 预期收益 |
|------|----------|----------|----------|
| **三层记忆** | Morpheus | 高 | 更精细的记忆控制 |
| **可检查执行** | NovelClaw | 中 | 调试和审计透明化 |
| **全书 diff 查看** | show-me-the-story | 低 | 修订可视化 |
| **设定协调** | show-me-the-story | 中 | 修改设定后自动协调 |

---

## 六、关键代码库参考

| 需求 | 推荐参考 | 链接 |
|------|----------|------|
| 多 Agent 流水线 | InkOS | github.com/Narcooo/inkos |
| 伏笔生命周期 | show-me-the-story | github.com/Nigh/show-me-the-story |
| 因果链引擎 | Dramatica-Flow | github.com/ydsgangge-ux/dramatica-flow |
| 去 AI 化 | knowrite | github.com/knoai/knowrite |
| 向量记忆 | Agent_Memory_Techniques | github.com/NirDiamant/Agent_Memory_Techniques |
| 风格学习 | AI_Gen_Novel_Style_RAG | github.com/cs2764/AI_Gen_Novel_Style_RAG |
| Skill 系统 | awesome-novel-skill | github.com/modoojunko/awesome-novel-skill |
| 全书优化 | show-me-the-story | github.com/Nigh/show-me-the-story |
| 时间真相库 | knowrite | github.com/knoai/knowrite |
| 角色一致性 | Character-Consistency-Checker | github.com/wzd09801-pixel/novel-character-consistency-checker |

---

## 七、技术趋势总结

1. **多 Agent 是主流**：所有成熟项目都采用多 Agent 协作，单一 Agent 已被淘汰
2. **记忆是核心竞争力**：向量检索 + 结构化记忆 + 时间追踪 三位一体
3. **去 AI 化是刚需**：23 种禁用模式 + 高频词替换 + 口语化改写 已成标配
4. **伏笔生命周期**：埋设→推进→回收 的完整追踪是长篇小说的必备功能
5. **因果链是新方向**：Dramatica-Flow 的因果链引擎是最前沿的创新
6. **Skill 系统**：可插拔的写作技巧模块，让系统可扩展
7. **全书优化**：写完后的全局一致性检查 + 自动修订 是质量保障的最后一环

---

## 八、灵砚借鉴实现情况 (2026-07 更新)

调研中的功能已被灵砚实现的清单：

| 调研功能 | 灵砚实现 | 实现时间 | 实现位置 |
|---------|---------|---------|---------|
| 去 AI 化 (23 种) | ✅ 120+ 模式 (8 大类) | V2.0 | `app/services/deai_agent.py` |
| 多 Agent 流水线 | ✅ Writer + Critic + 4 Keepers + Editor | V2.0 | `app/routes/pipeline.py` |
| 17 维度审计 | ✅ 6 个并行 Agent | V2.0 | `app/services/audit.py` |
| 因果链引擎 | ✅ cause→event→effect→decision | V2.0 | `app/services/causal_chain.py` |
| 向量记忆 | ✅ SQLite FTS5 | V2.0 | `app/services/vector_memory.py` |
| 信息边界 | ✅ 亲眼/听闻/推断 | V2.0 | `app/services/info_boundary.py` |
| 风格学习 | ✅ 风格指纹 | V2.0 | `app/services/style_fingerprint.py` |
| Skill 系统 | ✅ 7 内置 + 自定义 | V2.0 | `app/services/skill_system.py` |
| 时间真相库 | ✅ 时序真理 | V2.0 | `app/services/temporal_truth.py` |
| 全书优化 | ✅ 诊断 + 自动修订 | V2.0 | `app/services/book_optimizer.py` |
| **Per-Agent 模型** | ✅ 16 种独立配置 | **V2.5** | `app/routes/settings.py` |
| **DeepSeek V4 适配** | ✅ V4 Pro/Flash | **V2.5** | 全局配置 |
| **用户认证** | ✅ Session + 全局鉴权 | **V3.0** | `app/services/auth.py` |
| **大纲模板** | ✅ 4 种标准结构 | **V3.0** | `app/services/outline_templates.py` |
| **角色模板** | ✅ 6 种预设 | **V3.0** | `app/routes/knowledge.py` |
| **多格式导出** | ✅ TXT/DOCX/MD/HTML/EPUB | **V3.0** | `app/routes/export.py` |
| **移动端适配** | ✅ 汉堡菜单 + 响应式 | **V3.0** | `base.html` |
| **草稿自动保存** | ✅ localStorage 10 秒 | **V3.0** | `write.html` |
| **新手引导** | ✅ 示例数据 + 引导卡片 | **V3.0** | `sample_data.py` |

### 调研但未实现的 (未来规划)

- 三层记忆 (Morpheus 启发) — 当前用 FTS5 简化
- 多用户协作 (NovelClaw 启发) — V4.0 规划
- 设定协调 (show-me-the-story 启发) — V4.0 规划
- 语音输入 — V4.0 规划

### 灵砚独有创新

| 功能 | 描述 |
|------|------|
| **Per-Agent 模型配置** | 16 种 Agent 可独立配置模型/温度/tokens，灵活的成本与质量权衡 |
| **一键推荐配置** | 一键应用 16 种 Agent 的最佳实践配置 |
| **三级配置优先级** | Agent 特定 > 小说覆盖 > 全局配置 |
| **CLI + Web 统一认证** | Session 状态文件 `~/.lingyan_cli_auth.json` |
| **多格式导出** | 5 种格式 (TXT/DOCX/MD/HTML/EPUB) |
| **模板库** | 4 种大纲模板 + 6 种角色模板 |
| **草稿自动保存** | localStorage + 10 秒间隔 + 恢复横幅 |
| **仪表盘可视化** | 字数趋势 SVG + 超时伏笔警告 |
