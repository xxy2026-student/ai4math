#!/usr/bin/env bash
# AI4Research 一键部署（Mac / Linux；仓库名兼容保留为 ai4math）。
# 用法：
#   ./setup.sh                # 交互式
#   ./setup.sh --yes          # 全部默认继续
#   ./setup.sh --skip-opencode
set -e
cd "$(dirname "$0")"

YES=0; SKIP_OC=0
for a in "$@"; do
  case "$a" in
    --yes) YES=1 ;;
    --skip-opencode) SKIP_OC=1 ;;
  esac
done

confirm() {
  [ "$YES" = 1 ] && return 0
  read -r -p "$1 [Y/n] " r
  [ -z "$r" ] || [[ "$r" =~ ^[Yy] ]]
}

echo ""
echo "=== AI4Research 一键部署 ==="

# 1. Python
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "未找到 python3。请先安装 Python 3.11+："
  echo "  macOS:  brew install python@3.12"
  echo "  Debian: sudo apt install python3.12 python3.12-venv"
  exit 1
fi
echo "[1/6] Python: $PY"

# 2. venv + 依赖
[ -d .venv ] || "$PY" -m venv .venv
echo "[2/6] 安装依赖（首次需下载约 150 MB，请耐心；太慢可配置国内镜像："
echo "      ./.venv/bin/python -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple ）"
./.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
echo "[2/6] 虚拟环境与依赖就绪"

# 3. 冒烟测试
./.venv/bin/python verifiers/search/counterexample_search.py \
  --spec problems/_template/specs/c000_demo.json
./.venv/bin/python verifiers/gate.py --all
./.venv/bin/python -B -m unittest discover -s tests -q
echo "[3/6] 验证器、全树门禁与框架测试通过"

# 4. runner 配置
if [ ! -f runner/config.yaml ]; then
  cp runner/config.example.yaml runner/config.yaml
  echo "[4/6] 已生成 runner/config.yaml（默认 DeepSeek，可编辑换厂商）"
else
  echo "[4/6] runner/config.yaml 已存在，跳过"
fi

# 5. OpenCode（可选）
if [ "$SKIP_OC" = 1 ]; then
  echo "[5/6] 跳过 OpenCode（--skip-opencode）"
elif command -v opencode >/dev/null 2>&1; then
  echo "[5/6] OpenCode 已安装：$(command -v opencode)"
elif confirm "安装 OpenCode（开源终端 agent，官方安装脚本）？"; then
  curl -fsSL https://opencode.ai/install | bash
  echo "[5/6] OpenCode 安装完成（新开终端后 opencode 命令生效）"
else
  echo "[5/6] 跳过 OpenCode"
fi

# 6. API key
if [ "$YES" = 1 ]; then
  echo "[6/6] 跳过 key 设置（--yes 模式）"
elif [ -n "$DEEPSEEK_API_KEY" ]; then
  echo "[6/6] DEEPSEEK_API_KEY 已设置"
else
  echo "[6/6] 稍后请设置 API key，例如在 ~/.bashrc 或 ~/.zshrc 里加："
  echo '      export DEEPSEEK_API_KEY="sk-..."'
fi

echo ""
echo "=== 部署完成 ==="
echo "接下来（在本目录）："
echo "  用 OpenCode：   opencode"
echo "  用内置 runner： ./.venv/bin/python -m runner.main \"/lit 你的主题\""
echo "  用 Claude Code：claude"
echo "使用说明见 README.md，研究纪律见 CLAUDE.md。"
