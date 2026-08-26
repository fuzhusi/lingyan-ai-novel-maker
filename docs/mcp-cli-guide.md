# 灵砚 MCP Server & CLI 使用文档

> **更新于 2026-08-17** - 覆盖 V3.1 功能（单用户免登录、短篇逐节点多轮生成、多格式导出、模板库、Per-Agent 配置等）

## 一、概述

灵砚提供三种操作接口：

| 接口 | 适用场景 | 启动方式 | 是否需要登录 |
| --- | --- | --- | --- |
| **MCP Server** | Claude Code / Cursor 等 AI IDE 集成 | `python mcp_server.py` | 否 |
| **Web** | 浏览器访问 | `python run.py` → http://127.0.0.1:5000 | 否（单用户模式） |
| **CLI** | 命令行脚本、自动化 | `python cli.py <命令>` | 否（单用户模式） |

---

## 二、MCP Server

### 2.1 简介

MCP Server 通过 stdio 协议通信，适用于 Claude Code、Cursor 等支持 MCP 的 AI 工具。

**启动命令：**
```bash
python mcp_server.py
```

### 2.2 Claude Code 配置

在 `~/.claude/settings.json` 中添加：

```json
{
  "mcpServers": {
    "lingyan": {
      "command": "python",
      "args": ["/path/to/Ai novel system/mcp_server.py"],
      "env": {}
    }
  }
}
```

### 2.3 可用工具 (26 个)

#### 小说管理 (4)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_novels` | 无 | 列出所有长篇小说 |
| `create_novel` | title, genre?, synopsis?, world_intro? | 创建新小说 |
| `delete_novel` | novel_id | 删除小说及所有数据 |
| `get_novel_info` | novel_id | 获取小说详细信息 |

#### 章节管理 (5)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_chapters` | novel_id | 列出章节 |
| `create_chapter` | novel_id, chapter_number, title?, outline? | 创建章节 |
| `get_chapter_content` | novel_id, chapter_number | 获取章节最新版本 |
| `approve_chapter` | novel_id, chapter_number | 审批通过最新版本 |
| `save_chapter_content` | novel_id, chapter_number, content, source? | 保存章节（创建新版本） |

#### 人物管理 (3)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_characters` | novel_id | 列出角色 |
| `create_character` | novel_id, name, personality?, ... | 创建角色 |
| `update_character` | character_id, **kwargs | 更新角色信息 |

#### 世界观管理 (2)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_world_settings` | novel_id | 列出世界观设定 |
| `create_world_setting` | novel_id, category, title, content | 创建世界观设定 |

#### 伏笔管理 (3)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_foreshadowing` | novel_id | 列出伏笔 |
| `create_foreshadowing` | novel_id, title, description, importance? | 创建伏笔 |
| `update_foreshadowing_status` | foreshadow_id, new_status | 更新伏笔状态 |

#### 大纲管理 (2)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_outline` | novel_id | 列出大纲树 |
| `create_outline_node` | novel_id, title, summary?, node_type?, parent_id? | 创建大纲节点 |

#### 短篇创作 (3)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_short_stories` | 无 | 列出所有短篇 |
| `create_short_story` | title, inspiration?, mode?, genre?, theme?, ... | 创建短篇 |
| `get_short_story` | story_id | 获取短篇内容 |

#### 系统设置 (2)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `get_settings` | 无 | 查看所有设置 |
| `update_setting` | key, value | 更新设置 |

#### 质量审计 (2)

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `quick_audit` | novel_id, chapter_number | 快速 AI 痕迹检查（De-AI 统计） |
| `get_knowledge_context` | novel_id | 获取知识库上下文 |

### 2.4 使用示例

在 Claude Code 中：

