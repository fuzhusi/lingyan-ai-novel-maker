# 灵砚 — AI 小说创作系统 V3.0 技术设计文档

> **更新于 2026-08-20** - 完整记录 V1.0 ~ V3.2 全部功能设计

## 项目名称

灵砚 (LingYan)

## 项目目标

打造一套具备长期记忆、人物管理、世界观管理、伏笔管理、多 Agent 协同创作能力、按 Agent 类型灵活配置模型、单用户免登录的 AI 小说生成平台。支持长篇和短篇创作。

## 版本演进

| 版本 | 时间 | 主要内容 |
|------|------|---------|
| V1.0 | 已完成 | 基础 CRUD + 流式生成 + 版本管理 |
| V2.0 | 已完成 | 多 Agent 流水线 + 一致性保障 |
| V3.5 | 已完成 | 双盲审两角色审评取代 17 维审计（services/blind_review.py） |
| V2.5 | 已完成 | Per-Agent 模型配置 + DeepSeek V4 适配 |
| V3.0 | 已完成 | 用户认证 + 模板库 + 多格式导出 + 移动端 + 草稿保存 |

---

# 1. 产品背景

当前主流大模型在长篇小说创作中存在以下问题：

- 上下文窗口有限
- 长期设定遗失
- 人物行为崩坏
- 世界观前后矛盾
- 伏笔无法自动回收
- AI 写作痕迹明显
- 后期剧情失控

本系统旨在解决上述问题。

---

# 2. 系统总体架构

## 2.1 分层架构

```text
┌─────────────────────────────────────────────────────────┐
│                    客户端层 (Client)                      │
│              Jinja2 + Vanilla JS + CSS                   │
│      "朱金 · 玄漆" 中式主题（夜幕下摊开的稿纸）          │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────────┐
│               应用服务层 (Flask Backend)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ Novel    │ │ Chapter  │ │ Agent    │ │ Knowledge  │ │
│  │ CRUD     │ │ CRUD     │ │ Pipeline │ │ Base       │ │
│  └──────────┘ └──────────┘ └─────┬────┘ └────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌─────┴────┐ ┌────────────┐ │
│  │ Short    │ │ Audit    │ │ Services │ │ MCP/CLI    │ │
│  │ Story    │ │ System   │ │ Layer    │ │ Interface  │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
└──────────────────────────────────┼──────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────┐
│               模型服务层 (Model Service)                   │
│         DeepSeek V4 (OpenAI 兼容 HTTP API)               │
│         SSE 流式传输                                       │
└──────────────────────────────────┬──────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────┐
│               数据存储层 (Storage)                        │
│  ┌────────────────┐ ┌──────────┐ ┌───────────────────┐ │
│  │ SQLite         │ │ FTS5     │ │ .env 配置          │ │
│  │ 主存储 (18表)   │ │ 全文检索  │ │ API Key/模型      │ │
│  └────────────────┘ └──────────┘ └───────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## 2.2 技术选型

| 层 | 技术 | 理由 |
|---|------|------|
| 语言 | Python 3.14 | 生态丰富，开发效率高 |
| Web 框架 | Flask | 轻量、灵活、app factory 模式 |
| ORM | Flask-SQLAlchemy | SQLAlchemy 生态完整 |
| 数据库 | SQLite | 单文件、零运维、FTS5 支持 |
| AI 接口 | DeepSeek V4 | OpenAI 兼容协议、中文能力强 |
| 流式传输 | SSE (Server-Sent Events) | 浏览器原生支持、实现简单 |
| HTTP 客户端 | httpx | 支持流式响应 |
| 前端 | Jinja2 + Vanilla JS | 零依赖、快速迭代 |
| MCP | mcp Python SDK | AI IDE 集成 |

---

# 3. 功能模块设计

## 3.1 网关系统

入口页面，选择创作模式：

- **长篇创作** — 多章节架构、人物管理、伏笔追踪、多 Agent 协作
- **短篇创作** — 灵感驱动、双 Agent 协作、一次成文

## 3.2 长篇系统

### 书架

- 创建/删除小说
- 类型、简介、世界观设定

### 章节管理

- 多版本支持（AI/人工同权）
- 大纲树（卷 → 章 → 幕）
- 版本对比 (diff)

### 知识库

- 人物卡片（性格、说话风格、背景、动机、弧光）
- 世界观设定（按分类：地图/势力/规则/时间线）
- 伏笔管理（状态机 + 超时检测）
- 大纲树（三级结构）


### 3.2.1 长篇上下文注入（相关性驱动）

章节生成时按相关性注入上下文（`assemble_chapter_context`），而非全量堆砌：

- **出场角色勾选**：写作页勾选本章登场角色，只注入这些角色档案；`character_ids` 表单参数
- **上章结尾原文**：上一章最新版本正文末尾 ~800 字（衔接文风与钩子）
- **分层记忆**：近 3 章详细摘要 → 更早章节合并压缩概要（>600 字截断），不随章节数线性膨胀
- **摘要兜底**：无 `ChapterSummary` 的章节自动截取正文开头 300 字做粗摘要

注入顺序：约束(system) > 小说信息 > 大纲树 > 世界观 > 出场角色 > 上一章结尾 > 近章摘要 > 远章概要 > 伏笔 > 因果链 > 记忆 > 本章大纲 > 特别指示。

## 3.3 短篇系统

三种创作模式：

| 模式 | 流程 | 适用场景 |
|------|------|----------|
| 灵感模式 | 3+1 阶段策划（角色设计→剧情大纲→主题定调→逐节点创作） | 灵光一闪 |
| 设定模式 | 已有设定基础上走同一 3+1 阶段流程 | 有明确构思 |
| 细心模式 | 详细设定 → AI 单轮精心生成（不变） | 追求质量 |

**3+1 阶段策划**（灵感/设定模式共用）：

1. **角色设计** `POST /short/<id>/plan-characters` → `plan_characters`（纯文本，可编辑）
2. **剧情大纲** `POST /short/<id>/expand` → `concept` + `outline_nodes`（JSON 节点树）
3. **主题定调** `POST /short/<id>/plan-theme` → `plan_theme`（纯文本，可编辑，可跳过）
4. **故事创作** `POST /short/<id>/write-from-concept` → 逐节点多轮生成正文

每阶段产出可编辑（`POST /short/<id>/save-plan`），确认后解锁下一阶段。

**逐节点多轮生成**：

- 节点数 = 目标字数 / 1100（向上取整），单节点 800-1500 字
- 每个节点独立 `content` 存于 `outline_nodes` JSON，注入角色档案+大纲+主题+前文
- 断点恢复：每完成一个节点持久化，暂停后从第一个 pending 续写
- 单节点重写：`POST /short/<id>/node/<node_id>/rewrite` 只重生指定节点
- 根据评审重写：多轮逐节点二次生成（评审意见+前文+节点原内容孤立重写每节点）
- 局部编辑：续写 / 扩写选中 / 重写选中（编辑模式内流式变换）

短篇也支持版本管理、双盲审集成评审、导出。

## 3.4 人物关系系统

5 维度量化关系：

| 维度 | 说明 | 默认值 |
|------|------|--------|
| trust (信任度) | 对对方的信任程度 | 50 |
| affection (好感度) | 情感好感 | 50 |
| respect (尊重度) | 对方能力/地位的认可 | 50 |
| fear (畏惧度) | 对对方的恐惧程度 | 0 |
| dependency (依赖度) | 对对方的依赖程度 | 50 |

综合关系分：`overall = trust×0.3 + affection×0.25 + respect×0.2 + (100-fear)×0.15 + dependency×0.1`

关系类型自动判定：恋人/挚友、好友、畏惧/仇恨、依赖/师徒、敌对、普通。

关系事件系统：共同战斗、背叛行为、救命之恩等自动调整分数。

## 3.5 伏笔系统

状态机：

```text
planned → buried → advancing → reclaimable → resolved
任意状态 → abandoned
```

超时检测：

| 重要等级 | 超时阈值 |
|----------|----------|
| critical (9-10) | 30 章 |
| important (7-8) | 20 章 |
| normal (4-6) | 15 章 |
| minor (1-3) | 10 章 |

## 3.6 故事状态引擎

维护全书状态：

- 主线：当前核心目标
- 支线：当前推进的支线
- 冲突：人物/势力/价值观冲突
- 高潮阶段：setup → development → climax → resolution
- 风险标记：战力崩坏、人物 OOC、世界观冲突

阶段自动推进：

| 阶段 | 触发条件 |
|------|----------|
| setup | 进度 < 20% |
| development | 进度 20%~60% |
| climax | 进度 60%~85% 或待回收伏笔 > 5 |
| resolution | 进度 > 85% 或所有冲突已解决 |

状态快照 + 回滚机制。

---

# 4. Agent 架构

## 4.1 多 Agent 流水线

```text
Writer → [Critic | Character Keeper | Lore Keeper | Foreshadow Keeper] → Editor
                ↑ 四个 Agent 并行执行，结果汇总后统一判断
