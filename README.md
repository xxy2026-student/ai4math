# AI4Research

> 仓库名暂时保留为 `ai4math`，以兼容既有链接、安装脚本和配置；项目定位已经从“自动证明数学定理”调整为“人机协作解决研究问题”。博弈论与数学研究是当前重点场景，但不是能力边界。

AI4Research 帮助研究者把一个模糊想法推进为可检查的研究成果：界定问题、检索文献、比较方向、设计模型或实验、收集证据、审计主张并形成写作材料。LLM 负责提出建议、执行获批工作和暴露不确定性；人类研究者负责问题价值、研究方向、关键取舍、证据解释和最终发布。

Lean 可以作为未来的可选形式证明通道，但不是项目中心，也不是所有研究问题的完成条件。当前仓库**尚未实现 Lean 编译与证据绑定**，所以 gate 会拒绝直接声明 `formal: lean-verified`；在真正接入 Lean/Lake/mathlib、锁定依赖并保存编译证据前，应保持 `formal: not-requested`（或如实记 `failed`）。数值实验、数据分析、文献证据、反例、定性访谈、人工推导和形式证明都可以进入证据包；它们各自能支持什么结论，必须如实说明。

## 核心原则

1. **先解决值得解决的问题。** 不把“生成一个定理”当作默认目标；先明确研究问题、成功标准、非目标和可证伪条件。
2. **人类决定，LLM 建议并执行。** 关键分叉必须暂停，展示开放式决策卡，等待人类明确选择；沉默不等于批准。
3. **主张与证据分开。** 实验通过、审计文件存在或 Lean 编译成功，只说明对应证据通道通过，不自动把更宽泛的研究主张变成事实。
4. **产物可追溯。** 关键 artifact 版本化，记录来源、假设、决策和依赖；上游修改后，下游产物先标记为 `stale`，不得静默沿用。
5. **批准有边界。** 一次批准应包含明确的 scope、预算、版本和失效条件；在批准范围内连续执行，不反复打断。超出范围、证据冲突或外部发布时重新询问。

完整研究纪律见 [CLAUDE.md](CLAUDE.md)。

## 五个必经人类门

| 门 | 何时暂停 | 人类决定什么 |
|---|---|---|
| `PROBLEM_GATE` | 初版问题章程完成后 | 问题是否值得做、边界、成功标准、非目标 |
| `DIRECTION_GATE` | 文献落地与独立评审后 | 采用、组合、修订或放弃哪条研究方向 |
| `DESIGN_GATE` | design/spec/pilot 方案与代码准备好后、首次执行前 | 方法、基线、指标、资源预算与 pilot/正式执行范围 |
| `CLAIM_GATE` | 结果、反例和独立审计汇总后 | 主张措辞、证据强度、是否补实验或收缩结论 |
| `RELEASE_GATE` | 对外共享、提交、发布或推送前 | 发布版本、受众、渠道和仍需披露的限制 |

每张决策卡都必须包含：LLM 的推荐选项、置信度与理由、证据与未知、最强反对意见、2–4 个有实质差异的开放选项，以及“自定义/组合方案”。选项不能预选；没有明确回复时工作流保持暂停。

内置 runner 把五门实现为有顺序的状态链：除首个 `PROBLEM_GATE` 外，新阶段必须用 `parent_decision_id` 连接已回复且允许继续的上一阶段，不能从问题门直接跳到设计、主张或发布。同阶段重问也必须引用上一条真实回复。`CLAIM_GATE` 的每个选项另带机器字段 `claim_disposition`；只有映射为 `accepted-with-scope` 的选项可以列入 `authorizing_option_ids`，因此“修订/拒绝”回复不能被改写成“接受”，反之亦然。

此外，以下情况会触发条件门：核心范围、假设或指标发生变化；请求远程资源、付费服务、敏感数据或外部通信；不同审查意见实质冲突；依赖 artifact 已过期；准备覆盖、删除或发布内容。

## 工作流