```text
> 用灵砚创建一部科幻小说，标题叫《星际迷航》
AI 会调用: create_novel(title="星际迷航", genre="科幻")

> 给这部小说创建第一章，大纲是主角醒来发现飞船失联
AI 会调用: create_chapter(novel_id=1, chapter_number=1, title="苏醒", outline="...")

> 列出所有角色
AI 会调用: list_characters(novel_id=1)

> 给主角添加性格设定
AI 会调用: update_character(character_id=1, personality="机智勇敢")
```

---

## 三、Web 端使用 (免登录)

### 3.1 首次使用

1. 打开 `http://127.0.0.1:5000`，免登录直接进入
2. 看到首页「第一次使用灵砚？」引导卡片
3. 点击「一键加载示例数据」自动创建 3 部示例小说（玄幻/科幻/悬疑）
4. 或点击「我已有经验」跳过引导
5. 进入小说列表开始创作

### 3.2 核心功能

| 功能 | 路径 | 说明 |
|------|------|------|
| 长篇创作 | `/novel/` | 小说/章节/角色/世界观/大纲/伏笔管理 |
| 短篇创作 | `/short/` | 3 种创作模式 |
| 仪表盘 | `/novel/<id>/dashboard/` | 统计 + 趋势图 |
| 设置 | `/settings/` | 全局 + Per-Agent 配置 |
| 模板库 | `/prompt-templates/` | Prompt 模板管理 |

### 3.3 移动端

屏幕宽度 < 768px 时自动启用汉堡菜单。

### 3.4 草稿自动保存

短篇创作时每 10 秒自动保存到 localStorage，刷新页面可恢复。

### 3.5 短篇逐节点多轮生成（灵感模式）

1. 输入灵感 → 「灵感发散」→ AI 输出构思 + 剧情大纲节点列表
2. 「确认构思，开始创作」→ AI 按大纲逐节点生成（每节点一轮）
3. 创作中可随时**暂停 / 继续**（断点自动持久化）
4. 完成后可**重新创作**（从头生成全部节点）

---

## 四、CLI 命令行 (免登录)

### 4.1 说明

- **免登录**，直接执行命令；`auth` 命令组保留但不再需要
- 查看当前用户：`python cli.py whoami`（恒为默认管理员）

### 4.2 小说管理 (novel)

```bash
# 列出所有小说（表格化输出）
python cli.py novel list

# 创建小说
python cli.py novel create --title "我的小说" --genre "玄幻" --synopsis "一个关于..."
python cli.py novel create --title "星际迷航" --world-intro "2150年，人类..."

# 查看小说详情
python cli.py novel info --id 1

# 删除小说（带确认）
python cli.py novel delete --id 1

# 强制删除（跳过确认）
python cli.py novel delete --id 1 -y

# 导出小说（txt/docx/md/html/epub，复用 Web 导出同一路径）
python cli.py novel export --id 1 --format txt              # 默认输出 <标题>.txt
python cli.py novel export --id 1 --format epub --output /tmp/book.epub

# 删除全部小说（危险操作，级联删除所有章节数据）
python cli.py novel delete-all -y
```

### 4.3 章节管理 (chapter)

```bash
# 列出章节
python cli.py chapter list --novel 1

# 创建章节
python cli.py chapter create --novel 1 --number 1 --title "第一章" --outline "本章大纲..."

# 查看章节内容（前 500 字）
python cli.py chapter content --novel 1 --number 1

# 查看完整内容
python cli.py chapter content --novel 1 --number 1 --full

# 自定义预览长度
python cli.py chapter content --novel 1 --number 1 --length 1000

# 章节版本管理（历史版本查看与清理）
python cli.py chapter version-list --novel 1 --number 1
python cli.py chapter version-content --novel 1 --number 1 --version 2
python cli.py chapter version-delete --novel 1 --number 1 --version 2   # 审批版需确认

# 去AI化诊断（--save 将处理结果保存为新版本，原文保留）
python cli.py chapter deai --novel 1 --number 1
python cli.py chapter deai --novel 1 --number 1 --save

# 审批章节
python cli.py chapter approve --novel 1 --number 1
```

### 4.4 角色管理 (character)