```

## 4.2 Agent 职责

| Agent | 职责 | 检查内容 |
|-------|------|----------|
| Writer | 正文生成 | — |
| Critic | 综合评审 | 逻辑、节奏、爽点、人设 |
| Character Keeper | 角色一致性 | 性格、行为、成长轨迹 |
| Lore Keeper | 世界观一致性 | 地图、战力、规则 |
| Foreshadow Keeper | 伏笔管理 | 是否遗漏、是否需回收 |
| Editor | 最终润色 | 修复所有问题 |

## 4.3 双盲审（两角色审评体系，V3.5 取代 17 维审计）

两位「恶毒编辑」人格对正文做**零上下文盲审**（不给大纲设定，每条批评必须引用原文）：

| 编辑 | 视角 | 判决 |
|------|------|------|
| 尖酸嘴 · 阎浮 | 市场毒舌：钩子、灌水、跳段、AI 痕迹 | 追读 / 弃稿 |
| 白骨 · 文学审稿 | 文学刻薄：假情绪、假细节、套话腔、AI 腔 | 追读 / 弃稿 |

- 引擎 `app/services/blind_review.py`；工作台 `/blind/`（网关首页特性卡进入）；长/短篇写作页内嵌盲审入口
- API：`POST /api/blind-review/run`（kind=story/chapter/text）、`POST /api/blind-review/rewrite`（include_editors 可选过滤）、`GET /api/blind-review/latest`
- 持久化：独立 `blind_reviews` 表；综合评分沿用 critic 链路保证历史可比

## 4.4 短篇双 Agent

```text
灵感 → 发散 Agent (扩展构思) → 用户确认 → 创作 Agent (写故事)
```

---

# 5. 质量控制系统

## 5.1 去 AI 化 Agent

**5 步处理流程：**

1. **Banned pattern replacement** — 120+ 个 AI 高频词（仿佛→好像，眼中闪过→去掉），分 8 大类
2. **正则模式匹配** — 30+ 个句式规则（叠词、连接词、连续"的"等）
3. **Sentence rhythm fix** — 打破连续同句式开头，修剪长度差异过小的句子
4. **Colloquial polish** — 进行了→了，流露出→直接写（40+ 条规则）
5. **Paragraph flow** — 修复段落开头重复（而/但是/然而等）

**8 大类禁用模式：**
- 虚词/连接词（仿佛、宛如、犹如等）
- 情感/心理描写（不禁、不由得、恍然大悟等）
- 副词/修饰词（默默地、静静地、轻轻地等）
- 模式化描写（眼神、嘴角、心理等）
- 对话修饰（沉声道、轻声道、语气等）
- 过渡词/时间（与此同时、不一会儿、片刻之后等）
- 解释性开头（他知道、她明白、他意识到等）
- 成语/四字词（如释重负、如获至宝等）

## 5.2 写作约束系统

每个 prompt 模板可配置独立约束：

- 禁用词列表
- 句式规则（单句≤25字、每段≤5句）
- 叙事规则（用动作代替心理描写）
- 节奏控制（每500字至少一个感官细节）

## 5.3 风格指纹

从参考文本提取写作风格特征：

- 句式长度偏好
- 用词水平
- 叙事视角
- 对话风格
- 描写密度
- 情感表达方式
- 修辞手法
- 风格示例句

## 5.3.1 文风锚例 (Style Anchor)

真人原文直插 prompt 做风格锚定——一手 token 级质感，强于指纹描述的二手转译：

- **存储**：`Setting` 键 `style_anchor_text`（原文）+ `style_anchor_enabled`（开关 "1"/"0"）
- **格式化**：`format_anchor_for_prompt()` 按段落边界截断（上限 2000 字符），包装成「模仿叙事质感、只学文风勿抄情节」指令块；未启用/文本 <50 字返回空串
- **注入范围**（全部正文生成链路）：
  - 长篇：章节生成、聚焦生成、评审改写（`build_rewrite_prompt`）、Editor 润色（`build_editor_prompt`）
  - 短篇：逐节点生成（`build_node_prompt`）、旧路径续写/收尾、单节点重写、全文重写、AI 润色、评审逐节点/全文重写、续写、扩写选中、重写选中、分段生成
- **UI**：设置页「文风锚例」卡（粘贴 + 启用勾选）；短篇写作页工具栏「文风锚定」圆点开关（点亮=注入，熄灭=自由发挥，未设文本时引导跳设置页），两处开关同源
- **API**：`GET /api/style-anchor`（读）、`POST /api/style-anchor` `{text}`（存）、`POST /api/style-anchor/toggle` `{enabled}`（开关）
- **测试**：`tests/test_style_anchor.py`（7 个用例：存储/开关/格式化/段落边界截断/API）

## 5.4 Skill 系统

7 个内置写作技巧 + 自定义：

| Skill | 功能 |
|-------|------|
| 章节钩子 | 开头制造悬念 |
| 节奏控制 | 张弛有度 |
| 展示而非讲述 | 用动作代替描述 |
| 对话写实 | 自然对话 |
| 感官细节 | 增强画面感 |
| 伏笔编织 | 自然埋设伏笔 |
| 情感层次 | 丰富人物情感 |

---

# 6. 长期记忆系统

## 6.1 记忆层级

| 层级 | 存储 | 内容 |
|------|------|------|
| 章节级 | ChapterSummary | 200字摘要 + 因果链 |
| 场景级 | ChapterMemory.scenes | 100字/场景摘要 |
| 向量级 | SQLite FTS5 | 全文检索 |

## 6.2 因果链引擎

每个章节提取：因→事→果→策

- 起因(cause)：触发事件的原因
- 经过(event)：发生了什么
- 结果(effect)：产生了什么后果
- 决策(decision)：角色做出的关键决定

上一章的决策 = 下一章的起因，保证逻辑连贯。

## 6.3 信息边界系统

角色只知道他们亲历的事：

- 亲眼所见(witnessed)
- 被人告知(told)
- 推断得知(deduced)

防止"全知"污染。

## 6.4 时间真相库

追踪每个时间点的事实状态：

- 角色状态（alive/dead/missing）
- 关系变化
- 物品位置
- 势力变化

## 6.5 向量记忆

SQLite FTS5 全文检索，零外部依赖：

- 索引：章节摘要、角色、世界观、伏笔、场景
- 搜索：语义匹配 + 关键词召回
- 上下文组装：最近5章 + 语义搜索结果 + 活跃伏笔 + 信息边界 + 时间真相

---

# 7. 全书优化

写完后的全局质量保障：

1. **全书诊断** — 并行审计所有章节
2. **一致性检查** — 跨章节事实验证
3. **去 AI 化** — 批量清理 AI 痕迹
4. **自动修订** — 根据诊断结果修复问题

---

# 8. Prompt 中心

统一管理 Prompt 模板：

| 类型 | 用途 |
|------|------|
| writer | 正文生成 |
| critic | 综合评审 |
| summary | 章节摘要 |
| outline | 大纲生成 |
| rewrite | 改写 |
| character_check | 角色一致性检查 |
| lore_check | 世界观一致性检查 |
| foreshadow_check | 伏笔检查 |
| editor | 最终润色 |

每个模板可配置：

- 角色设定 (template_content)
- 写作约束 (constraints)
- 变量说明 (variable_help)

---

# 9. 数据库设计

## 9.1 表结构 (18 张表)

### 核心业务

```sql
-- 小说
CREATE TABLE novels (
    id INTEGER PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    genre VARCHAR(100) DEFAULT '',
    synopsis TEXT DEFAULT '',
    world_intro TEXT DEFAULT '',
    model_override TEXT DEFAULT '{}',
    created_at VARCHAR(20)
);

