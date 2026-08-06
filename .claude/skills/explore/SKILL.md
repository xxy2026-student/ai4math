---
name: explore
description: 为获批研究问题设计实验/分析，先准备可审阅的 pilot，再经 DESIGN_GATE 执行。用法：/explore <问题名或描述> [关注点]
---

# /explore — 研究设计、pilot 与正式执行

输入：$ARGUMENTS

1. 检查对应 PROBLEM_GATE 与 DIRECTION_GATE decision，以及其批准的 artifact 版本。没有获批方向或依赖已 `stale` 时先暂停，不得用实验替人类选择问题。
2. 派 **modeler** 创建/更新 `problems/<p>/model.md`，显式记录研究目标、假设、指标、基线、可证伪条件和待澄清项。关键不确定项交人类决定，不脑补。
3. 创建版本化 design：研究问题、方法/数据、对照与消融、主要/次要指标、成功阈值、失败解释、复现计划、停止条件、成本估计和风险。
4. 准备一个低成本、可逆、无外部副作用的 pilot（通常建议本地不超过约 2 分钟且不用敏感数据/付费/远程资源），但此时不执行。把实验脚本或固定 verifier driver、spec、predicate 和预计输出路径全部列入待批准 envelope；所有可执行输入必须加入 `context_paths` 以绑定精确哈希。
5. 根据静态规模估计、既有证据或历史运行估算 pilot 成本，明确哪些只是推断。首次运行也必须等待 DESIGN_GATE。

## `DESIGN_GATE`

调用 `/decide` 或 `request_human_decision`，stage=`design`，并用 `parent_decision_id` 连接已回复的 DIRECTION_GATE。决策卡必须给 LLM 推荐、置信度/理由、已有证据与成本估计、未知、最强反对意见，并提供 2–4 个选项，例如：只运行限定 pilot、在明确预算内批准 pilot 后的正式运行、先改设计/指标、暂停/放弃；始终提供自定义/组合项。

envelope 至少包含：model/design/spec 版本、允许的数据与方法、主要指标/基线、运行次数、时间/内存/费用上限、local/remote 边界、停止条件、可写目录和失效条件。未获明确批准，不运行正式实验，不提交远程任务。

## 执行与汇报

获批后才在 envelope 内执行。脚本进入 `experiments/`，spec 进入 `specs/`，摘要/evidence 进入 `results/`；记录环境、版本、seed、失败和偏离设计之处。先运行批准的 pilot，用实测结果更新正式运行的时间、内存、费用和失败概率。若原卡没有明确覆盖正式运行，或 pilot 改变了方差/指标/预算判断，则创建引用上一条 design decision 的同阶段新卡；不得把“pilot 获批”扩写为“正式实验获批”。输出统计量、效应、异常和反例，不向对话倾倒原始数组。

成本超预算、结果不可复现、主要指标需更换、需要新数据/外部服务或发现模型假设错误时立即暂停重问。结果只作为证据，不在本 skill 内把主张标为 `reviewed`。
