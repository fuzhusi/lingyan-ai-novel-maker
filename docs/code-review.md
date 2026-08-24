# 灵砚 (LingYan) 全面代码审查报告

> **【2026-08-24 更新】** 本报告所列问题已全部修复，逐项记录见 [fix-report.md](fix-report.md)。

> 审查方式：多路并行深度审查（核心生成链路 / 短篇子包 / 服务层引擎 / 知识库·借鉴·导出路由 / 前端模板 / 配置与模型层独立复核），全部结论基于逐行阅读实际代码；关键项在隔离环境运行时实测复现（临时数据库验证、FTS5/deai/text_cleaner/causal_chain 行为实测），未采信任何臆测。
>
> 标注说明：【已复现】= 有运行时输出佐证；【静态确认】= 代码路径确凿；行号为当前工作区版本。

---

## 一、严重问题（P0：数据损坏 / 功能损坏 / 安全）

### P0-1. 删除小说功能完全损坏 —— 引用未导入模型直接 500【已复现】
- **位置**：`app/routes/novel.py:82`（`ChapterMemory`）、`:85`（`CharacterRelation`）、`:89`（`StoryStateSnapshot`）、`:90`（`StoryState`）。四个模型在第 2 行的 import 中均缺失。
- **触发**：Web 端删除任意小说（`POST /novel/<id>/delete` 或 `/novel/delete-all`）。
- **影响**：`NameError` → HTTP 500，事务回滚后小说原样保留——**删除功能从未可用**（MCP 的同名工具因自己完整导入而正常，进一步证明是 Web 路由漏 import）。
- **修复**：第 2 行 import 补齐四个模型；建议同时把两处删除逻辑收敛为共享 service（当前 Web/MCP 两份拷贝已经发生行为漂移）。

### P0-2. 去 AI 化管线系统性破坏正常中文，且改坏后随版本永久入库【已复现】
- **位置**：`app/services/deai_patterns.py` + `app/services/deai_agent.py`；调用链覆盖长篇章节保存（`routes/chapter.py:105-109`）、短篇全链路（节点生成/评审重写/版本保存）、借鉴改写、CLI/MCP。
- **实测案例**（均为真实输出）：
  - 空替换悬空虚词：`他不由自主地笑了→他地笑了`、`莫名其妙的愤怒→感到的愤怒`（patterns:33-36 只删成语不删"地/的"）
  - 动词吞并：`比赛开始了吗？→比赛了吗？`(:352)、`他放弃了抵抗→他了抵抗`(:364)、`停止了呼吸→他了呼吸`(:356)、`坚持跑步→跑步`(:372)、`进行了深入的交流→深入的交了流`(:314，把名词短语劈开插"了")
  - 否定句残废：`这不是失败，而是新的开始→这新的开始`(:304)
  - 对话修饰误伤叙述：`他的语气平静得可怕→他的得可怕`(:146-155)
  - 比喻结构吞没/语义反转（deai_agent.py:84-93）：`像疯了一样奔跑→疯了奔跑`
  - 节奏去重制造病句（deai_agent.py:46-52）：`他知道天亮了。他知道该走了。→他知道天亮了。知道该走了。`（主语被剥）；相似句长即盲删"XX的"（:57-59）；引号内台词被改写
- **要害**：保存 AI 内容时自动执行、**无开关、无预览、不幂等**，版本表里存的就是改后文本，不可恢复；短篇还有前端自动二次 deai 叠加（见 P1-12）。
- **修复**：① 立即加总开关 + 保存前 diff 预览止血；② 所有规则加上下文边界与正反测试样例重写（如 `(?:不由自主|鬼使神差)地?`、动词规则加 `(?!了|着)` 负向断言）；③ 引号区域跳过。

