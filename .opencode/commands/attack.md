---
description: "对一条猜想双线作战：prover 写证明草稿、skeptic 设计反例搜索，两者并行。用法：/attack <C-编号或猜想文件路径>"
---

<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->

# /attack — 证明与反例并行

输入：$ARGUMENTS

1. 定位猜想文件，确认 status 是 open 或 numeric-verified。
2. **同一条消息里并行派出**两个 subagent：
   - **prover**：写证明草稿（写入猜想文件 `## 证明草稿`，GAP 显式标注）；
   - **skeptic**：设计刁钻参数区域的反例搜索方案（spec + 谓词要点）。
3. skeptic 方案回来后，主 agent 生成 spec/谓词并跑
   `counterexample_search.py`（针对边界区域可多跑几个 spec）。
4. 汇合裁决：
   - **找到反例** → status: refuted，反例记入 `counterexamples/`；证明草稿
     保留在文件里并加注 "已被反例推翻"——草稿哪一步与反例冲突，本身是信息。
   - **草稿完整（无 GAP）且反例搜索通过** → 提示用户跑 `/audit`。
     **禁止在本 skill 内把 status 改成 proved。**
   - **草稿有 GAP** → 把每个 GAP 列为子问题，建议：可数值检验的先
     /conjecture 化，纯逻辑的开新一轮 /attack。
5. 汇报：裁决结果、GAP 清单或反例、建议的下一步。
