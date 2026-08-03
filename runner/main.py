"""通用 API 执行器 CLI。

首次使用：把 config.example.yaml 复制为 runner/config.yaml，填好厂商与
key 环境变量。然后在仓库根目录：

    .venv\\Scripts\\python.exe -m runner.main "/explore my-problem 扫参数看均衡结构"
    .venv\\Scripts\\python.exe -m runner.main --role scholar "精读 arXiv:xxxx.xxxxx 写笔记"

（Linux/Mac 用 .venv/bin/python。）
"""
import argparse
import os
import sys

import yaml

from .agent_loop import run_agent


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="ai4math 通用 API 执行器")
    ap.add_argument("prompt", help='任务或工作流命令，如 "/lit Bayesian persuasion 综述"')
    ap.add_argument("--role", default="orchestrator",
                    help="直接以某个角色运行（默认主协调 agent）")
    ap.add_argument("--config", default=None, help="配置文件（默认 runner/config.yaml）")
    a = ap.parse_args()

    path = a.config or os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(path):
        sys.exit("找不到配置文件：请把 runner/config.example.yaml 复制为 "
                 "runner/config.yaml 并填写厂商与 key 环境变量。")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    env = (cfg.get("default") or {}).get("api_key_env", "")
    if env and not os.environ.get(env):
        print(f"[警告] 环境变量 {env} 未设置，API 调用将失败。", file=sys.stderr)

    print(f"=== ai4math runner · role={a.role} ===", flush=True)
    final = run_agent(cfg, a.role, a.prompt)
    print("\n=== 最终报告 ===\n" + (final or "(空)"))


if __name__ == "__main__":
    main()
