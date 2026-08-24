# 灵砚 · 代码审查修复报告

> 日期：2026-08-24
> 对应审查报告：[docs/code-review.md](code-review.md)
> 范围：四批路线图全部落地，共 **47 个文件**（+888 / −351 行）
> 验证：26 项自动化检查全过、22 个页面冒烟零 5xx（详见文末「验证记录」）

---

## 目录

1. [P0 止血批](#一p0-止血批)
2. [安全批](#二安全批)
3. [归属校验与逻辑漏洞批](#三归属校验与逻辑漏洞批)
4. [流式与解析协议批](#四流式与解析协议批)
5. [短篇正确性批](#五短篇正确性批)
6. [服务引擎批](#六服务引擎批)
7. [知识库批](#七知识库批)
8. [统计与杂项批](#八统计与杂项批)
9. [前端模板批](#九前端模板批)
10. [工程化批](#十工程化批)
11. [验证记录](#十一验证记录)
12. [已知遗留](#十二已知遗留)

---

## 一、P0 止血批

### 1. 删除小说 500 NameError
- **文件**：`app/routes/novel.py`
- **问题**：路由引用 `ChapterMemory / CharacterRelation / StoryState / StoryStateSnapshot` 但从未导入；任何一次删除小说都是 HTTP 500，且事务残留半删状态。
- **修复**：补齐四个导入。实测删除链路（含版本/评审/记忆级联清理）已跑通。

### 2. Werkzeug 调试器默认开启（RCE 风险）
- **文件**：`run.py`
- **问题**：`debug=True` 硬编码，调试器 PIN 可被绕过时等于远程代码执行。
- **修复**：仅当环境变量 `LINGYAN_DEBUG=1` 时开启。

### 3. `/settings/api/config` 明文返回 api_key
- **文件**：`app/routes/settings.py`
- **问题**：任意登录态页面可 fetch 到明文 key。
- **修复**：key 掩码为前 6 位 + `****`；新增 `has_provider_config` 字段供前端做「是否已配置厂商」预检。

### 4. 「删除全部小说」无任何确认
- **文件**：`app/routes/novel.py`、`app/templates/novel_list.html`
- **修复**：后端要求表单字段 `confirm=YES`，否则 400；前端表单加隐藏域。

### 5. 删除确认弹窗未插值书名 + 引号注入面
- **文件**：`app/templates/novel_list.html`
- **修复**：onclick 改单引号属性定界 + `"..." + {{ novel.title|tojson }} + "..."` 拼接（书名中的引号由 tojson 转义）。

---

## 二、安全批

### 1. CSRF 轻防护
- **文件**：`app/__init__.py`
- **方案**：`before_request` 钩子——对 POST/PUT/PATCH/DELETE，若请求携带 `Sec-Fetch-Site` 且值不属于 `{same-origin, same-site, none}` 则 403。现代浏览器均发送该头，旧客户端不携带则放行，零模板改动。

### 2. SSL 校验策略
- **文件**：`app/services/llm.py`
- **问题**：全局 `verify=False`，中间人可窃取 API key。
- **修复**：新增 `_ssl_verify_for(base_url)`——默认强制校验；localhost / 127.x / 10.x / 192.168.x / 172.16-31.x / *.local 自动豁免；公网自签域需显式设 `LINGYAN_INSECURE_SSL=1`。

### 3. 上传文件重构
- **文件**：`app/routes/plagiarize/upload.py`
- **问题**：原文件名直接落盘（路径穿越/覆盖/特殊字符）、异常时临时文件泄漏。
- **修复**：磁盘名用 uuid4；展示名 `secure_filename(原名)` 兜底 `upload.{ext}`；扩展名先白名单再清洗；读取全程 try/finally 清理。

### 4. 导出五格式加固
- **文件**：`app/routes/export.py`
- **HTML**：所有插值（标题/简介/类型/章节标题/段落）经 `html.escape`；`<head>` 注入 CSP meta（`default-src 'none'`）阻断内嵌脚本执行面。
- **EPUB**：EpubHtml 内容逐段转义；章节文件名改纯序号 `chapter_{idx:03d}.xhtml`（标题特殊字符不再进入 zip 条目名）。
- **TXT/DOCX/MD/HTML/EPUB 共通**：空内容统一 400（`没有可导出的章节内容`）；下载文件名经 `_safe_filename` 清洗 `[\\/:*?"<>|\r\n\t]`；导出范围 `MAX_RANGE_SPAN=10000` 钳制防 DoS。

### 5. 模板 XSS 注入点清理（前端代理完成，14 文件）
- `chapter_write.html`：`versions_json|safe` → `{{ versions_data|tojson }}`，后端 `routes/chapter.py` 同步改为传原生列表 `versions_data`；
- 内联 JS 注入 7 处（characters / outline / skills / world_settings ×2 / chapter_list / prompt_templates）改单引号属性 + `|tojson`；
- dashboard 动态数据（章节标题、审计 issue、因果链、时间真相）包 `escapeHtml`；
- 审计面板 `info.name` / `issue.dimension_name` / `issue.issue` 包 `escapeHtml`。

### 6. 请求体上限
- **文件**：`app/config.py`
- `MAX_CONTENT_LENGTH = MAX_UPLOAD_MB(默认50)MB`，防超大上传耗尽内存。

---

## 三、归属校验与逻辑漏洞批

跨实体 IDOR 类问题集中修（SQLite 未启用外键，此前全靠自觉）：

| 位置 | 问题 | 修复 |
|------|------|------|
| `short_story/versioning.py` 4 路由 | 版本 id 全局查询，可跨短篇读/载入/删/审批 | 全部 `filter_by(story_id=…)` |
| `routes/chapter.py` 版本读写 | 可跨小说/章节操作版本 | join Chapter 校验 novel_id + chapter_number |
| `story_state.py` rollback | 快照可跨书回滚覆盖状态 | filter_by(novel_id) |
| `knowledge/foreshadowing.py` edit/delete/advance | 可跨小说改/删/推进伏笔状态机 | filter_by(novel_id)；edit 表单收走 `status` 字段（状态只能走状态机） |
| `knowledge/outline.py` create/edit/delete | parent_id 可指向其他小说；递归删子树深大纲爆栈 | parent 同书校验；edit/delete 归属校验；删除改迭代式 BFS（一次取全节点内存闭包） |
| `knowledge/characters.py` delete | 无归属校验且不清理关系 | 归属校验 + 级联删 CharacterRelation 双向 |
| `relations.py` create | 两角色可不属于本书即可建关系 | 双向校验角色存在且同书 |
| `services/unified_review.py` | version_id 与章节不绑定 | 版本必须属于指定章节 |
| `routes/pipeline.py` foreshadow 应用 | LLM 幻觉出他书伏笔 id 会被直接改状态 | `fs.novel_id == novel_id` 才应用 |

其他：
- **章节号查重**（`chapter.py`）：重复章节号会让 `/chapter/<n>` 路由命中错误章节 → 创建时查重返回 400。
- **关系维度容错**（`relations.py`）：AI 传浮点串/None 时先 float 再 int，非法值 400 而非 500。
- **dashboard 口径修正**（`dashboard.py`）：
  - 连续创作天数：从今天（或昨天）回溯连续有版本创建的真实天数（原恒 0/1）；
  - 本周字数：近 7 天创建的版本正文字数之和（原统计的是摘要字符数）；
  - 伏笔超时：纳入全部未回收状态（含 reclaimable），以 max(chapter_number) 为基准，口径与 timeout-check API 对齐。

---

## 四、流式与解析协议批

### `_stream_chat` 错误通道重构（`app/routes/review.py`）
- **问题**：LLM 异常时把 SSE 错误串当 token 吐进正文；调用方靠「token 为空」猜测结束，错误与正文不可区分。
- **修复**：产出结构化三元组 `("token", s) / ("done", full) / ("error", msg)`；评审流与改写流两个调用方同步改造——error 直接推 `{"error": …}` 并终止，不再污染正文。

### 统一 JSON 解析入口
- 新增模块级 `_extract_json_dict(text)`：剥 ```` ```json ```` 围栏 → `json.loads` → dict 校验。
- 应用三处：评审保存（围栏 JSON 不再 500）、审批记忆（非 dict 输出防御）、并保留短篇侧独立实现。
- 审批记忆更新加防空串覆盖：结构化输出缺 `summary` 键时保留既有摘要。

### 其他
- `unified-review-stream` 生成器显式包回 app context（SSE 在请求上下文销毁后才迭代，原来必抛 Working outside of application context）。
- `_save_review` 持久化失败从静默吞掉改为 logging.exception 留痕。
- unified_review 的 critic/rewrite 提示词补传 `db=db`（用户自定义模板此前被静默忽略）；注释 location 对 index=0 不再误判为缺失。
- pipeline：Agent LLM 失败/解析失败/线程异常统一标记 `agent_status=error` 并计入 `failedAgents` 返回；全部失败返回 502 + 明确错误文案，绝不伪装成「检查通过」；流式路径新增 `check_failed` 事件。

---

## 五、短篇正确性批

全部位于 `app/routes/short_story/`：

| # | 问题 | 修复 | 位置 |
|---|------|------|------|
| S2 | 大纲重置后旧全文与新 pending 节点失配，「继续生成」整篇重复 | expand_inspiration 与 save_concept 写新大纲时清空 `story.content` | generate.py / __init__.py |
| M1 | `int(nodes[idx].word_count)` 遇 None/浮点串在流中途崩溃 | `int(float(... or 1200))` 容错 | generate.py rewrite_node |
| M2 | legacy 三条生成失败分支只吐错误文本，status 永久卡 "generating" | 生成前捕获 prev_status，失败回滚（其余不改状态的流式路由明确注释无需回滚） | generate.py |
| M3 | 断点暂停后续写只并入「末节点 done」的情况，pending 场景续写丢失 | 并入最近一个有正文的节点并 rebuild 全文 | continue_story |
| S3 | 存在 pending 缺口仍标 done，残文被当完整作品入库/导出 | 仅全部节点 done 才置 done，否则 concept_ready（主生成/单节点重写/评审重写三处对齐） | generate.py / review.py |
| — | NODE 标题含 `=` 或换行破坏前端解析正则 | 统一走 `_node_marker()` 清洗（`=`,`\r`,`\n` → `_`），前端正则同步非贪婪化 | generate.py / review.py / write.html |
| — | 「标题 —— 描述」的描述整体吞进 title 永久丢失 | parse_outline_nodes 拆出 summary 字段 + word_count 容错钳制 [300,3000] | generate.py |

---

## 六、服务引擎批

### deai 规则手术（`deai_patterns.py` / `deai_agent.py`）

误伤修复（正常中文不再被削残）：

- **语气词裸串块整体移除**：「语气平静」等会命中合法叙述（“她的语气平静得可怕”）并删成残句；
- **空替换改语义替换**：不由自主→忍不住、身不由己→只好、鬼使神差→稀里糊涂；「莫名其妙」移出禁用表（正常人常用语）；
- **「不是X而是Y」保留两侧信息**：`\1，其实\2`（原直接丢弃前半句）；
- **口语化剥离全面加负向断言守卫**：`坚持(?!了|着|过|的|性)` 等 20 余条——「坚持了三天三夜」「决定权」「选择性忽略」「无意冒犯」等不再被削；死规则（不由得…起来，Pass1 已替换前词永不命中）改为双前导匹配；
- **是X的/有X的通配删除规则移除**：「这是他的书」「有的是时间」曾被删残；
- **句首重复剥离限白名单**：只剥然后/接着/于是等话语连接词，代词/名词主语不再被剥成无主残句。

功能增强：

- **`deai_auto` 全局开关**（Setting 键，缺省开）：置 "0" 后保存/生成链路直通原文；`deai_process(force=True)` 供 CLI/诊断绕过；
- 人工来源（`source != "ai"`）版本保存不做 deai（原有行为保持并文档化）。

### text_cleaner.py
- 编号列表标记仅剥序号 ≤99（`1995. 那一年雪很大` 年份叙述句存活）；
- 星号/下划线仅成对出现才剥离（孤立 `*`/`_` 不再误删）。

### 其他服务
- `causal_chain.py`：LLM 输出非 dict（list/str）时抛错进统一 error 分支，不再 AttributeError；
- `temporal_truth.py`：add_truth 闭合同主体同属性的旧进行中记录（原与 update_truth 行为不一致，产生双 ongoing）；
- `vector_memory.py`：relevance 由 `abs(rank)` 改 `-rank`（原排序完全颠倒）；init_fts 进程级缓存（DDL 只建一次）；新增 `delete_novel_memory()` 并挂入单删/全删两条小说删除路径；
- `audit.py`：`_safe_score()` 强转分数（bool/None/字符串回退中性分 5），加权聚合不再 TypeError。

---

## 七、知识库批

见第三节表格（foreshadowing / outline / characters / relations 均在此批完成）。

补充：
- foreshadow timeout-check 纳入 reclaimable 状态（此前「已可回收但没人收」永远不出警告）。

---

## 八、统计与杂项批

见第三节 dashboard 部分；另：
- `chapter_write.html` 生成预检改用 `has_provider_config`（api_key 已掩码，明文判断失效）。

---

## 九、前端模板批（并行子代理完成）

14 个模板 + 自查通过（Jinja 标签栈配平 14/14；JS 括号引号配平通过）：

| 文件 | 修改点 |
|------|--------|
| chapter_write.html | versions_data\|tojson；_loadVer 成功才更新 currentVersionId + resp.ok + 不吞错；save-outline 校验 ok 且真字符 ✓；审计面板 escapeHtml；生成预检 has_provider_config |
| base.html | 移动端按钮移出 .topbar-nav；<768px inline-flex；点击外部/Esc 关闭 |
| short_story/write.html | 三个流式 helper getReader 前 resp.ok 检查（async 化），throw 走既有 catch 不触发存版本；NODE 正则非贪婪化 |
| dashboard.html | escapeHtml helper + 五处动态插值转义；三个按钮 handler try/catch 显示错误 |
| characters/outline/skills/world_settings×2/chapter_list/prompt_templates | 单引号属性 + \|tojson 注入 |
| settings_llm.html | fetchModels 按 enabled 渲染勾选/底色 + 真实统计；提交禁用按钮 + catch 恢复 |
| gateway.html | data.ok 为假恢复按钮 + alert 错误 |
| plagiarize/detail.html | 读循环 .catch 恢复按钮 + 「连接中断」提示（createElement/textContent 防注入） |
| short_story/new.html | switchMode 对非当前分组字段设 disabled（不随表单提交）+ 初始同步 |

后端配套：`routes/chapter.py` 改传 `versions_data` 原生列表（与模板切换同上线）。

---

## 十、工程化批

- `pyproject.toml`：`[dependency-groups] dev = ["pytest>=8.0"]`；
- 新增 `tests/conftest.py`：导入 app 前把 DATABASE_PATH 指向仓库内 `.tmp-test/`（sqlite URI 反斜杠转正斜杠；沙箱环境系统 TEMP 不可写时的兼容写法），session 级 app fixture + client fixture；
- `.env.example`：MODEL_NAME → deepseek-v4-pro（标注 deepseek-chat 2026-07 弃用）、SECRET_KEY / LINGYAN_DEBUG / LINGYAN_INSECURE_SSL / MAX_UPLOAD_MB 说明；
- `CLAUDE.md` 对齐实际行为：SSL 策略、streak/week 口径、deai 开关与守卫说明。

---

## 十一、验证记录

一次性脚本（已运行并删除），**26/26 通过**：

```
1. 模块导入扫描        app 包 64 个模块全部可导入            [OK]
2. 运行时冒烟          建小说/章节/版本                       [OK]
                       人工来源不做 deai                      [OK]
                       AI 来源自动 deai（仿佛→像）            [OK]
3. 导出与 XSS          TXT/MD/HTML 200                        [OK]
                       标题 <script> 已转义                   [OK]
                       HTML 含 CSP meta                       [OK]
4. 归属校验            跨书读版本 404                         [OK]
                       跨短篇载入版本 404                     [OK]
                       跨书推进伏笔 404                       [OK]
5. 安全                delete-all 无 confirm → 400            [OK]
                       Sec-Fetch-Site=cross-site → 403        [OK]
                       重复章节号 → 400                       [OK]
6. 删除回归            删除单本成功（P0-1 NameError 修复）    [OK]
7. deai/text_cleaner   坚持了三天/决定权/语气平静得可怕…      [OK×5]
                       年份序号保留/成对标记剥离/大序号保留   [OK×3]
```

页面冒烟 22 条路由 **0 个 5xx**（deai_auto=0 直通行为单独验证通过）。

---

## 十二、已知遗留

| # | 事项 | 说明 |
|---|------|------|
| 1 | EPUB/DOCX 依赖 | 未装时导出返回提示文本，需 `uv sync --extra export` |
| 2 | skills.html 内置技巧卡片 | 仍为双引号属性 + 服务端常量参数，非用户可控，未改 |
| 3 | save-outline 失败语义 | 仅提示不阻断，生成继续用内存大纲（按规格实现） |
| 4 | SQLite 无外键级联 | 历史遗留孤儿数据（如有）需手动清一次 |
