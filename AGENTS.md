<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->

# ai4math — 博弈论研究 agent 框架

这是一个 AI4Math 研究仓库。你（Claude）在这里是研究助理，必须服从以下纪律。

## 铁律：猜想与验证分离

1. **任何数学断言在没有验证器背书前一律是猜想。** 禁止在任何文件里把未验证断言写成事实。
2. 猜想状态机（frontmatter 的 `status` 字段）：

   ```
   open → numeric-verified → proved
     └──────────┴──→ refuted
   ```

   - `numeric-verified` / `refuted`：只能由 `verifiers/` 下的脚本运行结果推进。frontmatter 必须填 `verify.script` / `verify.args`，PostToolUse hook 会**重跑验证器核验**，VERDICT 与 status 不一致会被打回。
   - `proved`：需要 skeptic 审计通过，frontmatter 的 `audit` 字段指向审计文件（hook 核验其存在）。审计前禁止标 proved。
3. **数值验证是证据，不是证明。** 写作中 `numeric-verified` 的结果只能表述为 "numerical evidence suggests"，禁止写成定理。

## 目录约定

```
problems/<问题名>/
  model.md          形式化模型：players、时序、信息结构、支付、解概念、编号假设 A1...
  conjectures/      猜想，一条一个文件（格式见下）
  lemmas/           已证结果卡片（只允许 status: proved）
  audits/           skeptic 的审计记录
  counterexamples/  被推翻猜想的反例参数与复现说明
  specs/            验证器的 spec JSON
  predicates/       猜想谓词脚本 check(params) -> bool
  experiments/      探索性实验脚本
  results/          实验摘要与 evidence JSON（摘要，不放原始数据）
ideas/              抽象想法与落地报告（/ground 的工作区，见 _template.md）
literature/
  papers/           单篇精读笔记，一篇一个文件（frontmatter 含 url/accessed/access-level）
  maps/             文献地图：论断必须标 [bibkey]，bibkey 必须在 papers/ 有笔记
verifiers/          确定性验证器（详见各文件 docstring）；gate.py 是状态门禁核心
runner/             通用 API 执行器：任意 OpenAI 兼容厂商，读同一套 .claude/ 定义
paper/              LaTeX 产出
```

## 猜想文件格式

```markdown
---
id: C-001
problem: <问题名>
status: open            # open | numeric-verified | proved | refuted
verify:
  script: verifiers/search/counterexample_search.py
  args: --spec problems/<p>/specs/c001.json
evidence: problems/<p>/results/c001_evidence.json
audit: problems/<p>/audits/C-001-audit-2026-08-03.md   # 仅 proved 需要
---

# C-001：<一句话标题>

**陈述**：（精确的数学命题，含参数范围）
**依赖假设**：A1, A3
**价值**：（若为真，对主定理/论文的意义）

## 证明草稿
（prover 写；每步标注依赖，卡住处写 [GAP: ...]）
```

## 工作流（skills）

- `/ground <想法>` — 抽象想法 → 文献侦察 → 候选形式化。**新想法的入口**，
  产出经用户拍板后交给 modeler 变成 model.md
- `/lit <主题/论文>` — 文献检索、精读笔记、追引用线
- `/explore <问题>` — 数值探索：均衡计算、扫参、现象汇总
- `/conjecture <问题>` — 从实验结果提猜想 + 立即随机参数初检
- `/attack <C-编号>` — prover 证明与 skeptic 反例搜索**并行**
- `/audit <C-编号>` — skeptic 独立审计，通过才能标 proved
- `/writeup <问题>` — 已验证结果整理成 LaTeX

## 验证器协议

每个验证器最后必须打印一行 `VERDICT: PASS ...`、`VERDICT: REFUTED ...` 或
`VERDICT: ERROR ...`，并把细节写入 evidence JSON。hook 依赖这一行核验。

## 引用纪律

文献幻觉与数学错误同罪，用同样的验证思路管：

- **禁止凭记忆引用。** 记忆中的论文只是检索线索，必须当场抓取来源核实
  （frontmatter 记 url + accessed + access-level）后才能写进 `literature/`。
- `access-level: secondhand`（未读原文）的论文不得支撑任何具体论断。
- 文献地图与 grounding 报告里的每个论断标 [bibkey]；bibkey 必须能在
  `literature/papers/` 找到对应笔记。
- 新颖性声明只能表述为「在检索范围内未见」并附检索线清单，
  禁止断言「文献中不存在」。

## 环境与额度习惯

- Python 虚拟环境在 `.venv/`，验证器与实验一律用 `.venv\Scripts\python.exe` 运行。
- 长时间数值实验放后台 Bash 跑；脚本只输出**摘要**（统计量、现象、违反点参数），
  禁止向对话里 dump 原始数组——计算不花 token，读原始数据才花。
- 每个 session 专注一件事，结论落盘到 `problems/`；跨 session 记忆靠文件，不靠长对话。
- skeptic 审计必须在独立 context 进行：只给证明文本，不给 prover 的推理过程。
