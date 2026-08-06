---
id: C-000
problem: _template
version: v1
based_on: problems/_template/model.md
status: evidence-supported
human_disposition: pending
decision: null
formal: not-requested
verify:
  script: verifiers/search/counterexample_search.py
  args: --spec problems/_template/specs/c000_demo.json
evidence: problems/_template/results/c000_evidence.json
---

# C-000（演示）：2×2 共同利益协调博弈的完全混合均衡

**陈述**：对任意 a, b ∈ [0.1, 5]，双矩阵博弈 A = B = diag(a, b)
（对角线支付 a、b，非对角为 0）存在唯一完全混合 Nash 均衡，
且其中玩家 1 选第一个行动的概率为 p* = b/(a+b)。

**依赖假设**：无（自包含演示）。

**价值**：无——本文件是框架冒烟测试与格式样例，展示
研究主张 → spec → 谓词 → 有界检查 → evidence → status 的完整链路。
（手算验证：玩家 2 在混合均衡中对两行动无差异 ⟺ p·a = (1−p)·b ⟺ p = b/(a+b)。）

## 当前证据与边界

注册验证器在 spec 声明的有限参数域内随机检查 300 个样本；当前未找到反例。
这只支持 `evidence-supported`，不等价于定理证明，也不排除采样点之外存在反例。
若需要更强结论，应另行提供解析论证、形式化证明或更有针对性的压力测试，
并由结构化独立审计记录其审查范围。