-- 章节
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    chapter_number INTEGER NOT NULL,
    title VARCHAR(200) DEFAULT '',
    outline TEXT DEFAULT '',
    user_directive TEXT DEFAULT '',
    outline_node_id INTEGER REFERENCES outline_nodes(id),
    created_at VARCHAR(20),
    UNIQUE(novel_id, chapter_number)
);

-- 章节版本
CREATE TABLE chapter_versions (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapters(id),
    version_number INTEGER NOT NULL,
    content TEXT DEFAULT '',
    source VARCHAR(10) DEFAULT 'ai',
    prompt_used TEXT DEFAULT '',
    model_params_json TEXT DEFAULT '{}',
    approved BOOLEAN DEFAULT 0,
    created_at VARCHAR(20),
    UNIQUE(chapter_id, version_number)
);

-- 章节摘要 + 因果链
CREATE TABLE chapter_summaries (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL UNIQUE REFERENCES chapters(id),
    summary TEXT DEFAULT '',
    causal_chain_json TEXT DEFAULT '',
    generated_at VARCHAR(20)
);
```

### 知识库

```sql
-- 角色
CREATE TABLE characters (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    name VARCHAR(100) NOT NULL,
    personality TEXT DEFAULT '',
    speaking_style TEXT DEFAULT '',
    appearance TEXT DEFAULT '',
    background TEXT DEFAULT '',
    motivation TEXT DEFAULT '',
    arc_direction TEXT DEFAULT '',
    status_json TEXT DEFAULT '{}',
    created_at VARCHAR(20),
    updated_at VARCHAR(20)
);

