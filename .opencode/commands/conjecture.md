---
description: "从获批设计的结果中提出可证伪假设/候选主张，并做独立初检。用法：/conjecture <问题名> [结果或关注方向]"
---

<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->

# /conjecture — 候选主张组合

输入：$ARGUMENTS

这里的“conjecture”泛指可证伪研究假设，不要求是数学定理。

1. 确认 model/design 和输入 results 版本均 active，且结果来自获批 DESIGN_GATE envelope。stale 或设计外结果只能标为探索性证据。
2. 派 **conjecturer** 产生 2–4 条精确候选主张；主张分别写入 `conjectures/C-xxx.md`，初始 `status: open`。每条写：适用范围、依赖、价值、可能的替代解释、证伪方法和最合适的证据通道。
3. 由不同上下文的 checker 做初检：机械谓词/数值搜索、保留集测试、文献交叉核对、反例构造或人工推导。不要让提案者自评通过。
4. 可复现证据通过且绑定 exact claim/spec/evidence 版本时，可标 `evidence-supported`；发现反例则标 `refuted` 并保存复现。两者都不是 `reviewed`，也不自动触发写作。
5. 汇报候选组合：预期价值、证据强弱、最大风险、建议优先压力测试哪条及最强反对意见。

若候选主张会实质改变获批方向、成功指标或资源需求，先触发条件门，提供 2–4 个路线与自定义项；在原批准范围内的普通主张初检无需逐条打断。

形式命题未来可选用 Lean 通道；当前项目尚未实现编译证据绑定，gate 会拒绝 `formal: lean-verified`。只有真正接入并在锁定版本/依赖下编译通过后才能开放该值；它与 `status: reviewed` 正交，也不能替代 CLAIM_GATE。
