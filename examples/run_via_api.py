"""用 Claude API（Agent SDK）驱动本框架，不需要 Claude 订阅。

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
            permission_mode="acceptEdits",    # 无人值守；状态纪律由 hook_gate 兜底
        ),
    ):
        print(msg)


anyio.run(main)
