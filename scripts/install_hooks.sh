#!/bin/sh
# 安装仓库自带的 git 钩子（每台新克隆的机器跑一次）
# 用法：sh scripts/install_hooks.sh

root=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$root" ]; then
  echo "当前目录不在 git 仓库内"
  exit 1
fi

src="$root/scripts/hooks/pre-commit"
dst="$root/.git/hooks/pre-commit"

if [ ! -f "$src" ]; then
  echo "找不到 $src"
  exit 1
fi

cp "$src" "$dst"
chmod +x "$dst"
echo "已安装 pre-commit 钩子 -> .git/hooks/pre-commit"
echo "作用：改了 backend/ frontend/ sdk/ config/ 却没更新 docs/开发进度.md 时阻止提交。"
