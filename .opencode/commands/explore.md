---
description: "对一个博弈论问题做数值探索：计算均衡、扫参数、汇总现象。用法：/explore <问题名或新问题描述> [关注点]"
---

<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->

# /explore — 数值探索

输入：$ARGUMENTS

步骤：

1. 若 `problems/` 下没有该问题目录：先派 **modeler** subagent 建
   `problems/<p>/model.md`（按 `_template` 结构，目录也按 _template 建全）。
   modeler 报告的「待澄清」项先问用户确认，再继续。
2. 依据 model.md 写实验脚本，放 `problems/<p>/experiments/`，用
   `.venv\Scripts\python.exe` 运行：
   - 双人有限博弈用 nashpy（support enumeration / Lemke-Howson）；
   - 连续策略 / 一般均衡用 scipy 解 FOC 或不动点迭代；
   - 扫参数先粗网格找现象，再对可疑区域细化。
3. **资源评估门**：全量实验前先跑 pilot（约全量的 1/100）实测单位成本，
   外推总时长与内存，分级处置：
   - 预计 **< 15 分钟** → 本地后台直接跑，事后告知；
   - 更大 → 停下来向用户报告评估（预计时长/内存/建议），由用户决定：
     本地慢慢跑，还是上服务器。**未经用户确认，禁止向服务器提交任务**；
   - 服务器路径：`remote/remote_run.py` 的 check → push → setup → run →
     status → fetch（用法见其 docstring；fetch 只拉回摘要与 evidence，
     原始大数据留在远端）。评估拿不准时宁可高估成本。
4. 本地实验预计超过一两分钟的放**后台 Bash** 跑。无论本地还是远端，脚本
   只输出摘要（统计量、单调性、相变点、异常参数），写入
   `problems/<p>/results/<日期>-<主题>.md`，不要向对话 dump 原始数组。
5. 汇报：观察到的规律、反直觉现象、值得 /conjecture 的方向。只汇报，
   不在本 skill 内创建猜想文件。
