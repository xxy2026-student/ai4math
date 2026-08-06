---
description: "独立审计候选主张的完整证据包，并通过 CLAIM_GATE 让人类决定可接受措辞。用法：/audit <主张编号或路径>"
---

<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->

# /audit — 证据与推理独立审计

输入：$ARGUMENTS

1. 冻结待审对象：claim 陈述与版本、model/design/spec/results/evidence、反例、复现说明和可选推导/Lean artifact。任何 stale 依赖先返回上游。
2. 派 **skeptic** 独立审计。只提供冻结证据包，不附提案者隐藏推理或主 agent 倾向。
3. skeptic 写新的 `audits/<claim-id>-audit-<日期>-<编号>.md`，不覆盖旧审计。逐项检查：身份/版本绑定、设计遵从、复现、统计/逻辑有效性、边界、替代解释、文献支撑、限制与措辞。PASS 必须记录 gate 计算的 `claim_review_hash`；若使用 evidence，还须记录其路径与 `evidence_sha256`。claim 再记录整个审计文件的 `audit_sha256`。正文、假设、依赖、证据或审计任一内容变化都会失效；仅复用同一个 id/路径不够。
4. 审计结论：
   - `PASS`：在所审版本和限定措辞下无已知阻断问题；
   - `CONDITIONAL`：列出必须满足的收缩或补证条件；
   - `FAIL`：列出致命漏洞、反例或不可复现点。

审计结论不是人类批准；文件存在也不表示 PASS。结构化 PASS 与 exact claim/problem/`claim_review_hash` 以及引用证据的内容哈希绑定后，主流程可写 `status: reviewed`，由 gate 机器校验。当前 `formal: lean-verified` 会被 gate 拒绝；未来即使接入了 Lean，模型有效性和更宽结论的范围仍需独立审计。

## `CLAIM_GATE`

主 agent 综合证据与审计后调用 `/decide` 或 `request_human_decision`，stage=`claim`。必须给自己的推荐、置信度/理由、证据与未知、最强反对意见，以及 2–4 个开放选项，例如：

- 接受限定措辞，记 `human_disposition: accepted-with-scope`；
- 收缩 claim 后重新审计，记 `human_disposition: revise`；
- 补指定证据/复现，记 `human_disposition: revise`；
- 不采用该主张，记 `human_disposition: reject`；
- 自定义/组合方案。

envelope 写明获批 claim/audit/evidence 的精确版本、可用于写作的原句/范围、必须披露的限制和失效条件。无人类明确回复时保持 `human_disposition: pending` 并暂停；自定义回复不能无歧义映射时先澄清。

`status: reviewed` 只表示结构化独立审计 PASS，**不是 proof，也不是人类批准**。CLAIM_GATE 只改变正交的 `human_disposition` 并写 `decision`；只有 `accepted-with-scope` 才允许进入写作。`formal: lean-verified` 目前是保留值且会被 gate 拒绝，直到项目真正接入 Lean 编译证据；三轴互不替代。

当前 gate 能机器校验审计状态，runner 能记录不可覆盖、内容哈希绑定的人类回复；它们尚不是带人类身份数字签名的安全边界，报告中不得过度声称。
