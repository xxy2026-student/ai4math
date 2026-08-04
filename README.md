# ai4math

*A game-theory research agent framework: LLMs propose, deterministic verifiers dispose.*

面向博弈论研究的 AI4Math agent 框架。语言模型负责建模、检索文献、提出猜想与起草证明；确定性验证器（SymPy、nashpy、数值搜索）负责检验与背书；状态门禁确保二者永不混淆。同一套框架定义可运行于 Claude Code、OpenCode 或任意 OpenAI 兼容 API。

## 设计原则

框架围绕一条纪律构建：**模型提出，机器验证**。

- 任何数学断言在获得验证器背书之前，一律视为猜想；
- 猜想遵循状态机 `open → numeric-verified → proved`（或任意状态 → `refuted`），状态推进由门禁程序强制核验：
  - `numeric-verified` / `refuted` 必须由验证脚本的运行结果背书（`VERDICT` 协议），门禁在每次写入时重跑核验；
  - `proved` 必须存在 skeptic 角色的独立审计记录；
- 数值验证视为证据而非证明，写作时按状态分级措辞；
- 文献工作遵循同等纪律：禁止凭记忆引用，每条笔记必须记录来源 URL、访问日期与实际阅读层级。

纪律全文见 [CLAUDE.md](CLAUDE.md)。

## 功能

- **9 个研究工作流**：从抽象想法到 LaTeX 成稿的完整闭环（见下文）；
- **7 个分工角色**：modeler、scholar、referee、conjecturer、prover、skeptic、writer；评审与审计均在独立上下文中对抗式进行；
- **确定性验证层**：SymPy 符号验算、nashpy 均衡计算、随机参数反例搜索，统一 `VERDICT` 输出协议与 evidence 存档；
- **状态门禁**：对 `conjectures/`、`lemmas/` 的每次写入自动核验（[verifiers/gate.py](verifiers/gate.py)），三种运行时共用同一实现；
- **多运行时**：角色与工作流定义一份，多处运行，互不绑定。

## 快速开始

### 环境要求

- Windows 10/11，或 macOS / Linux
- Python 3.11+（Windows 下缺失时部署脚本可代为安装）

### 一键部署

克隆本仓库（或下载 ZIP 解压）后：

- **Windows**：双击 `setup.bat`
- **macOS / Linux**：`chmod +x setup.sh && ./setup.sh`

脚本依次完成：Python 检测/安装 → 创建虚拟环境并安装依赖 → 运行冒烟测试 →
生成 runner 配置 →（可选）安装 OpenCode →（可选）配置 API key。
脚本幂等，可重复运行；跳过 OpenCode 加 `-SkipOpenCode` / `--skip-opencode`。

<details>
<summary>手动安装（部署脚本不可用时）</summary>

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe verifiers/search/counterexample_search.py --spec problems/_template/specs/c000_demo.json
```

最后一行为冒烟测试，预期输出以 `VERDICT: PASS checked=300` 结尾。
macOS / Linux 将 `.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。

</details>

## 运行方式

角色、工作流与纪律全部定义于 `.claude/` 与 `CLAUDE.md`，以下方式共享同一套定义：

| 方式 | 适用场景 | 使用 |
|---|---|---|
| **Claude Code** | 持有 Claude 订阅或 API | 仓库目录内启动 `claude` |
| **Claude Agent SDK** | 以 Claude API 程序化调用 | 见 [examples/run_via_api.py](examples/run_via_api.py)；`setting_sources=["project"]` 为必填项 |
| **OpenCode** | 任意模型厂商，终端交互 | 安装 [OpenCode](https://opencode.ai) 后在仓库目录启动；适配层见下 |
| **内置 runner** | 任意 OpenAI 兼容 API，零额外依赖 | `.venv\Scripts\python.exe -m runner.main "/lit <主题>"` |
| **Anthropic 兼容端点** | 零代码试用 | 设 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` 后运行 Claude Code；非官方用法 |

### runner 配置

```
copy runner\config.example.yaml runner\config.yaml
```

在 `config.yaml` 中设置 `base_url` / `api_key_env` / `model` 三元组即可接入任意
OpenAI 兼容厂商（OpenAI、DeepSeek、Qwen、Gemini、本地 Ollama 等，文件内附端点列表）。
API key 一律通过环境变量传入，不写入任何文件。支持按角色映射不同厂商的模型；
将 prover 与 skeptic 配置为不同厂商可增强审计独立性。运行时对瞬时 API
错误（429/5xx）自动退避重试。

### OpenCode 适配层

仓库自带 `.opencode/`（角色、命令、状态门禁插件）与 `AGENTS.md`，OpenCode
用户开箱即用。这些文件由生成器从 `.claude/` 翻译而来——修改角色或工作流时只改
`.claude/`，然后重跑：

```
.venv\Scripts\python.exe adapters/gen_opencode.py
```

按角色指定模型参见 `adapters/opencode.models.json.example`。

## 研究工作流

| 命令 | 职能 |
|---|---|
| `/ground <想法>` | 抽象想法 → 文献侦察 → 候选形式化。新想法的入口 |
| `/review <想法>` | referee 独立评审想法：新颖性、重要性、可行性、张力 |
| `/revise <想法>` | 依据审稿意见或指示修订想法书，保留修订记录 |
| `/lit <主题或论文>` | 文献检索、精读笔记、引用线追踪 |
| `/explore <问题>` | 数值探索：均衡计算、参数扫描、现象汇总 |
| `/conjecture <问题>` | 从实验结果提炼猜想并做随机参数初检 |
| `/attack <猜想编号>` | prover 起草证明与 skeptic 搜索反例并行 |
| `/audit <猜想编号>` | 独立审计证明；通过后方可标记 `proved` |
| `/writeup <问题>` | 已验证结果整理为 LaTeX |

典型路径：`/ground → /review → /revise → /explore → /conjecture → /attack →
/audit → /writeup`。研究是循环而非流水线：`/lit` 可随时插入，任何阶段的产出
都可以打回上游（反例修正猜想、审稿意见修正想法、实验异常修正模型假设）。
每个想法在 `ideas/<想法名>/` 下拥有独立工作区，互不干扰。完整的格式演示样例见
[problems/_template/conjectures/C-000-demo.md](problems/_template/conjectures/C-000-demo.md)
（猜想 → spec → 谓词 → 验证器 → evidence 全链路）。

## 目录结构

```
.claude/          角色（agents/）与工作流（skills/）定义——唯一事实源
.opencode/        OpenCode 适配层（生成产物）
adapters/         适配层生成器
examples/         Claude Agent SDK 调用示例
runner/           内置执行器（OpenAI 兼容 chat.completions + function calling）
verifiers/        确定性验证器与状态门禁
problems/         研究问题工作区（_template/ 为模板与演示样例）
ideas/            研究想法工作区
literature/       文献笔记与文献地图
paper/            LaTeX 产出
CLAUDE.md         研究纪律全文（兼 Claude Code 规则文件）
AGENTS.md         OpenCode 规则文件（由 CLAUDE.md 生成）
```

所有研究产出均为纯文本（Markdown / JSON / Python），落盘于 `problems/`、
`ideas/`、`literature/`、`paper/`；agent 的跨会话记忆即这些文件本身。
`ideas/`、`literature/`、`problems/` 下除模板外默认不纳入版本控制
（见 `.gitignore`），以避免将个人研究内容随框架一同发布；如需在私有
fork 中对研究内容做版本管理，删除相应 ignore 规则即可。
