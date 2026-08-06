"""模型无关的 AI4Research agent loop：OpenAI 兼容接口 + 人类决策暂停/恢复。

设计要点：
- 单一事实源：角色提示词与工作流全部来自 .claude/（loader.py），与 Claude Code 同源；
- 工具本地执行（tools.py），write_file 落盘前自动过状态门禁；
- 关键研究分叉调用 request_human_decision 后立即停止，不把推荐冒充用户授权；
- subagent = 换 system prompt 新开一段对话；深度限 1，subagent 不能再派 subagent；
- 换厂商只需 config 里的 base_url + api_key_env + model 三元组。
"""
import json
import os
import time
import urllib.error
import urllib.request

from . import decisions, loader, tools

RETRYABLE = {429, 500, 502, 503, 504}   # 过载/限流/网关类错误自动重试

ORCHESTRATOR = """\
你是 AI4Research 仓库的主协调 agent，目标是与人类一起发现、澄清并解决研究问题。

- 需要专门角色时用 spawn_subagent 派遣；给 skeptic 的审计任务只附猜想陈述与
  证明草稿原文，不要转述任何人的思路（审计独立性）。
- 在问题定义、候选 idea、关键假设、研究设计、资源投入、结果解释和发布措辞等
  重大分叉处，先形成自己的推荐与理由，再单独调用 request_human_decision；
  未收到明确选择不得继续产生下游副作用。
- 正常流程必须经过 problem、direction、design、claim、release 五个闸门；批准范围内
  可持续执行，不要机械地重复询问。范围、成本、证据或外部副作用变化时重新开闸。
- 决策卡没有默认批准；推荐项只是 LLM 意见，必须同时给出最强反对意见和 custom 入口。
- 数值/符号/经验验证都是分级证据，不自动等于数学证明或用户认可。
- 严格遵守 system prompt 前半部分（CLAUDE.md）的全部纪律。

可用角色：
%s"""