### P0-3. 短篇版本四路由均不校验 story_id 归属 —— 跨短篇数据串写【静态确认】
- **位置**：`app/routes/short_story/versioning.py:59,73,82,91` —— 全部 `ShortStoryVersion.query.get_or_404(version_id)`，URL 中 `story_id` 形参未使用。
- **影响**：`load_version` 可把 B 短篇正文写入 A 短篇（且不同步 outline_nodes 导致结构失配）；`delete_version` 可删任意版本连带评审；approve/get 同理。
- **同类模式遍布全项目**：长篇 `chapter.py:131,144` 版本读取/删除同样不校验归属；knowledge 各 edit/delete（characters/world/outline/foreshadowing）、relations、story_state 快照回滚（`story_state.py:211` 可跨书恢复快照）均为同一缺陷族。
- **修复**：统一改为 `filter_by(id=x, <parent_id>=y).first_or_404()`。

### P0-4. 大纲编辑/重新发散后继续生成 —— 旧全文整体重复拼接【UI 可达路径已核实】
- **链条**：`short_story/__init__.py:159-171` save_concept 与 `generate.py:217-227` expand 重析节点时无条件全置 pending、丢弃 content（且解析正则 group(4) 把「标题 —— 描述」整体吞进 title，summary 永久丢失）→ 此时 `story.content` 未清空 → `write-from-concept` 不带 reset 时 `generate.py:338-341` `_nodes_have_content=False → all_text = s.content`（旧全文当上下文前文）→ 新节点 append → **正文翻倍式污染**。
- **触发**：生成中暂停 → 点「重新生成大纲」→ 回点「继续生成」（按钮均在页面可见区域）。
- **修复**：save_concept/expand 写新节点时若 `story.content` 非空同步清空；解析正则补 ` —— ` 分割还原 summary。

### P0-5. 含缺口（pending 节点）的半成品被强制标记 done，缺口内容从全文剔除【静态确认】
- **位置**：`short_story/review.py:359-365`（基于反馈重写只遍历 done 节点后无条件 `status="done"`）、`generate.py:521-522`（单节点重写允许跳过后面 pending 节点后同样置 done）。
- **影响**：缺一节、首尾相接的残文被当作完整作品入库/导出/展示「已完成」。
- **修复**：收尾改为 `all(done) ? done : concept_ready`；对之后仍有 pending 的单节点重写给出警告或拒绝。

### P0-6. HTML/EPUB 导出零转义 —— 存储型 XSS【静态确认】
- **位置**：`app/routes/export.py:207,215,218,220,226,230`（title/synopsis/genre/章题/正文逐段直插 HTML）；EPUB 同理 :264-268（ebooklib 原样写入 content）。
- **攻击链**：AI 输出可被提示注入操纵；借鉴模块上传 EPUB/DOCX 文本可"保存为章节"且不过 deai —— 恶意文件 → 入库 → 导出带毒 HTML/EPUB。配合 P0-8 无 CSRF，打开导出文件即可调用 delete-all 清空数据。
- **修复**：所有插值 `html.escape()`；导出页加 CSP meta。

### P0-7. 文件上传三连：无大小限制 / zip bomb / 中文文件名必崩 500 且临时文件残留【静态确认】
- **位置**：`app/routes/plagiarize/upload.py`；`config.py` 无 `MAX_CONTENT_LENGTH`。
- **细节**：① TXT `f.read()` 全量读入、DOCX/EPUB 本质 zip 解压无上限 → 内存/磁盘耗尽；② `allowed_file("小说.txt")` 过检后 `secure_filename("小说.txt")` 经非 ASCII 剥离退化为 `"txt"`，`:77 rsplit(".",1)[1]` 抛 IndexError → 500，且异常发生在 `:88 os.remove` 之前 → 固定名文件永久残留 uploads/ 并互相覆盖（**目标用户常态就是中文文件名，此路必现**）。
- **修复**：`MAX_CONTENT_LENGTH=20MB`；先 secure 再校验扩展名；存储名 `uuid4().hex+ext`；save/parse 包 finally 清理；解压前检查 zip 条目大小。