-- 角色关系
CREATE TABLE character_relations (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    character_a_id INTEGER NOT NULL REFERENCES characters(id),
    character_b_id INTEGER NOT NULL REFERENCES characters(id),
    relation_type VARCHAR(50) DEFAULT 'ordinary',
    description TEXT DEFAULT '',
    trust INTEGER DEFAULT 50,
    affection INTEGER DEFAULT 50,
    respect INTEGER DEFAULT 50,
    fear INTEGER DEFAULT 0,
    dependency INTEGER DEFAULT 50,
    status VARCHAR(20) DEFAULT 'active',
    start_chapter INTEGER,
    created_at VARCHAR(20),
    updated_at VARCHAR(20),
    UNIQUE(character_a_id, character_b_id)
);

-- 世界观设定
CREATE TABLE world_settings (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    category VARCHAR(100) DEFAULT '',
    title VARCHAR(200) NOT NULL,
    content TEXT DEFAULT '',
    created_at VARCHAR(20),
    updated_at VARCHAR(20)
);

-- 大纲节点
CREATE TABLE outline_nodes (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    parent_id INTEGER REFERENCES outline_nodes(id),
    sort_order INTEGER DEFAULT 0,
    node_type VARCHAR(20) DEFAULT 'chapter',
    title VARCHAR(200) DEFAULT '',
    summary TEXT DEFAULT '',
    created_at VARCHAR(20)
);

-- 伏笔
CREATE TABLE foreshadowing (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    title VARCHAR(200) DEFAULT '',
    description TEXT DEFAULT '',
    planted_chapter INTEGER,
    resolve_chapter INTEGER,
    status VARCHAR(20) DEFAULT 'open',
    importance INTEGER DEFAULT 5,
    last_mentioned_chapter INTEGER,
    timeout_threshold INTEGER DEFAULT 15,
    notes TEXT DEFAULT '',
    created_at VARCHAR(20)
);
```

### 高级功能

```sql
-- 故事状态
CREATE TABLE story_states (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL UNIQUE REFERENCES novels(id),
    main_quest TEXT DEFAULT '',
    main_quest_progress VARCHAR(50) DEFAULT '',
    active_subplots TEXT DEFAULT '[]',
    active_conflicts TEXT DEFAULT '[]',
    arc_phase VARCHAR(20) DEFAULT 'setup',
    arc_intensity INTEGER DEFAULT 3,
    risk_flags TEXT DEFAULT '{}',
    current_chapter INTEGER DEFAULT 0,
    updated_at VARCHAR(20)
);

-- 状态快照
CREATE TABLE story_state_snapshots (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    chapter_id INTEGER REFERENCES chapters(id),
    chapter_number INTEGER NOT NULL,
    state_json TEXT DEFAULT '{}',
    is_checkpoint BOOLEAN DEFAULT 0,
    created_at VARCHAR(20)
);

