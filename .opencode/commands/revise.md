---
description: "基于证据、评审或用户指示提出可比较修订，批准后创建新版本并传播 stale。用法：/revise <想法名> [修改指示]"
---

<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->

# /revise — 可追溯修订

输入：$ARGUMENTS

1. 读取 `ideas/<name>/` 的 idea、grounding、map、reviews 和相关 decisions，确认当前 active 版本及下游依赖。
2. 在改正文前给出修订提案：逐条列“接受/部分接受/不接受”的反馈、理由、预期 diff、收益、代价、未知，以及最强反对意见。
3. 若用户已给明确指示且改动完全落在现有 envelope 内，可连续执行，不重复打断。否则用开放决策卡提供 2–4 个修订方案与自定义/组合项，明确 LLM 推荐和置信度。
4. 获批后创建新版本：更新 frontmatter `version`、`based_on`、`decision`、`supersedes`；修订记录写日期、改变、依据和未采纳意见。禁止静默覆盖或删除旧观点。
5. 计算影响面：若问题、方向、假设、数据、指标或成功标准改变，把相应 grounding/model/design/spec/result/claim/paper 标为 `stale`，列出恢复 active 所需复核。

核心问题改变需重走 `PROBLEM_GATE`；路线或关键假设改变需重走 `DIRECTION_GATE`；只修措辞且语义不变则无需额外门。汇报新旧版本差异、stale 清单和建议下一步。