### P0-8. 全站零 CSRF + 破坏性端点裸奔 + debug=True
- `novel.py:96 delete_all_novels` 无确认参数无 token；全部 POST 写操作无 CSRF；外部网页可表单打向 `127.0.0.1:5000` 静默清库（CORS 不拦请求送达）。`run.py:7` debug=True 使任意一个上述 500 弹出 Werkzeug 交互式调试台（历史多次 PIN 绕过）。
- **修复**：CSRFProtect 全局启用；delete-all 加显式 confirm；debug 改环境变量控制。

### P0-9. SSL 校验全局关闭 —— 所有厂商流量裸奔【静态确认】
- **位置**：`app/services/llm.py:66`（fetch_models）与 `:110`（`httpx.Client(verify=False)`）。
- **影响**：不只自签名 Ollama 场景——DeepSeek/OpenAI 公网 API 的 Bearer key 与全文创作内容均可被网络路径 MITM 窃取；httpx 静默无告警。
- **修复**：默认 verify=True，仅 localhost/私网或显式 `ALLOW_INSECURE_SSL=1` 降级；client 模块级复用。

### P0-10. `/settings/api/config` 明文返回 api_key【静态确认】
- **位置**：`app/routes/settings.py:180-182` —— `get_model_config()` 返回 dict 含明文 key 直接 jsonify（对比 `llm_settings.py` 特意做了掩码）。同机任意进程/页面可读取。
- **修复**：返回 masked key；需要完整值的场景仅限服务端内部。

### P0-11. 评审/改写 SSE 错误事件被二次包裹 —— 前端卡死并显示乱码【静态确认】
- **位置**：`app/routes/review.py:58-61`（`_stream_chat` 出错时 yield `(None, SSE错误串)`）× `:98-100`（外层把该串当 token 再包一层 `{"token": "data:{\"error\"...}"}`）。
- **影响**：评审/改写失败时前端收到嵌套 JSON 字符串渲染进面板，且永远等不到 done/error 结构 → UI 异常。
- **修复**：`_stream_chat` 错误改为 yield 哨兵对象或抛出自定义异常由外层转 error 事件。（注：rewrite-stream 是活路径——`chapter_write.html:667` 在用；review-stream 无 UI 调用方）

### P0-12. `/api/unified-review-stream` 必然运行时崩溃【已复现】
- **位置**：`routes/review.py:375-377` → `services/unified_review.py:402`。SSE 生成器在 request/app context pop 之后才被迭代（Flask-SQLAlchemy 3.1 session 以 app context 为 scope），生成器内 DB 查询必抛 `RuntimeError: Working outside of application context`。
- **佐证**：代码库其他流式路由都懂这个坑——`short_story/generate.py:320-321` 有注释且生成器内 DB 操作全部包 `with app.app_context():`，唯独此处漏了。实测客户端收到 start 事件后连接中断。
- **修复**：生成器内包 app context，或视图内先算好结果再流式吐出；若决定不保留该端点则删除并从文档摘除。

### P0-13. 写作页版本 JSON 注入 `<script>` —— 存储型 XSS【静态确认】
- **位置**：`chapter_write.html:163` `{{ versions_json|safe }}` ＋ `routes/chapter.py:51-55` 普通 `json.dumps`（含章节正文前 200 字）。json.dumps 不转义 `<`，正文出现 `</script>` 即提前终止脚本块 → 后续 JSON 被 HTML 解析 → 存储型 XSS，写作页每次打开必炸。
- **修复**：改用 Flask 的 `|tojson`（自带 `\uXXXX` 转义）；同文件其余 `tojson|safe` 用法是安全的无需改。

### P0-14. 移动端全局导航整体失效 —— 汉堡按钮永远不可见【静态确认】
- **位置**：`base.html:26,64-65`。`@media(max-width:768px)` 把 `.topbar-nav{display:none}` 整个父容器隐藏，子规则 `.topbar-nav .mobile-menu-btn{display:block}` 无法生效（display:none 祖先的后代不可能显示），main.css 无覆盖。<768px 下无法到达长篇/短篇/借鉴/设置等任何页面。
- **修复**：按钮移出 `.topbar-nav` 或只隐藏容器内链接；顺带补点击外部/Esc 关闭菜单。