-- 章节记忆
CREATE TABLE chapter_memories (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    chapter_id INTEGER NOT NULL UNIQUE REFERENCES chapters(id),
    chapter_number INTEGER NOT NULL,
    summary TEXT DEFAULT '',
    key_events_json TEXT DEFAULT '[]',
    character_changes_json TEXT DEFAULT '{}',
    foreshadow_events_json TEXT DEFAULT '[]',
    new_characters_json TEXT DEFAULT '[]',
    scenes_json TEXT DEFAULT '[]',
    created_at VARCHAR(20)
);
```

### 短篇

```sql
-- 短篇
CREATE TABLE short_stories (
    id INTEGER PRIMARY KEY,
    title VARCHAR(200) DEFAULT '',
    mode VARCHAR(20) DEFAULT 'inspiration',
    inspiration TEXT DEFAULT '',
    genre VARCHAR(100) DEFAULT '',
    theme TEXT DEFAULT '',
    character_desc TEXT DEFAULT '',
    scene_desc TEXT DEFAULT '',
    tone VARCHAR(50) DEFAULT '',
    word_target INTEGER DEFAULT 2000,
    extra_instructions TEXT DEFAULT '',
    concept TEXT DEFAULT '',
    content TEXT DEFAULT '',
    status VARCHAR(20) DEFAULT 'draft',
    created_at VARCHAR(20),
    updated_at VARCHAR(20)
);

-- 短篇版本
CREATE TABLE short_story_versions (
    id INTEGER PRIMARY KEY,
    story_id INTEGER NOT NULL REFERENCES short_stories(id),
    version_number INTEGER NOT NULL,
    content TEXT DEFAULT '',
    source VARCHAR(10) DEFAULT 'ai',
    approved BOOLEAN DEFAULT 0,
    created_at VARCHAR(20),
    UNIQUE(story_id, version_number)
);

-- 短篇评审
CREATE TABLE short_story_reviews (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES short_story_versions(id),
    overall_score FLOAT,
    dimension_scores_json TEXT DEFAULT '[]',
    annotations_json TEXT DEFAULT '[]',
    overall_comment TEXT DEFAULT '',
    full_response TEXT DEFAULT '',
    user_feedback TEXT DEFAULT '',
    audit_json TEXT DEFAULT NULL,      -- 旧审计字段（V3.5 起不再写入，保留兼容）
    created_at VARCHAR(20)
);

### 双盲审记录

```sql
CREATE TABLE blind_reviews (
    id INTEGER PRIMARY KEY,
    kind VARCHAR(10) DEFAULT 'text',   -- story / chapter / text
    story_id INTEGER,                  -- kind=story 时引用 short_stories.id
    version_id INTEGER,                -- kind=chapter 时引用 chapter_versions.id
    title VARCHAR(200) DEFAULT '',
    word_count INTEGER DEFAULT 0,
    editors_json TEXT DEFAULT '[]',    -- [{key,name,verdict,review}]
    elapsed FLOAT DEFAULT 0.0,
    created_at VARCHAR(20)
);
```

### LLM 厂商配置

```sql
-- LLM 厂商
CREATE TABLE llm_providers (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    provider_type VARCHAR(50) DEFAULT 'deepseek',
    api_key TEXT DEFAULT '',
    base_url TEXT DEFAULT '',
    enabled BOOLEAN DEFAULT 1,
    created_at VARCHAR(20),
    updated_at VARCHAR(20)
);

-- LLM 模型（厂商下属）
CREATE TABLE llm_models (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES llm_providers(id),
    model_name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100) DEFAULT '',
    enabled BOOLEAN DEFAULT 0,
    created_at VARCHAR(20),
    updated_at VARCHAR(20)
);
```

### 系统

```sql
-- 评审记录
CREATE TABLE critic_reviews (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES chapter_versions(id),
    overall_score FLOAT,
    dimension_scores_json TEXT DEFAULT '[]',
    annotations_json TEXT DEFAULT '[]',
    overall_comment TEXT DEFAULT '',
    full_response TEXT DEFAULT '',
    user_feedback TEXT DEFAULT '',
    created_at VARCHAR(20)
);

-- 提示词模板
CREATE TABLE prompt_templates (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    template_type VARCHAR(20) DEFAULT 'writer',
    template_content TEXT DEFAULT '',
    constraints TEXT DEFAULT '',
    variable_help TEXT DEFAULT '',
    created_at VARCHAR(20),
    updated_at VARCHAR(20)
);

-- 系统设置
CREATE TABLE settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT DEFAULT ''
);
```

---

# 10. 技术栈

| 层 | 技术 |
|---|------|
| 语言 | Python 3.14 |
| Web 框架 | Flask |
| ORM | Flask-SQLAlchemy |
| 数据库 | SQLite + FTS5 |
| AI 接口 | DeepSeek V4 (OpenAI 兼容) |
| 流式传输 | SSE (Server-Sent Events) |
| HTTP 客户端 | httpx |
| 前端 | Jinja2 + Vanilla JS |
| 样式 | CSS 自定义属性 ("朱金 · 玄漆"，夜幕 + 稿纸面) + Three.js 环境月夜 |
| MCP | mcp Python SDK |
| CLI | argparse |

---

# 11. API 接口

