# 调用与安装说明

本包版本：v1.1.1。

本包分两层：

- `core/`：通用协议，所有 AI 共用。
- `adapters/`：不同 AI 的入口提示或安装方式。

## Codex

Codex 需要根目录 `SKILL.md`。安装或使用时，把整个 `jiangnan-feeling-writing/` 文件夹作为一个 skill 包。

如果 Codex 已能看到此包，直接要求：

```text
使用 jiangnan-feeling-writing 写/改/诊断这个原创片段……
```

Codex 会从根 `SKILL.md` 进入，再按需读取 `core/` 和 `references/`。

## Claude / Claude Code

Claude 不会自动读取 Codex 的 skill 机制。使用：

- `adapters/claude/CLAUDE.md`

做法：把该文件内容放进 Claude 项目说明，或在对话开头粘贴给 Claude，并附上 `core/` 文件。

## DeepSeek

DeepSeek 写作模式不自动调用本地 skill。使用：

- `adapters/deepseek/写作模式投喂提示.md`

做法：把提示复制到 DeepSeek；如果 DeepSeek 支持资料区/工作空间，再把 `core/` 文件夹加入资料区。测试时必须明确目标 preset。

## 通用 LLM

使用：

- `adapters/generic/system_prompt.md`

做法：把它作为 system prompt 或自定义指令，再附上 `core/protocol.md`、`core/presets.md`、`core/fingerprints.md`、`core/evaluation.md`。

## 最小调用包

如果上下文有限，只给这四个文件：

1. `core/protocol.md`
2. `core/presets.md`
3. `core/fingerprints.md`
4. `core/evaluation.md`

`references/` 是细化参考，不是最小必需。

## v1.1.1 使用提醒

调用时除了四个天生指纹，还要明确“现实成本 / 为什么人物会选择”。如果输出只有物件、动作和余韵，但人物没有付出钱、时间、身体、名誉、关系、工作风险、阵营身份或生存压力，优先要求模型补成本。