```bash
# 列出角色
python cli.py character list --novel 1

# 创建角色（完整版）
python cli.py character create --novel 1 \
    --name "林风" \
    --personality "冷峻果敢" \
    --speaking-style "言简意赅" \
    --appearance "剑眉星目，黑衣劲装" \
    --background "孤儿，被师父收养" \
    --motivation "寻找身世真相" \
    --arc "从孤僻到信任他人"

# 查看角色详情
python cli.py character info --id 1

# 角色模板（6 种：热血少年/冷峻剑客/温婉少女/腹黑反派/智慧长者/搞笑担当）
python cli.py character template-list

# 从模板创建角色（--name 覆盖模板默认名）
python cli.py character create-from-template --novel 1 --template brave_hero
python cli.py character create-from-template --novel 1 --template wise_elder --name "云清道长"
```

### 4.5 世界观管理 (world)

```bash
# 列出世界观
python cli.py world list --novel 1

# 创建世界观
python cli.py world create --novel 1 \
    --category "势力" \
    --title "天玄宗" \
    --content "修仙界第一大宗门..."
```

### 4.6 伏笔管理 (foreshadow)

```bash
# 列出伏笔
python cli.py foreshadow list --novel 1

# 创建伏笔
python cli.py foreshadow create --novel 1 \
    --title "神秘玉佩" \
    --description "主角腰间的玉佩，似乎与上古仙人有关系" \
    --importance 8 \
    --planted 1

# 修改伏笔状态
# 合法状态: open, planned, buried, advancing, reclaimable, resolved, abandoned
python cli.py foreshadow status --id 1 --status advancing

# 编辑伏笔字段（任选其一或组合）
python cli.py foreshadow update --id 1 --title "新标题" --description "新描述" --notes "推进备注"
python cli.py foreshadow update --id 1 --importance 9 --planted 2 --threshold 20

# 超时伏笔检测（默认以最新章为当前进度，--chapter 指定）
python cli.py foreshadow timeout-check --novel 1
python cli.py foreshadow timeout-check --novel 1 --chapter 30
```

### 4.7 大纲管理 (outline)

```bash
# 列出大纲树
python cli.py outline list --novel 1

# 创建卷
python cli.py outline create --novel 1 --type volume --title "第一卷：风云起"

# 创建章节
python cli.py outline create --novel 1 --type chapter --title "第一章" \
    --summary "主角林风在破庙中醒来..." --parent 1

# 创建场景
python cli.py outline create --novel 1 --type scene --title "破庙遇袭" \
    --summary "黑衣人闯入破庙" --parent 2

# 编辑大纲节点（标题/摘要/排序号）
python cli.py outline update --novel 1 --id 3 --title "新标题" --summary "新摘要"
python cli.py outline update --novel 1 --id 3 --sort 5

# 删除大纲节点（递归级联删除全部子节点，对齐 Web）
python cli.py outline delete --novel 1 --id 3 -y

# 从大纲节点创建章节（预填章节标题+大纲，子场景并入分幕指引，自动排下一章号）
python cli.py outline create-chapter --novel 1 --id 3
```

### 4.8 角色关系管理 (relation)

```bash
# 列出关系
python cli.py relation list --novel 1

# 创建关系
python cli.py relation create --novel 1 \
    --char-a 1 --char-b 2 \
    --type "mentor" \
    --desc "师徒关系"

# 编辑关系（类型/描述）
python cli.py relation update --id 1 --type "rival" --desc "宿敌"

# 关系事件：按事件类型自动调整多维度评分（对齐 Web apply_event）
# 事件类型: battle_together / betrayal / life_saving / conflict / open_talk / public_humiliation
python cli.py relation event --id 1 --event betrayal
python cli.py relation event --id 1 --event battle_together --intensity 1.5   # 强度 0.5~2.0
```

### 4.9 短篇创作 (short)