## 11.1 长篇 API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 网关首页 |
| `/novel/` | GET | 长篇列表 |
| `/novel/create` | POST | 创建小说 |
| `/novel/<id>/delete` | POST | 删除小说 |
| `/novel/<id>/` | GET | 章节列表 |
| `/novel/<id>/chapter/<num>/write` | GET | 写作页 |
| `/novel/<id>/chapter/<num>/save-version` | POST | 保存版本 |
| `/api/generate-stream` | POST | SSE 生成章节 |
| `/api/outline-stream` | POST | SSE 生成大纲 |
| `/api/review-stream` | POST | SSE 评审 |
| `/api/rewrite-stream` | POST | SSE 改写 |
| `/api/review/save` | POST | 保存评审 |
| `/api/review/get` | GET | 获取评审 |
| `/api/review/feedback` | POST | 用户反馈 |
| `/api/approve` | POST | 审批 |
| `/api/diff` | GET | 版本对比 |
| `/api/pipeline/check` | POST | 多 Agent 检查 |
| `/api/pipeline/check-stream` | POST | 多 Agent 检查 (SSE) |
| `/api/blind-review/run` | POST | 双盲审（kind=story/chapter/text） |
| `/api/blind-review/rewrite` | POST | 盲审意见返还 Writer 生成第二稿 |
| `/api/blind-review/latest` | GET | 查询对象最近一次盲审 |
| `/api/novels/<id>/story-state` | GET/PUT | 故事状态 |
| `/api/novels/<id>/relations` | GET/POST | 角色关系 |
| `/api/novels/<id>/causal-chain/extract` | POST | 因果链提取 |
| `/api/novels/<id>/optimize/diagnose` | POST | 全书诊断 |
| `/api/novels/<id>/memory/search` | GET | 记忆搜索 |
| `/api/novels/<id>/truths` | GET/POST | 时间真相 |
| `/api/style/analyze` | POST | 风格分析 |
| `/api/style-anchor` | GET | 读取文风锚例（文本+开关状态） |
| `/api/style-anchor` | POST | 保存文风锚例 `{text}` |
| `/api/style-anchor/toggle` | POST | 文风锚例开关 `{enabled}` |
| `/api/skills` | GET | Skill 列表 |
| `/api/skills/gate-check` | POST | 质量门禁 + AI 痕迹检测 |

## 11.2 短篇 API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/short/` | GET | 短篇列表 |
| `/short/new` | GET | 新建短篇 |
| `/short/create` | POST | 创建短篇 |
| `/short/templates` | GET | 短篇结构模板 |
| `/short/<id>` | GET | 短篇写作页 |
| `/short/<id>/edit` | GET | 编辑页 |
| `/short/<id>/delete` | POST | 删除短篇 |
| **阶段策划** | | |
| `/short/<id>/plan-characters` | POST | 阶段1：角色设计 (SSE) |
| `/short/<id>/plan-theme` | POST | 阶段3：主题定调 (SSE) |
| `/short/<id>/expand` | POST | 阶段2：剧情大纲 (SSE) → JSON 大纲+节点树 |
| `/short/<id>/save-plan` | POST | 保存策划阶段可编辑内容 |
| `/short/<id>/save-concept` | POST | 保存大纲构思 |
| **逐节点创作** | | |
| `/short/<id>/write-from-concept` | POST | 逐节点多轮创作 (SSE) |
| `/short/<id>/nodes` | GET | 节点进度状态 |
| `/short/<id>/node/<node_id>/rewrite` | POST | 单节点重写 (SSE) |
| **直接生成（细心模式）** | | |
| `/short/<id>/generate` | POST | 直接生成 (SSE) |
| `/short/<id>/generate-section` | POST | 分段生成 (SSE) |
| **局部编辑（编辑模式内）** | | |
| `/short/<id>/continue` | POST | 续写 (SSE) |
| `/short/<id>/expand-selection` | POST | 扩写选中 (SSE) |
| `/short/<id>/rewrite-selection` | POST | 重写选中 (SSE) |
| `/short/<id>/rewrite` | POST | AI 润色全文 (SSE) |
| **评审 + 重写** | | |
| `/short/<id>/review` | POST | critic 结构化评审 |
| `/short/<id>/review/get` | GET | 获取评审结果 |
| `/short/<id>/review/feedback` | POST | 保存用户评审意见 |
| `/short/<id>/rewrite-with-feedback` | POST | 根据评审重写：逐节点二次生成 (SSE) |
| **版本管理** | | |
| `/short/<id>/save` | POST | 保存全文 |
| `/short/<id>/versions` | GET | 版本列表 |
| `/short/<id>/save-version` | POST | 保存版本 |
| `/short/<id>/version/<vid>` | GET | 版本详情 |
| `/short/<id>/version/<vid>/load` | POST | 载入版本 |
| `/short/<id>/version/<vid>/delete` | POST | 删除版本 |
| `/short/<id>/approve/<vid>` | POST | 审批版本 |
| **导出** | | |
| `/short/<id>/export/{txt,docx,md,html,epub}` | GET | 多格式导出 |

## 11.3 系统 API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/settings/` | GET | 设置页（含 Per-Agent 配置） |
| `/settings/save` | POST | 保存全局设置 |
| `/settings/save-agent` | POST | 保存 Per-Agent 配置 |
| `/settings/api/config` | GET | 获取配置 JSON |
| `/settings/api/apply-recommended` | POST | 一键应用推荐配置 |
| `/settings/api/clear-agent` | POST | 清除 Per-Agent 自定义 |
| `/settings/api/novel-model-override` | POST | 设置小说级覆盖 |
| `/prompt-templates/` | GET | 模板库 |
| `/prompt-templates/create` | POST | 创建模板 |

---

## 11.4 Per-Agent 模型配置

**三级配置优先级：**

