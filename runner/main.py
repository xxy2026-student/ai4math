"""AI4Research 通用 API 执行器 CLI，支持人类决策暂停与恢复。

首次使用：把 config.example.yaml 复制为 runner/config.yaml，填好厂商与
key 环境变量。然后在仓库根目录：

    .venv\\Scripts\\python.exe -m runner.main "/explore my-problem 扫参数看均衡结构"
    .venv\\Scripts\\python.exe -m runner.main --role scholar "精读 arXiv:xxxx.xxxxx 写笔记"
    .venv\\Scripts\\python.exe -m runner.main --decide D-... --choice revise --custom "缩小问题"
    .venv\\Scripts\\python.exe -m runner.main --resume D-...

（Linux/Mac 用 .venv/bin/python。）
"""
import argparse
import os
import sys

import yaml

from . import decisions
from .agent_loop import run_agent


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="AI4Research 通用 API 执行器")
    ap.add_argument("prompt", nargs="?",
                    help='任务或工作流命令，如 "/lit Bayesian persuasion 综述"')
    ap.add_argument("--role", default="orchestrator",
                    help="直接以某个角色运行（默认主协调 agent）")
    ap.add_argument("--config", default=None, help="配置文件（默认 runner/config.yaml）")
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--decide", metavar="DECISION_ID",
                        help="记录用户对一个暂停决策的明确选择")
    action.add_argument("--resume", metavar="DECISION_ID",
                        help="从已响应决策的完整 checkpoint 恢复")
    action.add_argument("--list-decisions", nargs="?", const="all",
                        choices=["all", "pending", "decided"],
                        help="列出全部/待决定/已决定的人类闸门")
    ap.add_argument("--choice", action="append", default=[],
                    help="选项 id；多选时重复传入")
    ap.add_argument("--custom", default="", help="自定义、组合或修订意见")
    ap.add_argument("--rationale", default="", help="用户选择理由（可选）")
    a = ap.parse_args()

    try:
        if a.list_decisions:
            status = None if a.list_decisions == "all" else a.list_decisions
            rows = decisions.list_decisions(status=status)
            if not rows:
                print("(没有匹配的决策)")
            for item in rows:
                req = item["request"]
                print(f"{req['decision_id']}\t{item['status']}\t"
                      f"{req['stage']}\t{req['question']}")
            return
        if a.decide:
            if not a.choice:
                ap.error("--decide 需要至少一个 --choice")
            result = decisions.record_response(
                a.decide, a.choice, custom_text=a.custom, rationale=a.rationale)
            print(decisions.render_card(result))
            print(f"\n已记录，不会覆盖。继续运行：python -m runner.main --resume {a.decide}")
            return
    except decisions.DecisionError as exc:
        sys.exit(f"决策操作失败：{exc}")

    initial_messages = None
    role = a.role
    if a.resume:
        try:
            checkpoint = decisions.load_checkpoint(a.resume)
            resume_text = decisions.build_resume_prompt(a.resume)
        except decisions.DecisionError as exc:
            sys.exit(f"恢复失败：{exc}")
        initial_messages = checkpoint["messages"] + [
            {
                "role": "tool",
                "tool_call_id": checkpoint["tool_call_id"],
                "content": resume_text,
            }
        ]
        role = checkpoint.get("role") or "orchestrator"
    elif not a.prompt:
        ap.error("需要 prompt，或使用 --decide/--resume/--list-decisions")

    path = a.config or os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(path):
        sys.exit("找不到配置文件：请把 runner/config.example.yaml 复制为 "
                 "runner/config.yaml 并填写厂商与 key 环境变量。")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    env = (cfg.get("default") or {}).get("api_key_env", "")
    if env and not os.environ.get(env):
        print(f"[警告] 环境变量 {env} 未设置，API 调用将失败。", file=sys.stderr)

    if a.resume:
        try:
            decisions.mark_resume_started(a.resume)
        except decisions.DecisionError as exc:
            sys.exit(
                "恢复失败：该 checkpoint 已经启动过，不能重复执行副作用。"
                f"如上次中断，请创建新的决策/检查点明确重试范围。详情：{exc}"
            )

    print(f"=== AI4Research runner · role={role} ===", flush=True)
    final = run_agent(cfg, role, a.prompt, initial_messages=initial_messages)
    print("\n=== 最终报告 ===\n" + (final or "(空)"))


if __name__ == "__main__":
    main()
