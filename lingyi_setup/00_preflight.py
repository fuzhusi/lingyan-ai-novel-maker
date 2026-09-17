# -*- coding: utf-8 -*-
"""00_preflight.py —— 开工前体检。

用法（仓库根目录）：
    .venv/Scripts/python.exe lingyi_setup/00_preflight.py
    .venv/Scripts/python.exe lingyi_setup/00_preflight.py --plan-title "暂定书名"
    .venv/Scripts/python.exe lingyi_setup/00_preflight.py --backup
    .venv/Scripts/python.exe lingyi_setup/00_preflight.py --no-llm-test   # 跳过联网测试

不带 --backup 时全程只读，不会改动 data.db。
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (DB, REPO_ROOT, PYEXE, info, ok, run_cli, run_cli_expect_ok,  # noqa: E402
                  sql_scalar, step, warn, assert_novel_absent)


def main():
    ap = argparse.ArgumentParser(description="民俗灵异长篇 · 开工前体检")
    ap.add_argument("--plan-title", default="", help="暂定书名，用于占用检查（防重跑）")
    ap.add_argument("--backup", action="store_true", help="顺带做一份 DB 备份")
    ap.add_argument("--no-llm-test", action="store_true", help="跳过厂商联网测试")
    args = ap.parse_args()

    print("=== 民俗灵异长篇 · 开工前体检 ===")

    # ---------------------------------------------------------------- 0. 环境
    step("0. 环境")
    import platform
    info("repo    : %s" % REPO_ROOT)
    info("python  : %s (%s)" % (platform.python_version(), PYEXE))
    info("data.db : %.2f MB" % (os.path.getsize(DB) / 1024 / 1024))

    # ---------------------------------------------------------------- 1. 现有书单
    step("1. 现有书单（建库时不得误伤）")
    run_cli(["novel", "list"])

    # ---------------------------------------------------------------- 2. 书名占用
    step("2. 目标书名占用检查")
    if args.plan_title:
        assert_novel_absent(args.plan_title)
    else:
        warn("未传 --plan-title，跳过（定书名后务必再跑一次）")

    # ---------------------------------------------------------------- 3. 模型
    step("3. Per-Agent 生效模型")
    run_cli(["llm", "agent-list"])

    step("4. 厂商与连通性")
    run_cli(["llm", "provider-list"])
    provider = sql_scalar("select id from llm_providers where enabled=1 order by id limit 1")
    if not provider:
        warn("没有任何启用的厂商——所有生成类操作都会失败")
    elif args.no_llm_test:
        info("启用厂商 id=%s（已按 --no-llm-test 跳过联网测试）" % provider)
    else:
        info("启用厂商 id=%s，跑一次连通性测试…" % provider)
        run_cli(["llm", "test", "--provider", str(provider)], check=False)

    # ---------------------------------------------------------------- 5. 文风资产
    step("5. 文风资产（本稿已定：江南协议全保留）")
    info("--- 文风锚例（只显示前几行：状态 / 字数）---")
    r = run_cli(["style-anchor", "view"], echo=False)
    for line in (r.stdout or "").splitlines()[:3]:
        info(line)
    info("--- 已激活写作技巧 ---")
    run_cli(["skill", "active"])
    info("--- 去AI味约束词库 ---")
    run_cli(["constraint", "status"])

    # ---------------------------------------------------------------- 6. Web
    step("6. Web 服务（流式写作 / 统一评审用）")
    try:
        with socket.create_connection(("127.0.0.1", 5000), timeout=1.5):
            ok("127.0.0.1:5000 已监听 → http://127.0.0.1:5000")
    except OSError:
        warn("5000 未监听：需要时用 python run.py 启动")

    # ---------------------------------------------------------------- 7. 备份
    step("7. DB 备份")
    if args.backup:
        target = os.path.join(REPO_ROOT, "data_backup_%s.db" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        run_cli_expect_ok(["sys", "backup", "--output", target])
        ok("备份完成：%s" % target)
    else:
        warn("未传 --backup，跳过（动 DB 之前建议先备份一次）")

    print("\n体检结束。")


if __name__ == "__main__":
    main()