```
Agent 特定配置 > 小说覆盖 (model_override) > 全局配置
```

**16 种 Agent 类型：**

| 类型 | 推荐模型 | 用途 |
|------|----------|------|
| writer | V4 Flash | 章节生成 |
| outline | V4 Flash | 大纲生成 |
| summary | V4 Flash | 摘要生成 |
| memory | V4 Flash | 章节记忆 |
| causal_chain | V4 Flash | 因果链 |
| temporal_truth | V4 Flash | 时序真理 |
| short_story | V4 Flash | 短篇生成 |
| critic | V4 Pro | 评审 |
| rewrite | V4 Pro | 改写 |
| character_check | V4 Pro | 角色检查 |
| lore_check | V4 Pro | 世界观检查 |
| foreshadow_check | V4 Pro | 伏笔检查 |
| editor | V4 Pro | 编辑润色 |
| audit | V4 Pro | 质量审计 |
| optimizer | V4 Pro | 全书优化 |
| style | V4 Pro | 风格分析 |

**实现：**

```python
# app/routes/settings.py
def get_effective_config(novel=None, agent_type=None):
    """三级优先级：Agent > Novel > Global"""
    base = get_model_config(agent_type=None)  # 全局
    if novel and novel.model_override:
        # 小说覆盖
        overrides = json.loads(novel.model_override)
        for k, v in overrides.items():
            if v: base[k] = v
    if agent_type:
        # Agent 覆盖（最高优先级）
        agent_cfg = get_model_config(agent_type=agent_type)
        for k in ("model_name", "temperature", "max_tokens"):
            base[k] = agent_cfg[k]
    return base
```

**存储格式（Setting KV 表）：**
- `model_name_writer` = `deepseek-v4-flash`
- `temperature_writer` = `0.9`
- `max_tokens_writer` = `4096`
- ...（共 16 × 3 = 48 个可能的 key）

---

# 12. MCP Server

26 个 MCP 工具，支持 Claude Code / Cursor 集成：

| 类别 | 工具 |
|------|------|
| 小说管理 | list_novels, create_novel, delete_novel, get_novel_info |
| 章节管理 | list_chapters, create_chapter, get_chapter_content, approve_chapter, save_chapter_content |
| 人物管理 | list_characters, create_character, update_character |
| 世界观 | list_world_settings, create_world_setting |
| 伏笔 | list_foreshadowing, create_foreshadowing, update_foreshadowing_status |
| 大纲 | list_outline, create_outline_node |
| 短篇 | list_short_stories, create_short_story, get_short_story |
| 设置 | get_settings, update_setting |
| 审计 | quick_audit, get_knowledge_context |

---

# 13. CLI 命令

**15 个命令组（含 auth/whoami）：**

```bash
# 小说
python cli.py novel list|create|info|delete [--id ID] [--title X]
python cli.py novel delete -y  # 跳过确认

# 章节
python cli.py chapter list|create|content|approve --novel ID [--number N] [--full]

# 角色
python cli.py character list|create|info [--novel ID] [--name X] [--personality X]

# 世界观
python cli.py world list|create --novel ID [--category X] [--title X]

# 伏笔
python cli.py foreshadow list|create --novel ID [--title X]
python cli.py foreshadow status --id ID --status resolved

# 大纲
python cli.py outline list|create --novel ID [--type volume|chapter|scene]

# 角色关系
python cli.py relation list|create --novel ID [--char-a ID] [--char-b ID]

# 短篇
python cli.py short list|create|content [--id ID] [--mode inspiration|setting|careful]

# 提示词模板
python cli.py template list|create|delete [--name X] [--type writer|critic|...]

# 质量审计
python cli.py audit run --novel ID --number N [--detailed]

# 系统设置（含 Per-Agent）
python cli.py setting list  # 查看所有配置（含 16 种 Agent）
python cli.py setting get --agent-type writer  # 获取特定 Agent 配置
python cli.py setting set --key api_key --value X
python cli.py setting apply-recommended  # 一键应用推荐配置
python cli.py setting clear-agent  # 清除所有 Per-Agent 自定义

# 全书优化
python cli.py optimize diagnose --novel ID

# 系统管理
python cli.py sys info
python cli.py sys backup [--output PATH]
```

---

# 14. 开发路线

## V1.0 (已完成)

- 基础 CRUD
- AI 流式生成
- 版本管理
- 评审循环
- 知识库

## V2.0 (已完成)

- 多 Agent 流水线
- 17 维度审计（V3.5 起由双盲审取代）
- 去 AI 化
- 因果链引擎
- 向量记忆
- 信息边界
- 风格指纹
- Skill 系统
- 时间真相库
- 全书优化
- 短篇模块
- MCP Server + CLI

## V2.5 (已完成 - 2026-07)

- **Per-Agent 模型配置** — 16 种 Agent 可独立配置模型/温度/tokens
- **DeepSeek V4 模型适配** — V4 Pro/Flash 分组（生成 vs 分析）
- **去 AI 化扩充** — 从 40+ 升级到 120+ 模式，8 大类
- **CLI 完善** — 从 5 命令组扩展到 15 命令组
- **SSL 容错** — http_client.py 统一处理
- **Linux venv 兼容** — 创建 bin/ 风格虚拟环境

## V3.0 (已完成 - 2026-07)

### 15. 用户认证 (P0-3) — ⚠️ 已于 V3.1 禁用（单用户免登录）

