---
name: review
description: 独立评审候选研究路线，主 agent 综合后通过 DIRECTION_GATE 由人类拍板。用法：/review <想法名>
---

# /review — 独立评审与方向决策

输入：$ARGUMENTS

1. 定位 `ideas/<name>/`，确认 `idea.md` 已通过 PROBLEM_GATE，并记录待评审的 idea/grounding/map 版本。
2. 派 **referee** 独立评审。只给它上述 artifact，不转述主 agent 或用户倾向；多轮评审可附旧评审供差异比较。
3. referee 写入新的 `reviews/review-<日期>-<编号>.md`，不得覆盖历史。评审至少覆盖问题价值、新颖性、可行性、识别/外部效度、风险、替代方向与会改变意见的证据。
4. 主 agent 单独写综合：哪些是评审事实、哪些是自己的推断；明确处理冲突，给出自己的推荐、置信度和最强反对意见。不得把 referee 的总评直接当作决定。

## `DIRECTION_GATE`

调用 `/decide` 或 `request_human_decision`，stage=`direction`。提供 2–4 个有实质区别的方向选项，例如：采用推荐路线、组合两条路线、先补关键证据、停止该想法；始终允许自定义/组合。每项列明收益、风险、成本、会建立或作废的 artifact。

envelope 应写明：获批的 idea/grounding/map 版本、研究路线、允许 modeler 固化的范围、下一阶段 pilot 边界，以及假设/数据/目标变化等失效条件。没有明确回复不得创建“已选定”的 model 或进入正式探索。

人类决定后记录 decision id。获批路线交给 modeler；未选路线保留为 rejected/deferred 历史而不删除。重大方向修订必须产生新版并重新走 DIRECTION_GATE。