### P0-15. 短篇流式 helper 不检查 `resp.ok` —— 错误报文被当正文展示、替换选区并存为版本【静态确认】
- **位置**：`short_story/write.html:424-509/512-547/550-577`（对比 chapter_write.html:735 有检查）。后端 4xx 返回纯文本错误（如「构思为空…」「未选中要扩写的文本」），最坏路径 streamCollect 会用错误串**直接替换编辑器选中段落**，onDone 照常触发把错误文本存进版本库。
- **修复**：三个 helper 统一 `if (!resp.ok) throw new Error(await resp.text())`。

---

## 二、逻辑漏洞与隐患（P1：传参 / 状态机 / 一致性 / 并发）

### 生成链路
1. **pipeline 检查失败被计为通过**：`routes/pipeline.py:44-45` LLMError 返回 `{"error","pass":false}` 但 `has_issues` 要求 issues 非空（:182-185）；`:69-70` 解析失败兜底 `pass=True` —— QA 流水线对故障静默绿灯。
2. **审计分数无类型防御**：`services/audit.py:363` score 为字符串/null 时聚合 `+=` 直接 TypeError 500；且解析失败时所有维度静默填 5 分 —— **失败的审计伪装成平庸但有效的审计**。另 docstring 称 6 个审计 Agent 实为 5 个。
3. **无效参数静默降级**：`generate.py:84` novel_id/chapter_number 缺失时静默跳过全部角色/世界观/伏笔注入；`:170` 不存在的 novel_id 回退全局配置不报错；`:116-156` 因果链/记忆/边界/真理/风格五段 try/except-pass 吞掉注入失败（用户花钱买不到质量毫无感知）。
4. **approve 同步阻塞两次 LLM 调用**（summary+memory）：请求可达分钟级，失败静默（`review.py:201-204` summary_text=""），摘要缺失只有粗兜底。
5. **JSON 解析不剥 ```json 围栏**：`review.py:122`（评审整体降级为 comment）、`:229`（memory 静默丢弃）；对比 `pipeline._parse_keeper_result` 有围栏处理 —— 同类解析三处三种实现。
6. **critic 提示词拼接 bug**：`prompt_builder/review.py:29` `f"【世界观设定参考】\n\n".join(ws_lines)` 把段头变成条目间分隔符，首条无头、后续插假头。
7. **写作约束 few-shot 自我矛盾**：`context.py:78` 「人味写法✓」示例本身含禁用词"嘴角微微上扬"、残句"轻声到：。"——提示词教模型产出坏文本。
8. **续写轮丢约束**：`generate.py:54-64` 续写 messages 不带 system 去AI约束/技能提示，补写段落风格漂移；`:49` O(n²) join；`:65` word_target<floor 时 max_tokens 为负（埋雷）。

### 短篇子包
9. **rewrite_node `int(word_count)` 无容错**：`generate.py:502` 与 `:358` 不一致，None/浮点串直接 TypeError，崩溃发生在流中途（NODE 标记已发出）。
10. **legacy 无节点路径三处失败后 status 永久卡 "generating"**：`generate.py:403-405,433-435,456-458`（对照 generate_story:694 有回滚）。
11. **continue_story 吞文本**：末节点 pending 时续写内容追加到 s.content（:584），恢复生成后被纯节点 rebuild 整体覆盖丢失。
12. **双重 deai**：生成时逐节点已 deai（:370），完成后前端自动 saveVersion('ai') 服务端再跑一遍（versioning.py:43,49），不幂等叠加改写；human 来源也被 clean_ai_text 改写。
13. **并发零互斥**：同一短篇双开生成交错提交；生成中手动保存会被内存 all_text 覆盖；断连无 finally → status 卡死。
14. **刷新后断点续写 UI 不可达**：后端支持非 reset 续写，但按钮只在暂停回调动态 DOM 里，刷新后只剩破坏性「重新创作」。
15. **评审绑定最新版本而非被评内容**：`review.py:67-88`、`audit.py:155-172` 结果挂 versions[0]，手动编辑后评审对象错位；自动补建版本 source="ai" 失实。
16. **评审 max_tokens=2048 必截断长文 JSON** → 误报「AI 未返回有效 JSON」。
17. **导出**：HTML/EPUB 空内容照常出文件、DOCX/EPUB 库缺失伪装成 txt 返回 200。

### 知识库 / 状态引擎
18. **foreshadowing edit 绕过状态机**：`knowledge/foreshadowing.py:52-55` status 任意赋值使转移表形同虚设；advance 不校验归属并把当前小说章号写进别书伏笔（:146,171-174）；timeout 口径漏 reclaimable。
19. **story_state 回滚不完整**：回滚忽略 excitement_history/recent_pacing/current_chapter 等已序列化字段（`story_state.py:219-225`）；删章不清快照成悬挂引用。
20. **关系孤儿化**：删角色不清 CharacterRelation（FK 关闭 SQLite）→ 幽灵边永不自愈；创建关系不校验角色归属/存在；VALID_RELATION_TYPES 白名单是死代码。
21. **大纲递归删除无环/深保护**（`outline.py:92-97`）+ 建节点可跨小说挂父 → 跨书级联误删。
22. **dashboard 统计三连错**：「本周字数」累加的是摘要长度（:96）；「连续创作」实为布尔且 UTC 字符串比本地日期（:83,94，UTC+8 凌晨恒 0）；超时伏笔用 `len(chapters)-planted` 而非 max(chapter_number)，删中段章后漏报（:71-74）。
23. **FTS 记忆孤儿 + rowid 复用串数据**：各删除路径均不清 memory_fts，新小说复用 id 可检索出已删小说记忆；`vector_memory.py:196` abs(rank) 抹掉相关性方向；init_fts 每次搜索跑 DDL；index N+1。
24. **temporal_truth 注入矛盾真相**：add_truth 不闭合旧值（update_truth 有闭合逻辑但零调用方）。
25. **Setting 读改写竞态**：skill/temporal/style 三处单行 JSON 并发互相覆盖（Flask dev 默认多线程）。
26. **自定义技能可覆盖内置技能**：`skill_system.py:584-591` 同名 custom 覆盖 builtin → 协议包静默降级为浓缩 prompt。
27. **causal_chain 数组响应 500**：`extract_causal_chain` 返回类型不校验，路由 `.get()` AttributeError（已实测）；存进 summary 后污染生成链（被 generate.py except-pass 静默吞掉）。
28. **chapter.create_chapter 撞唯一约束 500**（`chapter.py:24-42` 不查重 uq_chapter_number）；relations int() 未捕获 500；export `?chapters=1-999999999` 区间物化 DoS。
29. **plagiarize plot/style 共用 style_report 字段互串** + save-as-skill 的 `startswith('{')` 对 "```json" 输出恒 False → 静默空技能。