> **当前状态（2026-08-17）：** 多用户登录已去除，改为单用户免登录。
> `app/routes/auth.py` 中 `login_required` 为 no-op，全局 `require_login` 钩子已删除，
> `/login` `/logout` 重定向首页，`cli.py` 免登录。以下为 V3.0 历史实现，仅供恢复参考。

**Session-based 认证架构（历史实现）：**

```text
┌──────────┐       ┌──────────┐       ┌──────────┐
│ Browser  │──────▶│  Flask   │──────▶│  Session │
│ (Cookie) │       │  Routes  │       │  Cookie  │
└──────────┘       └──────────┘       └──────────┘
       │                  │
       │            before_request
       │            require_login()
       ▼                  ▼
   /login         ├─ /login (公开)
   form post      ├─ /static (公开)
                   ├─ /api/* (返回 401 JSON)
                   └─ 其他 (重定向 /login)
```

**实现位置：** `app/routes/auth.py`（原 `app/services/auth.py`）

```python
PUBLIC_PATHS = {"/login", "/logout", "/static"}

@auth_bp.before_app_request
def require_login():
    """全局登录检查 — 除公开路径外都需要登录。"""
    if request.path in PUBLIC_PATHS or request.path.startswith("/static/"):
        return None
    if session.get("user"):
        return None
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"error": "未登录", "login_required": True}), 401
    return redirect(url_for("auth.login_page", next=request.path))
```

**默认账号（保留常量，已不再用于登录）：**
- `admin/admin` (管理员)
- `user/user` (普通用户)

**CLI 认证（已禁用）：** 状态文件 `~/.lingyan_cli_auth.json` 不再使用，`check_cli_auth()` 直接放行

### 16. 模板库 (P2-1 + P1-4)

**大纲模板 (4 种)：**

| 模板 | 节点数 | 适用 |
|------|--------|------|
| 节拍式 | 15 | 商业小说 |
| 三幕式 | 12 | 戏剧性强 |
| 英雄之旅 | 12 | 冒险/成长 |
| 四幕式 | 13 | 电影剧本 |

**API：** `GET /api/outline-templates/list`

**角色模板 (6 种)：**

| 模板 | 类型 |
|------|------|
| `brave_hero` | 热血少年 |
| `cold_swordsman` | 冷峻剑客 |
| `gentle_lady` | 温婉少女 |
| `scheming_villain` | 腹黑反派 |
| `wise_mentor` | 智慧长者 |
| `comic_relief` | 搞笑担当 |

**应用 API：** `POST /novel/<id>/characters/create-from-template`

**AI 生成角色 API：** `POST /novel/<id>/characters/ai-generate`

### 17. 多格式导出 (P2-2)

| 格式 | 依赖 | 端点 |
|------|------|------|
| TXT | 无 | `/novel/<id>/export/txt` |
| DOCX | python-docx | `/novel/<id>/export/docx` |
| Markdown | 无 | `/novel/<id>/export/md` |
| HTML | 无 | `/novel/<id>/export/html` |
| EPUB | ebooklib | `/novel/<id>/export/epub` |

### 18. 仪表盘升级 (P1-2 + P2-5)

**新增统计卡片：**
- 总字数 / 章节进度 / 完成度
- 连续创作天数 (streak)
- 本周字数
- 平均每章

**新增可视化：**
- 字数趋势 SVG 折线图
- 进度条 + 目标完成度
- 超时伏笔警告

### 19. 新手引导 (P0-1)

- 首页「第一次使用灵砚？」悬浮卡片
- 一键加载 3 部示例数据（《破天》/《星际迷航》/《深夜来客》）
- 关闭后通过 `localStorage` 记忆

### 20. 移动端适配 (P2-3)

```css
@media (max-width: 768px) {
    .topbar-nav a { display: none; }
    .mobile-menu-btn { display: block; }
    .mobile-menu { display: none; }
    .mobile-menu.open { display: block; }
}
```

- 汉堡菜单（< 768px）
- 响应式统计卡片（2 列布局）
- 移动端导航菜单

### 21. 草稿自动保存 (P1-3)

```javascript
const DRAFT_KEY = `lingyan_draft_${storyId}`;
const DRAFT_INTERVAL = 10000; // 10 秒

function saveDraft() {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
        content: content,
        timestamp: Date.now(),
    }));
}
setInterval(saveDraft, DRAFT_INTERVAL);
```

- 每 10 秒保存到 `localStorage`
- 页面加载检测草稿，提供恢复横幅
- 成功保存到服务器后清除草稿

### 22. 文风锚例 (Style Anchor)

真人原文直插 prompt 做风格锚定（详见 5.3.1）：

```python
from app.services.style_fingerprint import format_anchor_for_prompt

anchor_ctx = format_anchor_for_prompt()  # 空串 = 未启用/未设置
if anchor_ctx:
    system += "\n\n" + anchor_ctx
```

- 存储于 `Setting` 键 `style_anchor_text` / `style_anchor_enabled`
- 注入长篇 + 短篇全部正文生成链路（生成/改写/润色/局部编辑）
- 设置页粘贴入口 + 短篇写作页圆点开关

---

## V4.0 (未来规划)

- 多用户协作系统
- WebSocket 实时推送
- 向量 Embedding (bge-large-zh)
- 移动 App (React Native)
- AI 自动续写
- 自动封面图生成
- 模板市场
- 订阅版 SaaS
