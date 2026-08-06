"""用 Claude API（Agent SDK）驱动本框架，不需要 Claude 订阅。

这是轻量示例，不保存可恢复的人类决策 checkpoint。需要五个闸门的持久暂停/恢复时，
请使用 ``python -m runner.main``；本示例遇到决策卡应由人类回复后再启动下一轮。

前置：Python 3.10+、Node.js 18+，然后
    pip install claude-agent-sdk
    设置环境变量 ANTHROPIC_API_KEY

在仓库根目录运行：
    python examples/run_via_api.py "/explore my-problem 扫参数看均衡结构"
"""
import sys

import anyio
from claude_agent_sdk import ClaudeAgentOptions, query


async def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else "/lit Bayesian persuasion 综述"
    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=".",                          # 仓库根目录
            setting_sources=["project"],      # 关键：不加这行 .claude/ 与 CLAUDE.md 全部失效
            system_prompt={"type": "preset", "preset": "claude_code"},
        ),
    ):
        print(msg)


anyio.run(main)