### 统一评审 / 全书诊断 / pipeline 补充
30. **pipeline 应用伏笔变更不校验归属**：`pipeline.py:188-204` 对 LLM 输出的 fs_id 直接 `Foreshadowing.query.get()` 改状态并提交——模型幻觉出其他小说的伏笔 id 即跨书改数据（状态机白名单反而让越权"合法"通过）。加 `fs.novel_id == novel_id` 校验。
31. **unified-review 漏传 `db=`**：`unified_review.py:139-148,311-318` 未传 db，用户自定义 critic/rewrite 模板被静默忽略——同一章节单步评审与「全面评审」口径不一致。
32. **approve_version 记忆解析无围栏剥离 + 空串覆盖**：`review.py:229` 围栏 JSON 解析失败静默丢记忆；`:238` memory_data 缺 summary 时把已有 cm.summary 清空。应 `memory_data.get("summary") or cm.summary`。
33. **save_review 双缺陷**：全库 4 处 JSON 提取器中唯一不剥围栏的一处；`full_response="123"` 等合法非 object JSON 时 `.get()` AttributeError 500（`review.py:121-128`）。
34. **auto_revise 用长度不等判断改动**：`book_optimizer.py:178` —— 中文等长替换即误报「无变化」，前端可能跳过保存。
35. **全书诊断 N章×5Agent 串行同步单 POST**：20 章 = 100 次 LLM 调用可能挂几十分钟，无进度/超时；失败返回 `{"error":...}` 配 200，dashboard 渲染成 "undefined/10"。应改 SSE 流式逐章推送。
36. **unified_review version_id 不校验章节归属**（`unified_review.py:67-68`）：A 章上下文 + B 章正文混合审计并落库污染历史。
37. **`_save_review` 裸 except 吞持久化失败**：`unified_review.py:377-378` rollback 无日志，花钱跑的评审静默丢失。

