"""模型无关的极简 agent loop：OpenAI 兼容 chat.completions + function calling。

设计要点：
- 单一事实源：角色提示词与工作流全部来自 .claude/（loader.py），与 Claude Code 同源；
- 工具本地执行（tools.py），write_file 后自动过状态门禁（verifiers/gate.py）；
- subagent = 换 system prompt 新开一段对话；深度限 1，subagent 不能再派 subagent；
- 换厂商只需 config 里的 base_url + api_key_env + model 三元组。
"""
import json
import os
import time
import urllib.error
import urllib.request

from . import loader, tools

RETRYABLE = {429, 500, 502, 503, 504}   # 过载/限流/网关类错误自动重试

ORCHESTRATOR = """\
你是 ai4math 仓库的主协调 agent，按任务描述推进研究工作流。

- 需要专门角色时用 spawn_subagent 派遣；给 skeptic 的审计任务只附猜想陈述与
  证明草稿原文，不要转述任何人的思路（审计独立性）。
- 一切状态推进必须经 verifiers/ 下的脚本背书（用 run 工具执行，python 解释器
  一律写 {python} 占位符）。
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


def run_agent(cfg_all, role, task, depth=0, on_event=None):
    """跑一个 agent 直到它给出最终文本回复；返回该回复。"""
    on_event = on_event or (lambda s: print(s, flush=True))
    limits = cfg_all.get("limits") or {}
    max_turns = int(limits.get("max_turns", 40))
    cap = int(limits.get("tool_output_chars", 8000))

    roles = loader.load_roles()
    parts = [loader.load_claude_md()]
    if role in roles:
        parts.append(roles[role]["prompt"])
    else:  # orchestrator（主协调 agent）
        parts.append(ORCHESTRATOR % _role_list(roles))
        task = loader.resolve_prompt(task, loader.load_skills())
    system = "\n\n━━━\n\n".join(p for p in parts if p.strip())

    cfg = _resolve_cfg(cfg_all, role, roles)
    schemas = list(tools.SCHEMAS)
    if depth == 0:
        schemas.append(_spawn_schema(roles))

    messages = [{"role": "system", "content": system},
                {"role": "user", "content": task}]
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
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""),
                             "content": str(result)[:cap]})
    return "[中止：达到 max_turns 上限——考虑拆小任务或调大 limits.max_turns]"
