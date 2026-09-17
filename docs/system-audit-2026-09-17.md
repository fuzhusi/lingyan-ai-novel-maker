# 灵砚系统全面技术审计报告（2026-09-17）

> 审核形式：技术审核团队（1 名技术总监管架构横切面 + 4 名专项审核员分别深审数据层、LLM 生成链、评审/一致性引擎、前端/CLI/安全），全程只读，测试基线实跑验证（305 passed）。各专项完整报告见会话记录，本文为汇总。

## 总体判定

**修复后通过。** 工程底盘扎实（单一真源删除服务、PRAGMA/WAL/迁移版本表、硬约束豁免的 prompt 预算哲学、盲审版本快照隔离、原子认领长任务、回归锚测试），但存在 **8 个 P0** 与一批系统性 P1，集中在四个主题：**FK 开启只改了一半调用方**、**可观测性归零**、**产品承诺的引擎闭环有半数空转**、**单用户安全假设的隐性依赖**。

---

## P0（8 项，须最先修）

| # | 模块 | 问题 | 位置 |
|---|------|------|------|
| 1 | 部署 | **waitress 未声明安装**，`run.py` import 静默失败回退单线程 dev server——任一 SSE 生成期间全站阻塞（现在就是坏的，不必等并发） | run.py:14-19、pyproject.toml |
| 2 | 可观测 | **全项目零日志配置**，llm 重试失败/盲审落库失败等关键故障无持久现场；8+ 模块在正确打 log 但无人配置 handler | 全仓库 |
| 3 | 可观测 | **无任何全局 errorhandler**，未捕获异常行为不定义 | app/__init__.py |
| 4 | 数据 | **批量删除/重置链路 FK 开启后实测必炸**：Web delete-all（novel.py:105-134，且 FTS 先删不可回滚）、CLI delete-all（cli.py:254-281）、sys reset（cli.py:2967-3009，bulk delete 绕过 ORM 级联）——三份旧拷贝与 delete_service 真源口径漂移。修法：全部委托 delete_service | 三处 |
| 5 | 数据 | **sys backup 永远拿不到真实库路径**（config.py 从未写 `DATABASE_PATH` 这个 key），静默备份 CWD 陈旧副本，灾难恢复链路断裂；且无 restore 命令 | cli.py:2928-2959、config.py:14-17 |
| 6 | 引擎 | **伏笔排程闭环断裂**：must_payoff 按 `expected_resolve_chapter == 本章号` 精确匹配，一章脱靶排程永久蒸发；一致性检查的 overdue 用错字段（resolve_chapter），对拆书伏笔是死代码 | narrative_plan.py:122-126、consistency_check.py:94 |
| 7 | 引擎 | **故事状态引擎空转**：excitement/pacing 全系统无任何写入方，是"有表有回滚仪式的死仪表盘"；CLI 回滚还会把现存值无条件清空（口径漂移实锤） | story_state、cli.py:1409-1413 |
| 8 | 安全 | **存储型 XSS**：盲审结果把小说标题原样 innerHTML（同页其他字段都过 escapeHtml，唯独 title 漏了；拆书 LLM 起书名可二阶注入） | chapter_write.html:1401 + blind_review.py:85 |

## P1（按主题归并）

**计量与事务**
- 流式主链路（generate/outline/focus-stream）的 LLMCall 计量因 Flask 流式响应脱离 app context **静默全丢**，"成本统计"空转；且 `_record_llm_call` 在调用方 session 上 commit/rollback，失败时会回滚调用方合法数据（llm.py:331-346 + generate.py:22-65）
- 章节审批事务跨越两次同步 LLM 调用持有 SQLite 写锁，并发时 `database is locked`（chapter_approval.py:125-222）

**安全**
- 全部端点无鉴权（单用户模式），纵深仅 127.0.0.1 绑定 + 可被 DNS rebinding 绕过的 Sec-Fetch-Site；无 Host 校验
- API key 三处明文落库（LLMProvider/Setting/novel.model_override）+ 根目录 5 个含 key 的备份散落、无轮转
- 掩码口径三处不一（前8/前6/前3），建议统一 `****last4`

**删除级联（与 P0-4 同根）**
- CLI outline delete 不解链章节必炸（cli.py:1015-1030）；CLI chapter/version delete 不清盲审——三套实现继续分叉

