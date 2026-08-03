---
name: writeup
description: 把一个问题的已验证结果整理成 LaTeX 论文素材。用法：/writeup <问题名> [目标形态：note / section / full paper]
---

# /writeup — 成文

输入：$ARGUMENTS

1. 盘点 `problems/<p>/`：
   - proved 的引理与定理（lemmas/ + 对应审计）；
   - numeric-verified 的观察（含 evidence 路径与 seed）；
   - 有信息量的 refuted 猜想（反例）。
2. 派 **writer** subagent 产出 LaTeX 到 `paper/<p>/`，遵守其措辞分级纪律。
3. 若本机有 LaTeX 环境则编译检查；没有就做括号/引用/环境配对的静态检查。
4. 汇报：产出文件清单 + 差距分析——哪些关键命题还停在 numeric-verified
   （成文前需要 /attack + /audit 补证明），哪些 open 问题值得写进 future work。