| 命令 | 作用 | 关键人类门 |
|---|---|---|
| `/ground <想法>` | 建立问题章程、文献坐标与候选路线 | `PROBLEM_GATE` |
| `/lit <主题或论文>` | 有目的地检索、精读和维护证据地图 | 条件门（扩大检索边界时） |
| `/review <想法>` | 独立评估新颖性、价值、可行性和风险 | 为 `DIRECTION_GATE` 提供输入 |
| `/revise <想法>` | 生成可比较修订方案并保留版本历史 | 重大修订触发 `DIRECTION_GATE` |
| `/explore <问题>` | 设计实验与 pilot，获批后运行并估算正式资源 | `DESIGN_GATE` |
| `/conjecture <问题>` | 把结果提炼为可证伪的假设或候选主张 | 重大方向变化触发条件门 |
| `/attack <主张>` | 证明、反例、稳健性和替代解释并行压力测试 | 为 `CLAIM_GATE` 提供输入 |
| `/audit <主张>` | 独立审计完整证据包与推理链 | `CLAIM_GATE` |
| `/writeup <问题>` | 按获批主张形成稿件，检查复现与措辞 | `RELEASE_GATE` |
| `/decide <决策>` | 展示或记录人类决策；不替人类选择 | 对应当前门 |

典型路径是：

```text
想法 → 问题章程 → PROBLEM_GATE
     → 文献/评审/候选方向 → DIRECTION_GATE
     → 设计 + pilot 计划/代码 → DESIGN_GATE
     → 获批 pilot/实验/分析/压力测试/审计 → CLAIM_GATE
     → 写作与复现检查 → RELEASE_GATE
```

研究不是单向流水线。反例、文献重合、异常结果或审计失败都可以把工作送回上游；回退时创建新版本，并将依赖旧版本的产物标为 `stale`。

## 证据与主张

候选主张把机器可检查状态、人类处置和可选形式验证分成三个正交轴。`status` 使用：

- `open`：待检验；
- `evidence-supported`：在声明范围内获得可复现证据，但仍可能被推翻；
- `reviewed`：结构化独立审计为 PASS，且 gate 已核对 claim/problem/`claim_review_hash`、audit/evidence/spec/predicate/verifier 内容哈希；任一绑定内容变化会使旧审计失效；不等同于普遍意义上的“证明”，也不表示人类同意采用；
- `refuted`：找到可复现的反证或关键证据否定；
- `abandoned`：经人类决定不再继续，保留原因和历史。

人类在 CLAIM_GATE 的处置另记为 `human_disposition: pending | accepted-with-scope | revise | reject`，并用 `decision` 指向不可变回复。gate 会读取对应 request/response，核对阶段、内容哈希、实际选项及其 `claim_disposition`；`D-fake` 之类的空引用不能通过。只有 `accepted-with-scope` 才允许按其中 scope 进入写作；审计 PASS 本身不能替代人类选择。

形式证据也与上述两轴正交；`formal: lean-verified` 当前是保留值且会被 gate 拒绝，直到项目接入可机器核验的 Lean 编译证据。即使未来通过，也不会自动把更宽的研究主张改为 `reviewed` 或 `accepted-with-scope`。

当前 `gate.py` 机器核验 evidence/audit、`status` 以及非 pending claim 引用的本地 decision 实体，内置 runner 负责暂停并记录真实交互中的人类选择。若私有研究内容要进入 CI，相关 decision 记录也必须在受控环境中可用，否则非 pending claim 会被拒绝。请求/回复有内容哈希和不可覆盖约束，但目前不是带人类身份签名的安全边界；公开或高风险流程仍需仓库权限、签名审阅或组织审批来增强 provenance。

可选证据通道包括：

- 数值搜索或模拟，附参数、seed、环境和 evidence 文件；
- 数据分析或实证实验，附数据版本、指标与基线；
- 文献证据，附可访问来源和实际阅读层级；
- 人工推导与独立审计，显式标注 GAP 和依赖假设；
- Lean/Lake/mathlib 形式化，适用于确实需要机器检查定理的子任务。

任何单一通道都不能自动外推到未检验的人群、参数区间、数据集或研究问题。

## 快速开始

环境要求：Windows 10/11、macOS 或 Linux，Python 3.11+。