### 前端契约补充（模板层）
38. **事件属性内 JS 字符串注入（7 处）**：characters/outline/skills/world_settings/novel_list/chapter_list/prompt_templates 各删除/操作按钮把名称直插内联 JS——autoescape 的 HTML 实体在 JS 上下文会被解码回 `'`；轻则含单引号名称使按钮失效，重则构造 breakout 存储型 XSS。应改 data-* + addEventListener 委托。
39. **dashboard.html 大量 innerHTML 拼接 AI 抽取文本零转义**：审计 issue、因果链、时序真相字段均来自 LLM 且常引用小说原文（:265-307）；chapter_write 审计面板 :904 同病（同文件 unified 渲染却做了转义，标准不一）。
40. **生成前 API Key 预检与多厂商体系脱节**：chapter_write.html:512-523 查遗留 Setting 键判定 key 是否设置，纯厂商配置用户被误报阻断（后端本可成功）。删预检或改查厂商池接口。
41. **「拉取模型」后 UI 全部显示未勾选**：settings_llm.html:254-274 重渲染不带 checked，与数据库勾选失同步，误导后续全选/全不选操作污染自动默认池。
42. **伏笔页只渲染 open/resolved 两态**：planned/buried/advancing/reclaimable 条目从页面消失但徽标仍计数（foreshadowing.html:42-43），数据看似丢失且无法编辑回收。
43. **短篇草稿恢复横幅永不触发**：write.html:365-388 的 hasServerContent 因占位文案恒为真 → banner 死代码；saveDraft 只读展示区，编辑模式未保存内容不入草稿——「10 秒自动保存」形同虚设。
44. **NODE 标记解析边界**：正则 `[^=]*` 不容标题含 `=`（后端 generate.py:348 也未清洗 title）→ 标记原文泄漏进正文入库；乱序/跳号 id 使进度 chip 错位；每 chunk 全量重扫 O(n²)。
45. **_loadVer 先改 currentVersionId 再异步取文**：fetch 失败静默（catch 空），批准/重写作用于 B 版本而屏幕显示 A 版本（chapter_write.html:233-253）。
46. **save-outline 失败仍置 hasOutline=true**（chapter_write.html:547-551）：之后「AI 生成本章」用空/占位大纲发起正文生成。
47. **杂项前端**：plagiarize/detail 读循环无 catch 按钮永久卡死；new.html 隐藏分组同名参数残留提交；saveVersion 连点重复建版本且不检查 error 响应（undefined 写入 currentVersionId）；多处 fetch 无 catch 显示假「已保存」；textContent 输出 `&#x2713;` 字面量；「采纳此版本」只 alert 不建版本。

---

## 三、轻微问题与死代码（P2，择要）

