"""Claude Code PostToolUse hook 薄壳：解析 hook 协议 → 调 gate.check_file。

核心规则在 gate.py（与通用 API runner 共用同一实现）。
违规 → exit 2，stderr 反馈给 Claude 修正。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate import check_file  # noqa: E402


def main():
    try:
        evt = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", "replace") or "{}")
    except json.JSONDecodeError:
        sys.exit(0)
    fp = (evt.get("tool_input") or {}).get("file_path") or ""
    if not fp:
        sys.exit(0)
    ok, msg = check_file(fp, root=os.getcwd())
    if not ok:
        sys.stderr.write("[hook_gate] " + msg + "\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
