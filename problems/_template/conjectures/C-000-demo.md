---
id: C-000
problem: _template
status: numeric-verified
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
猜想 → spec → 谓词 → 验证器 → evidence → status 的完整链路。
（手算验证：玩家 2 在混合均衡中对两行动无差异 ⟺ p·a = (1−p)·b ⟺ p = b/(a+b)。）

## 证明草稿

（略。真实猜想中由 prover 在此写草稿：每步标注依赖假设/引理，
卡住处显式写 [GAP: ...]，通过 /audit 后才能标 proved。）
