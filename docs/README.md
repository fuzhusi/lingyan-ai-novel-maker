# 灵砚 (LingYan) 文档索引

> 最后更新：2026-08-20

## 文档总览

| 文档 | 路径 | 说明 | 状态 |
|------|------|------|------|
| [CLAUDE.md](../CLAUDE.md) | 项目根目录 | Claude Code 项目指令 — 架构概览、开发规范、常用操作 | ✅ 维护中 |
| [架构文档](architecture.md) | `docs/architecture.md` | 系统架构、技术栈、项目结构、数据模型、认证、多 Agent、配置系统 | ✅ 维护中 |
| [技术设计文档](technical-design.md) | `docs/technical-design.md` | 完整技术设计 — 功能模块、Agent 架构、质量控制系统、记忆系统、数据库 DDL、API 接口、开发路线 | ✅ 维护中 |
| [实现状态与路线图](roadmap.md) | `docs/roadmap.md` | 各版本实现状态 (V1.0→V3.0 已完成)、项目指标、V4.0 未来规划 | ✅ 维护中 |
| [MCP & CLI 使用指南](mcp-cli-guide.md) | `docs/mcp-cli-guide.md` | 26 个 MCP 工具、18 个 CLI 命令组、自动化脚本示例 | ✅ 维护中 |
| [开源调研报告](open-source-survey.md) | `docs/open-source-survey.md` | 45 个开源项目调研、竞品对比、技术趋势、借鉴实现情况 | 📋 归档 (2026-06) |
| [产品整改计划](improvement-plan.md) | `docs/improvement-plan.md` | V3.0 整改计划 (P0-P3)、时间线、验收标准 — 大部分已完成 | 📋 归档 (2026-07) |

## 阅读建议

### 新加入的开发者

1. [CLAUDE.md](../CLAUDE.md) — 快速了解项目全貌和开发规范
2. [架构文档](architecture.md) — 理解系统分层和数据模型
3. [技术设计文档](technical-design.md) — 深入各功能模块设计

### 想了解实现进度

1. [实现状态与路线图](roadmap.md) — 各版本功能完成情况
2. [产品整改计划](improvement-plan.md) — 历史整改任务及验收标准

### 想使用 MCP / CLI

1. [MCP & CLI 使用指南](mcp-cli-guide.md) — 完整工具参考和示例

### 想了解竞品和技术选型背景

1. [开源调研报告](open-source-survey.md) — 45 个项目对比分析

## 文档职责划分

为避免内容重复，各文档有明确职责边界：

| 主题 | 主文档 | 其他文档中的内容 |
|------|--------|-----------------|
| 项目结构与目录 | CLAUDE.md | architecture.md (更详细) |
| 技术栈 | architecture.md | technical-design.md (含选型理由) |
| 数据模型 | architecture.md | technical-design.md (含完整 DDL) |
| Agent 架构 | architecture.md | technical-design.md (含职责表) |
| 配置系统 | architecture.md | technical-design.md (含代码示例) |
| API 接口 | technical-design.md | — |
| MCP 工具 | mcp-cli-guide.md | technical-design.md (概览) |
| CLI 命令 | mcp-cli-guide.md | CLAUDE.md (速查) |
| 实现状态 | roadmap.md | — |
| 竞品对比 | open-source-survey.md | — |
