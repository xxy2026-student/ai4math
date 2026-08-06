---
name: writeup
description: 用 CLAIM_GATE 获批版本形成稿件，并在任何对外动作前经过 RELEASE_GATE。用法：/writeup <问题名> [note/section/full paper]
---

# /writeup — 受控成文与发布

输入：$ARGUMENTS

1. 盘点可用素材，只纳入 `human_disposition: accepted-with-scope` 且对应 CLAIM_GATE decision 明确覆盖的 claim/evidence/audit 版本。`status: reviewed` 但 disposition 为 pending/revise/reject 的主张不得进入确认性写作；`open`、`stale` 或仅 `evidence-supported` 的内容只能在 decision 明确允许时放入探索性结果、限制或 future work，不得升级措辞。
2. 派 **writer** 生成版本化 LaTeX 到 `paper/<p>/`。每个主张保留 decision id、复现路径、证据类型和限制；当前 gate 会拒绝尚无机器证据通道支持的 `formal: lean-verified`，未来开放后也只用于实际形式验证过的精确子命题。
3. 编译或静态检查，核对引用、图表数据、claim 版本、作者信息占位和复现说明。发现逻辑/数据问题立即停止，将 paper 标 `stale` 并返回 `/audit` 或上游。
4. 汇报草稿文件、与获批 claims 的对照、已知限制和未解决事项。生成草稿不等于授权 commit、push、发送、上传或提交。

## `RELEASE_GATE`

任何对外共享前，调用 `/decide` 或 `request_human_decision`，stage=`release`。决策卡给 LLM 推荐、置信度/理由、检查证据、未知、最强反对意见，以及 2–4 个选项，例如：按当前版本发布、完成指定修改后再审、仅内部保存/分享、暂缓；始终提供自定义/组合项。

envelope 必须写明：paper/claim 精确版本、受众、渠道、允许的具体外部动作、署名/许可、敏感内容处理、限制披露和失效条件。没有明确批准，不执行任何外部动作；批准某一渠道不自动授权其他渠道或后续新版。

发布后记录实际发布版本与位置。内容有实质修改、上游 claim 变 stale 或目标渠道变化时，重新走 RELEASE_GATE。