| 类别 | 条目 |
|------|------|
| 死代码 | `llm.PROVIDER_DEFAULTS`、`info_boundary.check_boundary_violations`（函数体还是 for-pass 空转）、`temporal_truth.update_truth/get_truth_changes`、`outline_templates.apply_template`（危险且零调用）、CLI AUTH_FILE 系列、`login.html` 孤儿模板、根目录 `_review_verify.py`/flask 日志残留 |
| 无效防御 | `causal_chain.py:101` 等 hasattr 恒真假防御；`deai_agent.py:151-155` callable 分支重复；`deai_patterns.py:262` 因 Pass1 先替换永不命中 |
| 校验缺失 | `if val:` 更新模式无法清空字段（knowledge 各处，与 templates_lib 口径不一）；node_type/mode 无白名单；word_target 可为负；style_fingerprint name 无校验直写 Setting.key；intensity 无范围 clamp |
| 提示词瑕疵 | DEFAULT_WRITER_CONSTRAINTS 示例含禁用词与残句（见 P1-7）；short_story_templates 体裁双向子串匹配偏置（"科幻悬疑"命中首个） |
| 兼容性 | chunk.content 可能是非 str（部分网关分片）→ join TypeError；LLM 调用无重试（fetch_models 却有 3 次）；未知 role 转 HumanMessage |
| 杂项 | 导出 download_name 含特殊字符 500（Werkzeug>=3.1 头守卫）；TXT 下划线中文宽度不对齐；DOCX 字体无中文字形；CJK 扩展 B 生僻字不入 FTS 分词 |
| 死端点（6 个，仅 docs 登记） | `/api/review-stream`、`/api/review/save`、`/api/pipeline/check(-stream)`、`/api/audit/quick`、`/api/audit/short-story/quick`、`optimize/deai(+save)/revise`——无模板/CLI/MCP 调用方；其中 unified-review-stream 还叠加 P0-12 |
| 重复实现 | 围栏剥离+JSON 提取复制 4 份且口径不一（2 处该用没用）；Web/MCP 删除逻辑两份拷贝漂移；escapeHtml 在同文件重复定义 |
| 细碎逻辑 | `unified_review.py:254` `if ann.get("paragraph_index")` 把段 0 当缺失；`generate.py:47-66` 首轮空输出仍空跑 3 轮续写；`character_ids` 脏值解析失败回退"注入全部角色"；SQLite 未配 busy timeout（并发审批+审计偶发 database is locked）；save_deai max_ver 先查后插竞态；versions 数据不含 approved 字段刷新后徽标消失 |

---

## 四、项目短板（工程化层面）

1. **测试基建形同虚设**：pytest 未列入依赖（`pyproject.toml` 无 dev/test extra，venv 里没装）；tests 直连真实 `data.db`（靠 ID 区间清理，中途崩溃即污染用户数据）；现有用例全是 happy-path，对本报告所有严重项均为盲区。
2. **无 CI / lint / 类型检查**：43 处 SQLAlchemy 2.x 已弃用的 `Query.get()`；29 处 `except: pass` 静默吞噬（generate.py 一家 5 处）——本次多个 P0/P1（NameError、数组 500、score 类型崩）都能被最基础的 pyflakes/冒烟测试拦截。
3. **数据完整性靠约定不靠约束**：SQLite FK 关闭 + 级联删除靠手工枚举，且 Web/MCP 两份拷贝已漂移（正是 P0-1 根因）；孤儿数据（FTS、快照、关系边）无清理机制。
4. **配置与文档漂移**：`.env.example` 仍写已弃用的 `deepseek-chat`（CLAUDE.md 自己标注 2026/07 弃用），SECRET_KEY 未列示例而代码默认 `dev-secret-key`；CLAUDE.md 行数/特性描述与代码脱节（generate.py 855≠734、审计"6 agents"实为 5、「断点恢复」宣称与前端入口缺失不符、「连续创作」统计未真正实现）。
5. **静默降级文化**：上下文注入失败、摘要失败、审计失败、技能解析失败全部无声吞掉——产品卖点是质量保障体系，但体系自身的故障对用户完全不可见。
6. **单用户免登录的威胁模型未闭环**：绑回环 + 免登录可以接受，但 CSRF/XSS/debug 台组合使浏览器侧攻击面完整存在；文档应明示勿改 0.0.0.0 并补最低防护。