def _api_call(cfg, messages, schemas):
    payload = {"model": cfg["model"], "messages": messages}
    if schemas:
        payload["tools"] = schemas
    if "temperature" in cfg:
        payload["temperature"] = cfg["temperature"]
    key = os.environ.get(cfg.get("api_key_env", ""), "")
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    url = cfg["base_url"].rstrip("/") + "/chat/completions"

    last = "?"
    for attempt in range(4):
        if attempt:
            wait = (3, 15, 45)[attempt - 1]
            print(f"  [api] {last}，{wait}s 后第 {attempt}/3 次重试...", flush=True)
            time.sleep(wait)
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=int(cfg.get("request_timeout", 300))) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code in RETRYABLE:
                last = f"HTTP {e.code}（服务端过载/限流）"
                continue
            raise RuntimeError(f"API 错误 {e.code}（{cfg['base_url']}）: {body}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"网络错误 {type(e).__name__}"
            continue
    raise RuntimeError(
        f"API 连续 4 次失败（{cfg['base_url']}，最后一次：{last}）。"
        "服务端持续过载或网络不通——稍后再试，或在 runner/config.yaml 换一家厂商。")


def _resolve_cfg(cfg_all, role, roles):
    """default → agents frontmatter 模型档位别名 → roles 覆盖，逐层合并。"""
    cfg = dict(cfg_all.get("default") or {})
    tier = (roles.get(role, {}).get("meta") or {}).get("model")
    alias = (cfg_all.get("aliases") or {}).get(tier)
    if isinstance(alias, str) and alias not in ("", "default"):
        cfg["model"] = alias
    cfg.update((cfg_all.get("roles") or {}).get(role) or {})
    limits = cfg_all.get("limits") or {}
    if "request_timeout" not in cfg and "request_timeout" in limits:
        cfg["request_timeout"] = limits["request_timeout"]
    return cfg


def _role_list(roles):
    return "\n".join(f"- {n}: {(r['meta'].get('description') or '')[:80]}"
                     for n, r in roles.items())


def _spawn_schema(roles):
    return {"type": "function", "function": {
        "name": "spawn_subagent",
        "description": "派出一个专门角色的 subagent 执行子任务并返回其最终报告。\n可用角色：\n"
                       + _role_list(roles),
        "parameters": {"type": "object", "properties": {
            "role": {"type": "string", "enum": list(roles)},
            "task": {"type": "string",
                     "description": "自包含的任务描述（subagent 看不到当前对话）"}},
            "required": ["role", "task"]}}}


def run_agent(cfg_all, role, task=None, depth=0, on_event=None,
              initial_messages=None):
    """跑一个 agent 直到它给出最终文本回复；返回该回复。"""
    on_event = on_event or (lambda s: print(s, flush=True))
    limits = cfg_all.get("limits") or {}
    max_turns = int(limits.get("max_turns", 40))
    cap = int(limits.get("tool_output_chars", 8000))

    roles = loader.load_roles()
    if initial_messages is None:
        parts = [loader.load_claude_md()]
        if role in roles:
            parts.append(roles[role]["prompt"])
        else:  # orchestrator（主协调 agent）
            parts.append(ORCHESTRATOR % _role_list(roles))
            task = loader.resolve_prompt(task or "", loader.load_skills())
        system = "\n\n━━━\n\n".join(p for p in parts if p.strip())

    cfg = _resolve_cfg(cfg_all, role, roles)
    schemas = list(tools.SCHEMAS)
    if depth > 0:
        schemas = [s for s in schemas
                   if s["function"]["name"] != "request_human_decision"]
    if depth == 0:
        schemas.append(_spawn_schema(roles))

    if initial_messages is None:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": task}]
    else:
        # JSON 往返得到一份纯数据深拷贝，防止调用方的 checkpoint 被原地修改。
        messages = json.loads(json.dumps(initial_messages, ensure_ascii=False))
    for _ in range(max_turns):
        resp = _api_call(cfg, messages, schemas)
        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        clean = {"role": "assistant", "content": msg.get("content") or ""}
        if calls:
            clean["tool_calls"] = calls
        messages.append(clean)
        if not calls:
            return clean["content"]

        allowed_names = {schema["function"]["name"] for schema in schemas}
        undeclared = [
            c for c in calls if (c.get("function") or {}).get("name") not in allowed_names
        ]
        if undeclared:
            # Some OpenAI-compatible providers may emit a tool call that was not
            # present in the supplied schema. Treat the whole batch as zero-execution.
            for c in calls:
                name = (c.get("function") or {}).get("name", "")
                messages.append({
                    "role": "tool",
                    "tool_call_id": c.get("id", ""),
                    "content": f"[拒绝] 当前 agent 未获工具 {name!r}；本轮没有执行任何工具。",
                })
            continue

        # 决策请求必须独占本轮，避免模型把“请求授权”和其他有副作用的调用打包执行。
        decision_calls = [c for c in calls
                          if c["function"]["name"] == "request_human_decision"]
        if decision_calls and len(calls) != 1:
            for c in calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": c.get("id", ""),
                    "content": ("[拒绝] request_human_decision 必须单独调用；"
                                "本轮没有执行任何工具，请先提交决策卡并暂停。"),
                })
            continue

        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            on_event(f"  [{role}] {name} {json.dumps(args, ensure_ascii=False)[:120]}")
            if name == "spawn_subagent":
                sub = args.get("role", "")
                if depth > 0:
                    result = "[拒绝] subagent 不能再派 subagent。"
                elif sub not in roles:
                    result = f"[未知角色] {sub}，可用：{', '.join(roles)}"
                else:
                    result = run_agent(cfg_all, sub, args.get("task", ""),
                                       depth=depth + 1, on_event=on_event)
            else:
                result = tools.dispatch(name, args)
            result_text = (json.dumps(result, ensure_ascii=False)
                           if isinstance(result, (dict, list)) else str(result))
            if tools.is_human_decision(result):
                # checkpoint 停在原始 assistant tool call。恢复时再以同一个
                # tool_call_id 注入真实的人类响应，既不伪造用户消息，也不重放旧工具。
                decisions.save_checkpoint(result["decision_id"], messages,
                                          tool_call_id=c.get("id", ""),
                                          role=role, root=tools.ROOT)
                return result["message"]
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""),
                             "content": result_text[:cap]})
    return "[中止：达到 max_turns 上限——考虑拆小任务或调大 limits.max_turns]"
