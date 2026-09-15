#!/usr/bin/env bash
# 09_instantiate.sh —— 将 18 个大纲章节点按顺序实例化为 Chapter 实体（章号 1-18）
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe
NID=3

# 防重跑：已有正文章节则中止
CNT=$($PY -c "import sqlite3;print(sqlite3.connect('data.db').execute('select count(*) from chapters where novel_id=$NID').fetchone()[0])")
if [ "$CNT" != "0" ]; then
  echo "[中止] novel $NID 已有 $CNT 个正文章节，请勿重跑。" >&2
  exit 1
fi

# 大纲节点 ID 102..119 对应第1..18章，按序实例化
for OID in $(seq 102 119); do
  $PY cli.py outline create-chapter --novel "$NID" --id "$OID" 2>/dev/null
done

echo "---- 章节列表 ----"
$PY cli.py chapter list --novel "$NID" 2>/dev/null
