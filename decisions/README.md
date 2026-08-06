# 人类决策记录

`decisions/` 是 AI4Research 的控制面，不是普通研究文本。内置 runner 在人类门处保存决策请求与对话检查点，收到真实人类回复后才能恢复。LLM 不得写入或伪造 response。CLAIM_GATE 的回复映射为 claim 的 `human_disposition: pending | accepted-with-scope | revise | reject`，claim 用 `decision` 引用该记录；机器审计的 `status: reviewed` 与它正交。

每个决定使用独立目录：

```text
decisions/<decision-id>/
  request.json      决策卡；创建后不可覆盖
  response.json     人类选择/自定义方案；写入后不可覆盖
  checkpoint.json   暂停时的对话与待完成工具调用
  resume.json       checkpoint 已开始恢复的单次消费凭据
  uses/
    U-00001.json    每个受控动作的不可覆盖授权消费记录
```

请求至少包含门类型、问题、LLM 推荐、证据、未知、最强反对意见、2–4 个开放选项、自定义入口、`approval_scope`（批准 envelope）和 `reask_triggers`。`context_paths` 绑定已存在的依据文件及其内容哈希；`authorized_paths` 单独限制获批后可创建或执行的仓库相对路径；`authorizing_option_ids` 明确哪些已有 option 会激活 envelope，自定义/修订/暂停默认不授权；`max_runtime_seconds` 给出单次本地执行硬上限，`max_uses` 限制整个 envelope 可消费的受控动作次数。问题代码执行时，实验脚本或固定 verifier driver、spec、predicate 等每个输入既要落入授权路径，也必须预先存在于 context 哈希快照；使用凭据保存完整 action manifest。每次消费写入不可覆盖的 `uses/U-*.json`，checkpoint 启动恢复也只能一次。依赖变化或次数用尽后必须重新询问。推荐选项不是默认选项，`default_option_id` 必须为 `null`；没有 `response.json` 时保持暂停。

五门是顺序状态链：`problem → direction → design → claim → release`。除第一个 problem 外，首次进入下一阶段必须用 `parent_decision_id` 引用已回复且允许继续的上一阶段；同阶段重问只能引用上一条同阶段真实回复。CLAIM_GATE 每个 option 必须声明唯一 `claim_disposition`，且 `authorizing_option_ids` 必须精确等于映射为 `accepted-with-scope` 的 option 集合。gate 会读取 claim 引用的 request/response 并核对实际选择，单写一个假的 decision id 不会通过。

决策可能包含未公开想法、评审或资源信息，因此个人记录默认不应提交到公共仓库。若在私有 fork 中版本管理，应先确认数据、隐私和协作者同意。修订决定时新建 decision id，并用 `parent_decision_id` 或等价字段引用旧决定；不要编辑历史 response。

request/response 的不可覆盖与内容哈希用于检测普通误改和 stale 依据，但当前没有对人类身份做数字签名，也不能抵御拥有仓库写权限者重写整个记录。它是本地流程边界，不是签名级安全边界；高风险用途应增加访问控制和签名审阅。