```bash
# 列出短篇
python cli.py short list

# 创建短篇（灵感模式）
python cli.py short create \
    --title "深夜来客" \
    --mode inspiration \
    --inspiration "深夜的末班地铁上，一个陌生人对主角笑了一下"

# 创建短篇（设定模式）
python cli.py short create \
    --title "末日之城" \
    --mode setting \
    --genre "科幻" \
    --theme "人类与AI的共存" \
    --character "退役军人王明" \
    --scene "被AI控制的城市废墟" \
    --tone "压抑而希望" \
    --word-target 3000

# 查看短篇内容
python cli.py short content --id 1

# 查看完整内容
python cli.py short content --id 1 --full

# 更新元数据（标题/体裁/主题/基调/灵感/目标字数）
python cli.py short update --id 1 --title "新标题" --genre "悬疑" --word-target 8000

# 版本管理
python cli.py short version-list --id 1                    # 版本列表（含审批标记）
python cli.py short version-content --id 1 --version 2     # 查看历史版本
python cli.py short version-load --id 1 --version 2        # 载入为当前正文
python cli.py short approve --id 1 --version 2             # 审批版本
python cli.py short version-delete --id 1 --version 2 -y   # 删除版本

# 导出短篇（txt/docx/md/html/epub，复用 Web 导出同一路径）
python cli.py short export --id 1 --format txt
```

### 4.10 故事状态引擎 (state)

```bash
# 查看故事状态（不存在时按章节数据自动检测创建）
python cli.py state get --novel 1

# 更新状态字段
python cli.py state set --novel 1 --quest "寻找圣剑" --progress "已获得地图碎片"
python cli.py state set --novel 1 --phase development --intensity 3    # 阶段 setup/development/climax/resolution，强度 1~5
python cli.py state set --novel 1 --subplot "师门恩怨线" --conflict "与师兄的误会"   # 追加支线/冲突

# 弧线阶段自动检测（基于章节字数分布；--apply 写回）
python cli.py state auto-detect --novel 1 [--apply]

# 快照与回滚
python cli.py state snapshot --novel 1 --chapter 5              # 创建快照
python cli.py state snapshot --novel 1 --chapter 10 --checkpoint # 标记为检查点
python cli.py state snapshots --novel 1                          # 快照列表
python cli.py state rollback --novel 1 --snapshot 3 -y           # 回滚到指定快照
```

### 4.11 提示词模板 (template)

```bash
# 列出模板
python cli.py template list

# 创建模板
python cli.py template create \
    --name "我的写手模板" \
    --type writer \
    --content "你是一位专业的小说作家..." \
    --constraints "禁用词: 仿佛、宛如、不禁..."

# 删除模板
python cli.py template delete --id 1
```

### 4.12 质量审计 (audit)

```bash
# 基本审计
python cli.py audit run --novel 1 --number 1

# 详细模式（列出前 10 个具体问题）
python cli.py audit run --novel 1 --number 1 --detailed
```

输出示例：
```
【第1章 AI 痕迹审计】
  字数: 3500
  检测到 AI 模式: 12 处
  字数变化: 3.2%
  禁用词库: 120 个
  正则模式: 30 个
  口语化规则: 40 个
```

### 4.13 系统设置 (setting)

```bash
# 列出所有设置（含 Per-Agent 配置状态）
python cli.py setting list

# 获取特定 Agent 的配置
python cli.py setting get --agent-type writer

# 获取特定 key
python cli.py setting get --key model_name

# 设置全局配置
python cli.py setting set --key api_key --value "sk-xxx"
python cli.py setting set --key model_name --value "deepseek-v4-pro"

# 一键应用推荐配置（写入 16 个 Agent 的最佳实践）
python cli.py setting apply-recommended

# 清除所有 Per-Agent 自定义配置（恢复全局）
python cli.py setting clear-agent
```

### 4.14 全书优化 (optimize)