**引擎口径漂移**
- 伏笔容量公式拿"当前进度"当"目标章数"，开篇高峰期只许 2 条活跃伏笔即触发禁埋令（narrative_plan.py:55-59）
- 约束总量失控：技能协议包/红线/tone/boundary 各自豁免预算，最坏破万字，违背自家引用的"少而硬"原则
- 盲审两位编辑无视 novel.model_override（blind_review.py:109），同书 critic 与盲审用不同模型
- 评审 JSON 解析双标：unified_review 只认裸 ```json 开头，前导文字即静默丢分；库内已有三级容错的 extract_json_dict 未复用
- 双重 de-AI：save_version 与 create_version_record 各跑一遍（chapter.py:132-136）

**架构**
- 事务边界不成文：151 commit / 8 rollback，路由层全部裸奔（teardown 兜底救一半）
- 5 个 service 反向注册 HTTP 蓝图，分层击穿（vector_memory/skill_system/temporal_truth/causal_chain/style_fingerprint）
- 测试 session 级共享 DB，顺序依赖结构性存在（deconstruct 抖动即症状）
- cli.py 3518 行单体，删除逻辑三处重复

**前端**
- 版本 diff 渲染 `split('n')` 按字母 n 切分——lingyan-stream.js 注释里记载过的同款历史事故复发（chapter_write.html:1100,1115）
- CLI 校验缺口：novel create 无标题兜底、chapter create --number 可空落库成不可达脏数据、export 文件名未清洗

## P2（摘要）

错误分类缺 402 欠费档；重试放大（应用 3×SDK 2）；prompt 预算只统计 5 类字段，伏笔/边界块无界；focus 链路无预算；assemble_chapter_context N+1 查询（200+章时 400+ 查询）；续写 floor 不随 word_target 推导；SSE 流内 llm_calls 未推上下文（同 P1 计量）；EntityEmbedding 成为新孤儿源；FTS 仅审批时同步、编辑后陈旧；版本/评审原文/LLMCall/LongTask 无界增长；status_json 零校验；5 处缺索引；CSRF fail-open 无 Host 校验；`a.btn !important` 未限定作用域；2 处对比度不达标（2.75/2.78）；移动端断点双处维护互相 !important 对打；版本时间两种格式；auth.py 硬编码 admin/admin 死代码；applyRewrite 僵尸按钮；localStorage 键无清理；ai_metric 对白误伤；severity 中文档位不识别。

## 健康面（有证据的好设计）

delete_service 单一真源且顺序正确、PRAGMA foreign_keys+busy_timeout+WAL+迁移版本表+启动恢复一次性配齐、备份用 SQLite backup API 防 WAL 撕裂、盲审按版本快照隔离、拆书长任务原子认领+断点续跑+重启恢复、prompt 硬约束豁免的压缩哲学、anthropic 协议适配有精确回归锚、key 在 HTTP 层掩码无明文外泄通道、导出/上传路径安全扎实、FTS5 参数化+消毒、XSS 面 14 处 |safe 逐点核查后仅 1 处遗漏、305 测试实跑全绿。

## 建议修复顺序

1. **第一批（小时级，"给第二个人用"前必做）**：waitress+threaded（P0-1）、logging dictConfig（P0-2）、全局 errorhandler（P0-3）、盲审标题 XSS（P0-8，一行）、diff split('n')（P1，一行×2）
2. **第二批（天级，数据完整性）**：三处批量删除委托 delete_service + sys backup 路径反解 + restore 命令（P0-4/5）+ CLI outline delete 解链 + 带盲审/关系/拆书数据的删除回归测试
3. **第三批（引擎救活）**：伏笔排程改账本式（`<=` + 逾期升级）+ 一致性检查字段纠正（P0-6）、excitement 要么补最小生产者要么撤下（P0-7）、伏笔容量公式、盲审配置统一
4. **第四批（计量与安全）**：流式计量改上下文无关写法（P1 计量）、审批两阶段提交、Host 校验 + 管理面口令、key 加密落库 + 备份轮转出目录
5. **第五批（收敛性）**：约束注入台账、测试 per-test 隔离、service 蓝图迁出、CLI 拆分、P2 逐项消化
