# ai4math — 博弈论研究 agent 框架

以 Claude Code 为运行时（订阅覆盖，无需 API 计费）的 AI4Math 研究框架：
Claude 负责建模、提猜想、写证明草稿；确定性验证器（SymPy / nashpy / 数值搜索）
负责背书；状态推进由 PostToolUse hook 强制核验。核心纪律见 [CLAUDE.md](CLAUDE.md)。

## 一次性安装

1. 安装 Python 3.11+（勾选 Add to PATH）
2. 建虚拟环境并装依赖：

   ```
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. 冒烟测试（预期最后一行 `VERDICT: PASS checked=300`）：

   ```
   .venv\Scripts\python.exe verifiers/search/counterexample_search.py --spec problems/_template/specs/c000_demo.json
   ```

## 日常使用

在本目录启动 `claude`，然后：

| 命令 | 作用 |
|---|---|
| `/ground <想法>` | 抽象想法 → 文献侦察 → 候选形式化（**新想法从这里进**） |
| `/lit <主题/论文>` | 文献检索、精读笔记、追引用线 |
| `/explore <问题>` | 数值探索：均衡计算、扫参、现象汇总 |
| `/conjecture <问题>` | 从实验提猜想并立即随机参数初检 |
| `/attack <C-编号>` | prover 证明 + skeptic 反例搜索并行 |
| `/audit <C-编号>` | 独立审计证明，通过才标 proved |
| `/writeup <问题>` | 已验证结果整理成 LaTeX |

两条入口：想法还抽象 → `/ground` 先做文献落地；模型已经能写下来 → 直接
`/explore`。新问题从 `problems/_template/` 的结构开始；
`problems/_template/conjectures/C-000-demo.md` 是一个完整的演示样例
（猜想格式 → spec → 谓词 → 验证 → evidence）。

## 五种驱动方式

角色、工作流、纪律全部定义在 `.claude/` 与 CLAUDE.md 里，五种方式跑的是同一个大脑：

1. **Claude 订阅**：本目录启动 `claude`（上文的用法，体验最完整）。
2. **Claude API**：`pip install claude-agent-sdk` + `ANTHROPIC_API_KEY`，
   见 [examples/run_via_api.py](examples/run_via_api.py)。
   注意 `setting_sources=["project"]` 是命门，不加则 `.claude/` 全部失效。
3. **任意厂商 API**（OpenAI / Gemini / DeepSeek / Qwen / 本地 Ollama…）：

   ```
   copy runner\config.example.yaml runner\config.yaml   # 填 base_url/model，key 放环境变量
   .venv\Scripts\python.exe -m runner.main "/explore my-problem 扫参数"
   ```

   runner 是约 300 行的模型无关执行器：读同一套 `.claude/` 定义，本地执行工具，
   写文件后直接调 `verifiers/gate.py` 过状态门禁。要求模型支持 function calling。
   支持按角色映射不同厂商（`runner/config.example.yaml` 有说明）——
   prover 与 skeptic 用不同厂商的模型可以增强审计独立性。
4. **OpenCode**（开源多模型 harness，MIT，75+ 厂商）：仓库自带 `.opencode/`
   适配层（agents、commands、状态门禁插件）与 `AGENTS.md`，装好
   [OpenCode](https://opencode.ai) 后在本目录启动即可，`/explore` 等命令与
   全部角色原样可用。`.opencode/` 由 `adapters/gen_opencode.py` 从 `.claude/`
   生成——改角色或工作流只改 `.claude/`，然后重跑生成器；按角色指定模型
   参考 `adapters/opencode.models.json.example`。
5. **零代码通道**：部分厂商提供 Anthropic 兼容端点（DeepSeek、GLM、Kimi 等），
   设 `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` 即可让 Claude Code 原样跑
   在他们的模型上。非官方用法，体验取决于对方模型的 agentic 能力。
