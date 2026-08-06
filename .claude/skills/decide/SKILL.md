---
name: decide
description: 在五个人类门或条件门展示开放式决策卡，记录真实人类选择并定义批准范围。用法：/decide <待决事项或 decision id>
---

# /decide — 人类决策控制流

输入：$ARGUMENTS

本 skill 不替人类做决定。它把 LLM 的分析变成可回应的开放选择题，并保证未收到明确回复时暂停。五门与 runner stage 映射：

| 人类门 | stage |
|---|---|
| `PROBLEM_GATE` | `problem` |
| `DIRECTION_GATE` | `direction` |
| `DESIGN_GATE` | `design` |
| `CLAIM_GATE` | `claim` |
| `RELEASE_GATE` | `release` |

## 决策卡格式

结构化请求使用字段 `why_now`、`recommendation`、`recommended_option`、`confidence`、`evidence`、`uncertainties`、`strongest_counterargument`、`change_conditions`、`options`、`approval_scope`、`reask_triggers`、`context_paths`、`authorized_paths`、`authorizing_option_ids`、`max_runtime_seconds`、`max_uses`、`parent_decision_id`。其中 `approval_scope` 就是本次批准 envelope，`context_paths` 由运行时绑定内容哈希；`authorized_paths` 明确批准后允许创建或执行的仓库相对路径；`authorizing_option_ids` 明确哪些已有选项会激活 envelope，自定义/修订/暂停默认不授权；`max_runtime_seconds` 是单次本地执行硬上限，`max_uses` 是整个 envelope 可消费的受控动作次数。

1. **门与阻塞动作**：现在处于哪个门，等待批准的下一步是什么；
2. **依据版本**：相关 artifact 的路径与精确版本；
3. **LLM 推荐**：推荐 option id、`confidence: high | medium | low` 与简洁理由；
4. **证据**：来自文件、实验、文献或审计的已知信息；
5. **未知**：尚未验证的假设与缺失信息；
6. **最强反对意见**：对推荐方案最有力的反驳/风险，以及什么新证据会改变推荐；
7. **选项**：2–4 个实质不同的开放方案。每项说明收益、风险、成本、影响的 artifact 和下一步；CLAIM_GATE 每项还要声明唯一 `claim_disposition`；
8. **自定义/组合**：明确邀请人类改写、组合、追加条件或继续讨论；`default_option_id: null`，推荐项也不预选；
9. **批准 envelope 草案**：scope、允许动作、预算/资源、artifact 版本、有效期/失效条件、重新询问条件。

推荐项不可预选；“沉默/超时”不是选项。不要只给“接受/拒绝”，也不要把无实质差异的措辞伪装成多个选择。一次最多打包三个紧密相关问题。

展示给人类时可使用以下开放式样式：

```text
[DESIGN_GATE] 现在需要确定正式实验范围
LLM 推荐：B（confidence: medium）——理由……
依据：……    未知：……
最强反对意见：……    会改变推荐的证据：……

A. 最小验证路线——收益……；代价/风险……；影响……
B. 匹配基线的正式路线——收益……；代价/风险……；影响……
C. 先改设计再决定——收益……；代价/风险……；影响……
自定义/组合：可以改写任一方案、组合 A+C，或要求继续讨论。

approval_scope 草案：……
authorized_paths 草案：……
authorizing_option_ids：……
max_uses：……
reask_triggers：……
```

## 运行时行为

- 有 `request_human_decision` 时，单独调用它；不得与写文件、运行命令等调用混在同一批。
- 五门按 `problem → direction → design → claim → release` 顺序连接；除首个 problem 外必须给出已回复上一门的 `parent_decision_id`。同阶段重问引用上一条同阶段回复，不能跳门。
- CLAIM_GATE 的 `authorizing_option_ids` 必须精确等于所有 `claim_disposition: accepted-with-scope` 选项；自定义回复不自动映射 disposition。
- 内置 runner 保存 request 和 checkpoint 后立即暂停。收到真实回复后，以原 tool call id 恢复，不重放暂停前的动作。
- 没有专用工具时，直接向用户展示完整决策卡并停止本轮；只有用户亲自回复后，才把其原意记录到 decision artifact。
- LLM、subagent、脚本或默认值都不得生成 response。不得覆盖已有 request/response；修订决定创建新 id 并引用旧 id。

## 恢复后

回述人类选择与解释后的 envelope，若有歧义先澄清。随后在 envelope 内连续执行，不重复询问。仅当超范围、artifact stale、证据冲突、资源/外部动作变化或命中卡片约定的失效条件时，创建新的决策请求。