完整的克隆、API Key、Windows/macOS/Linux 安装、验证、升级与故障排查说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。

- Windows：双击 `setup.bat`
- macOS / Linux：运行 `chmod +x setup.sh && ./setup.sh`

手动安装：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy runner\config.example.yaml runner\config.yaml
```

macOS/Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`。

## 运行方式

角色、工作流和纪律的单一事实源位于 `.claude/` 与 `CLAUDE.md`，可供多种运行时使用：

| 方式 | 使用 |
|---|---|
| Claude Code | 在仓库目录运行 `claude` |
| Claude Agent SDK | 参考 `examples/run_via_api.py`；轻量、非持久化示例，真正的 pause/resume 请用内置 runner |
| OpenCode | 在仓库目录运行 `opencode`；命令和角色由适配器生成 |
| 内置 runner | `.venv\Scripts\python.exe -m runner.main "/ground <主题>"` |

内置 runner 遇到人类门会保存不可变决策请求和对话检查点后退出。查看、答复并恢复：

```powershell
.venv\Scripts\python.exe -m runner.main --list-decisions pending
.venv\Scripts\python.exe -m runner.main --decide <decision-id> --choice <option-id> --rationale "原因"
.venv\Scripts\python.exe -m runner.main --resume <decision-id>
```

选择现有选项不是强制的；使用 `--choice custom --custom "你的方案"` 提交自定义或组合方案。自定义回复会恢复讨论，但默认不产生机器执行权；需要执行时，系统先把它澄清成带精确 envelope 的新决策。决策记录一经写入不覆盖；每个 envelope 还受 `max_uses` 限制并留下动作指纹凭据，同一 checkpoint 只能开始恢复一次。若恢复后的 API 调用失败，也应创建新决策，而不是重复消费旧 checkpoint。结构和隐私说明见 [decisions/README.md](decisions/README.md)。

runner 不向模型暴露任意 shell。方向获批后可以编写 design/spec/predicate/实验脚本供人审阅；真正运行问题实验或验证器必须再经过顺序相连的 `DESIGN_GATE`。被执行的实验脚本或固定 verifier driver，以及 spec 和 predicate，必须全部出现在 decision 的 `context_paths` 中并保持精确内容哈希；它们与 evidence 输出路径也必须全部落在 `authorized_paths`。动作收据保存完整 manifest、驱动/输入哈希、参数、预算和消费序号。模型工具只可运行 `gate.py --all --structure-only`，会执行仓库代码的完整 gate 留给用户或 CI。问题 grounding、model、claim 接受和 paper 写入也分别由 `PROBLEM_GATE`、`DIRECTION_GATE`、`CLAIM_GATE` 机器拦截。`runner/`、`verifiers/`、`remote/`、决策记录、hooks 等框架控制面不允许模型文件工具改写。普通文件写入只运行无代码执行的结构/内容哈希门禁，避免一次无关 Markdown 写入偷偷启动实验。它缩小了误操作面，但仍不是针对恶意仓库代码的操作系统沙箱。

修改 `.claude/agents/`、`.claude/skills/` 或 `CLAUDE.md` 后，重新生成 OpenCode 适配层：

```powershell
.venv\Scripts\python.exe adapters/gen_opencode.py
```

## 目录结构

```text
.claude/          角色与工作流的单一事实源
.opencode/        OpenCode 适配层（生成产物；插件除外）
adapters/         适配层生成器
runner/           OpenAI 兼容 API runner 与暂停/恢复控制流
decisions/        人类决策请求、回复与检查点（默认不提交个人记录）
ideas/            问题章程、grounding、评审和修订历史
literature/       可追溯文献笔记与地图
problems/         模型、设计、实验、证据、主张和审计
verifiers/        证据验证器与状态门
remote/           经批准后使用的远程实验执行器
paper/            获批主张对应的写作产物
```

研究产物默认是 Markdown、JSON、Python 和 LaTeX。公开模板与示例纳入仓库；个人研究内容和决策记录默认忽略。如需在私有 fork 中版本管理，可按项目数据政策调整 `.gitignore`，但不要提交密钥、敏感数据或未经同意的私人反馈。
