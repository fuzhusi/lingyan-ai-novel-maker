![banner](assets/banner.png)

[![Hugging Face Collection](https://img.shields.io/badge/🤗%20Collection-Qwen3.5--9B--Humanize-yellow)](https://huggingface.co/collections/XiangJinYu/qwen35-9b-humanize)
[![Dataset](https://img.shields.io/badge/🤗%20Dataset-Humanize--Dataset-blue)](https://huggingface.co/datasets/XiangJinYu/Qwen3.5-9B-Humanize-Dataset)

[中文](README_zh.md)

---

## Overview

The goal is to rewrite AI-generated Chinese text so it is no longer flagged by detection tools, while retaining the original meaning and academic writing style. Training proceeds in three stages: SFT to establish rewriting capability, followed by two rounds of DPO to align the output distribution with human writing.

In testing, the model reduced the suspected AI ratio from ~30% to below 10% on a subset of samples. Manual spot-checks indicate that key semantics and factual content are largely preserved.

---

## Training Pipeline

### Stage 1 — SFT

~18,000 training pairs were synthesized from the [CSL](https://github.com/ydli-ai/CSL) academic abstract dataset in the format `(AI-rewritten, original human text)`. Training ran on Qwen3.5-9B for ~0.8 epoch (900 steps) and was stopped early once loss plateaued.

![SFT Training Loss](assets/sft_loss.png)

---

### Stage 2 — DPO Round 1

Dual-direction rejected data was constructed (2,000 formal + 2,000 casual samples) so the model learns "human writing distribution" rather than simply shifting toward colloquial style. Rejected reward turned negative within the first 40 steps; accuracy reached 100% and margin stabilized around ~11.

![DPO Round 1](assets/dpo_stage1_metrics.png)

---

### Stage 3 — DPO Round 2

Starting from an intermediate checkpoint of the previous stage, a second DPO round was run using self-play data (the model's own outputs as rejected samples) to push rewriting diversity further. Rejected reward declined steadily from −2.9 to −4.3 with stable convergence.

![DPO Round 2](assets/dpo_stage2_metrics.png)

---

## Dataset

Training data is publicly available, covering SFT and all DPO stages:

👉 [XiangJinYu/Qwen3.5-9B-Humanize-Dataset](https://huggingface.co/datasets/XiangJinYu/Qwen3.5-9B-Humanize-Dataset)

---

## Models

| Stage | Model | Description |
|-------|-------|-------------|
| SFT | [Qwen3.5-9B-Humanize-SFT](https://huggingface.co/XiangJinYu/Qwen3.5-9B-Humanize-SFT) | Base rewriting capability |
| DPO Round 1 | [Qwen3.5-9B-Humanize-DPO-Round1](https://huggingface.co/XiangJinYu/Qwen3.5-9B-Humanize-DPO-Round1) | Aligned to human writing distribution |
| DPO Round 2 | [Qwen3.5-9B-Humanize-DPO-Round2](https://huggingface.co/XiangJinYu/Qwen3.5-9B-Humanize-DPO-Round2) | Final model, stronger rewriting |