```bash
# 诊断整本书
python cli.py optimize diagnose --novel 1

# 章节去AI化（诊断模式命中统计；--save 保存为新版本，原文保留）
python cli.py optimize deai --novel 1 --number 2
python cli.py optimize deai --novel 1 --number 2 --save
```

输出示例：
```
【诊断报告】
  总章节: 20
  总问题: 35
  高严重度: 8
  平均分: 7.5
  需要修复: 12
```

### 4.15 系统管理 (sys)

```bash
# 系统信息
python cli.py sys info

# 加载示例小说（对齐 Web 首页「一键加载示例数据」；已存在的示例跳过）
python cli.py sys sample-data

# 备份数据库
python cli.py sys backup
python cli.py sys backup --output /path/to/backup.db
```

### 4.16 双盲审 (blind)

阎浮（市场毒舌）× 白骨（文学刻薄）对正文做零上下文盲审，各给「追读 / 弃稿」判决；
结果落库 `blind_reviews` 表，与 Web 盲审工作台（`/blind/`）共用记录。

```bash
# 盲审短篇 / 章节（缺省最新版，可 --version 指定历史版本）
python cli.py blind run --story 1
python cli.py blind run --novel 1 --number 2 [--version 3]

# 盲审自由文本文件（UTF-8）
python cli.py blind run --file 稿子.txt

# 查看对象最近一次盲审记录
python cli.py blind latest --story 1
python cli.py blind latest --novel 1 --number 2

# 把最近一次盲审意见返还 Writer 生成第二稿（写入 md 文件，不改库内正文）
python cli.py blind rewrite --story 1
python cli.py blind rewrite --story 1 --only baigu      # 只采纳白骨意见（可 yafu/baigu 组合）
python cli.py blind rewrite --story 1 --out 二稿.md
```

说明：`run` 与 `rewrite` 需要已配置可用模型（深度分析类走 critic/rewrite 配置）；
`rewrite` 仅支持短篇/章节目标——自由文本的循环重写请在 Web 工作台人工勾选意见进行。

---

## 五、自动化脚本示例

### 5.1 批量创建章节

```bash
for i in $(seq 1 20); do
    python cli.py chapter create --novel 1 --number $i --title "第${i}章"
done
```

### 5.2 导出所有小说信息

```bash
python cli.py novel list > novels.txt
for id in 1 2 3; do
    python cli.py chapter list --novel $id >> chapters.txt
    python cli.py character list --novel $id >> characters.txt
done
```

### 5.3 Python 脚本调用

```python
import subprocess

# 免登录，直接创建小说
subprocess.run(["python", "cli.py", "novel", "create",
                "--title", "AI小说", "--genre", "科幻"])

# 批量创建章节
for i in range(1, 21):
    subprocess.run(["python", "cli.py", "chapter", "create",
                    "--novel", "1", "--number", str(i),
                    "--title", f"第{i}章"])

# 触发审计
subprocess.run(["python", "cli.py", "audit", "run",
                "--novel", "1", "--number", "1", "--detailed"])
```

### 5.4 配置 Per-Agent 模型

```bash
# 一键应用推荐配置（推荐首次使用）
python cli.py setting apply-recommended

# 自定义：让 writer 用 Flash，critic 用 Pro
python cli.py setting set --key model_name_writer --value "deepseek-v4-flash"
python cli.py setting set --key model_name_critic --value "deepseek-v4-pro"

# 或在 UI 中编辑
# 打开 http://127.0.0.1:5000/settings/
```

---

## 六、新增 API 端点 (V3.0)

### 6.1 大纲模板

```bash
# 获取所有大纲模板
curl http://127.0.0.1:5000/api/outline-templates/list
```

返回 4 种模板：节拍式 (15 节点)、三幕式 (12 节点)、英雄之旅 (12 节点)、四幕式 (13 节点)

### 6.2 角色模板

