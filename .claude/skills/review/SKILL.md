---
name: review
description: referee 以审稿人视角独立评审一个研究想法（新颖性/重要性/可行性/张力），产出审稿意见。用法：/review <想法名>
---

# /review — 想法评审

输入：$ARGUMENTS

1. 定位 `ideas/<想法名>/`。派 **referee** subagent，输入**只给**：
   idea.md、grounding.md、map.md（如有多轮评审，可附上一轮意见供对比）。
   不要转述你或用户对想法的看法——评审的价值全在独立性。
2. referee 把审稿意见写入 `ideas/<想法名>/reviews/review-<日期>.md`
   （每轮新开文件，不覆盖旧的，形成评审历史）。
3. 意见原样汇报给用户；你有不同意见可以附，但必须标明「这是主 agent
   的观点，非评审结论」。
4. 后续动作交用户决定：改想法 → /revise；补文献 → /lit；
   直接形式化 → /explore；放弃 → idea.md 的 status 改为 abandoned 留档。
