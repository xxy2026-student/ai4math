---
name: conjecture
description: 从数值实验结果提炼猜想并立即做随机参数初检。用法：/conjecture <问题名> [基于哪次实验/关注方向]
---

# /conjecture — 提猜想并初检

输入：$ARGUMENTS

步骤：

1. 派 **conjecturer** subagent 读 `problems/<p>/results/` 与 model.md，
   产出候选猜想文件（`conjectures/C-xxx.md`，status: open，附检验方案）。
2. 对每条候选猜想，主 agent：
   - 写 spec JSON 到 `problems/<p>/specs/`（参数范围、n_samples ≥ 1000、seed）；
   - 写谓词脚本到 `problems/<p>/predicates/`（`check(params) -> bool`）；
   - 跑 `verifiers/search/counterexample_search.py --spec ...`。
3. 按结果推进状态（hook 会重跑核验，确保 frontmatter 的 verify 字段先填好）：
   - `VERDICT: PASS` → status: numeric-verified，evidence 路径写入 frontmatter；
   - `VERDICT: REFUTED` → status: refuted，反例参数与复现命令记入
     `counterexamples/`，并让 conjecturer 看反例——常能改出一条收缩版猜想。
4. 汇报：存活猜想清单（各自价值、建议先 /attack 哪条）、被推翻的及其反例。