```bash
# 获取角色模板
curl http://127.0.0.1:5000/novel/1/characters/templates

# 从模板创建角色
curl -X POST http://127.0.0.1:5000/novel/1/characters/create-from-template \
  -d "template_key=cold_swordsman" -d "name=林风"

# AI 自动生成角色
curl -X POST http://127.0.0.1:5000/novel/1/characters/ai-generate \
  -d "role_hint=主角的父亲" -d "style_hint=冷峻严肃"
```

### 6.3 多格式导出

```bash
# 通过浏览器下载
http://127.0.0.1:5000/novel/1/export/txt
http://127.0.0.1:5000/novel/1/export/docx
http://127.0.0.1:5000/novel/1/export/md   # 新增 Markdown
http://127.0.0.1:5000/novel/1/export/html  # 新增 HTML
http://127.0.0.1:5000/novel/1/export/epub # 新增 EPUB
```

### 6.4 示例数据加载

```bash
# 一键加载 3 部示例小说
curl -X POST http://127.0.0.1:5000/sample/load-all
```

返回：
```json
{
  "ok": true,
  "total_count": 3,
  "new_count": 3,
  "message": "已加载 3 部示例小说 (新增 3)"
}
```

---

## 七、MCP + Claude Code 完整工作流

### 7.1 从零开始创作

```text
1. 用户: 帮我创建一部仙侠小说《破天》
2. AI: 调用 create_novel(title="破天", genre="仙侠")
3. 用户: 设定主角林风，性格冷峻，天赋异禀
4. AI: 调用 create_character(novel_id=1, name="林风", personality="冷峻", ...)
5. 用户: 创建第一章大纲
6. AI: 调用 create_chapter(novel_id=1, chapter_number=1, outline="...")
7. 用户: 生成第一章内容
8. AI: 提示用户通过 Web 页面触发流式生成（MCP 暂不支持流式）
9. 用户: 审核章节
10. AI: 调用 approve_chapter(novel_id=1, chapter_number=1)
```

### 7.2 批量管理

```text
1. 用户: 列出所有伏笔，告诉我哪些超时了
2. AI: 调用 list_foreshadowing(novel_id=1)
3. AI: 分析并报告超时伏笔
4. 用户: 把超时的伏笔状态改为 abandoned
5. AI: 调用 update_foreshadowing_status(...)
```

### 7.3 配置优化

```text
1. 用户: 我想用 deepseek-v4-flash 跑章节生成，pro 跑评审
2. AI: 调用 update_setting(key="model_name_writer", value="deepseek-v4-flash")
3. AI: 调用 update_setting(key="model_name_critic", value="deepseek-v4-pro")
4. 用户: 确认这些配置生效
5. AI: 调用 get_settings() 返回当前所有配置
```

---

## 八、注意事项

1. **单用户免登录** — Web 和 CLI 均无需登录，直接使用
2. **MCP Server** 通过 stdio 协议通信，需要由 Claude Code 等 IDE 启动
3. **生成操作**（AI 生成章节、评审、改写）需要通过 Web 页面进行，因为是流式输出
4. 所有时间戳使用 UTC，数据库为 SQLite
5. **SSL 配置：** `http_client.py` 已禁用证书验证，兼容各种网络环境
6. **Per-Agent 配置：** 优先级 `Agent > 小说 > 全局`

---

## 九、故障排查

| 问题 | 解决方案 |
|------|---------|
| MCP Server 启动报错 | 确认虚拟环境已激活：`source .venv/bin/activate` |
| CLI 找不到数据库 | 确认在项目根目录运行 |
| 端口 5000 被占用 | `pkill -9 -f "python run.py"` |
| API 401 错误 | 检查 `python cli.py setting list` 中的 api_key |
| 中文显示乱码 | 确认终端编码为 UTF-8 |
| Per-Agent 配置不生效 | 确认 `model_name_{agent_type}` 键已设置 |
| 一键加载示例失败 | 检查 Flask 应用是否正常运行 |
| 草稿恢复不显示 | 检查浏览器 localStorage 是否启用 |
| 短篇发散后无节点进度条 | 发散输出未按节点格式，重新发散即可 |