---

## 五、修复优先级路线图

**第一批（止血，≤1 天）**
1. novel.py 补 4 个 import（一行级修复，功能从不可用到可用）
2. deai_process 加总开关 + 保存 diff 预览；human 来源不再过 clean_ai_text
3. `/settings/api/config` 掩码 key；run.py debug 改环境变量
4. versioning/chapter/knowledge 各 by-id 路由补归属过滤（统一 helper）
5. `chapter_write.html:163` 改 `|tojson`；audit score 加 `_safe_float`（一行救活三条链路）；pipeline 伏笔应用加 novel_id 校验；unified_review 补 `db=`

**第二批（安全 + 前端阻断类，1-3 天）**
6. export.py html.escape 全量插值 + CSP meta
7. upload.py：MAX_CONTENT_LENGTH + uuid 存储名 + finally 清理
8. CSRFProtect + delete-all 显式 confirm；verify=True 默认化
9. 短篇三个流式 helper 补 resp.ok 检查；base.html 移动端导航修复；7 处内联 JS 注入改事件委托；dashboard/审计面板 innerHTML 转义

**第三批（正确性，3-5 天）**
10. deai 规则逐条重写 + 正反测试样例；text_cleaner 数字列表/下划线/星号规则收紧
11. 短篇 S2/S3/M1/M2/M3（大纲重置清 content、done 判定、int 容错、generating 回滚、continue 吞文本）
12. pipeline/audit 故障语义修正（fail ≠ pass）；review.py _stream_chat 错误通道重构；JSON 提取器抽公共 `extract_json()` 并统一围栏处理
13. dashboard 统计口径与时区；foreshadowing 状态机收口 + 页面状态全集渲染；temporal_truth 闭合旧值
14. unified-review-stream 修复 app context 或摘除；全书诊断 SSE 化；拉取模型 UI 同步；API key 预检移除

**第四批（工程化，持续）**
15. pytest 入依赖 + 测试库隔离（tmp_path fixture）+ 按 P0 清单补回归用例
16. ruff/pyflakes 入 CI；Query.get 批量换 session.get；except-pass 加日志
17. 删除逻辑收敛单点 service + 打开 SQLite FK + ON DELETE CASCADE 迁移
18. 文档与实现对齐（CLAUDE.md 行数/特性、.env.example 模型名、审计"6 Agent"口径、移除 login.html/_review_verify.py 与 6 个死端点的去留决策）

---

## 六、审查统计与总体评价

- **规模**：76 个 Python 文件约 1.44 万行 + 22 个模板约 5600 行，全部逐行走查；关键结论以隔离运行时实测佐证。
- **问题总量**：严重 15 项、逻辑漏洞/中等 47 项、轻微与死代码 60+ 处（合计 120+ 具体点位）。
- **总体评价**：架构分层清晰、功能广度可观（多 Agent 协作、17 维审计、分层记忆、SSE 流式的骨架都是对的），多处防御性设计值得肯定（续写轮数上限、per-future 异常兜底、除零防护、单次原子提交、character_ids 三态语义前后端一致）。但**质量保障链路自身存在系统性故障语义缺陷**（失败被计为通过、静默降级遍布）、**文本后处理正在主动破坏作品内容且不可逆**、**归属校验缺失是全项目性的模式缺陷**、**工程化基建（测试/CI/静态检查）缺位使上述问题长期潜伏**。建议按四批路线图推进，第一、二批多为几行级的修复，投入产出比极高。

*报告完（2026-08）· 产出：ox-alpha 多路并行审查 + 隔离环境运行时验证*
