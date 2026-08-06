"""AI4Research 人类决策闸门与不可覆盖的决策记录。

每个决策由一个目录组成：

    decisions/<decision-id>/request.json
    decisions/<decision-id>/response.json
    decisions/<decision-id>/checkpoint.json
    decisions/<decision-id>/resume.json
    decisions/<decision-id>/uses/U-00001.json

上述控制记录均只创建一次，不覆盖。状态由 response.json 是否存在推导；resume
记录阻止重复恢复，uses 记录限制批准 envelope 的消费次数，避免把“模型推荐”误当成
“用户已经同意”或无限授权。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_VERSION = 2
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_STAGES = {"problem", "direction", "design", "claim", "release"}
_CONFIDENCE = {"high", "medium", "low"}
_PREVIOUS_STAGE = {
    "direction": "problem",
    "design": "direction",
    "claim": "design",
    "release": "claim",
}
_CLAIM_DISPOSITIONS = {"pending", "accepted-with-scope", "revise", "reject"}


class DecisionError(ValueError):
    """决策请求或响应不合法。"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(value):
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_bytes(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _decisions_root(root):
    root_real = os.path.realpath(root)
    base = os.path.realpath(os.path.join(root_real, "decisions"))
    try:
        inside = os.path.commonpath(
            [os.path.normcase(root_real), os.path.normcase(base)]
        ) == os.path.normcase(root_real)
    except ValueError:
        inside = False
    if not inside or base == root_real:
        raise DecisionError("decisions 目录必须位于仓库内")
    return base


def _decision_dir(decision_id, root):
    if not _ID_RE.fullmatch(str(decision_id)):
        raise DecisionError(f"非法 decision_id: {decision_id!r}")
    base = _decisions_root(root)
    path = os.path.realpath(os.path.join(base, str(decision_id)))
    if os.path.commonpath([os.path.normcase(base), os.path.normcase(path)]) != \
            os.path.normcase(base):
        raise DecisionError("decision_id 越出 decisions 目录")
    return path


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_once(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError as exc:
        raise DecisionError(f"决策记录已存在，禁止覆盖: {path}") from exc


def _validate_hash(payload, hash_key, ignored):
    expected = payload.get(hash_key)
    core = {k: v for k, v in payload.items() if k not in set(ignored) | {hash_key}}
    if not expected or _sha256(core) != expected:
        raise DecisionError(f"{hash_key} 校验失败，记录可能被修改")


def _snapshot_context(context_paths, root):
    """把决策所依据的文件绑定到内容哈希，防止旧批准被新上下文复用。"""
    root = os.path.realpath(root)
    snapshots, seen = [], set()
    for raw in context_paths or []:
        rel = str(raw).strip().replace("\\", "/")
        if not rel:
            continue
        path = os.path.realpath(os.path.join(root, rel))
        try:
            inside = os.path.commonpath([os.path.normcase(root), os.path.normcase(path)]) == \
                os.path.normcase(root)
        except ValueError:
            inside = False
        if not inside or not os.path.isfile(path):
            raise DecisionError(f"决策依据必须是仓库内已有文件: {raw}")
        rel = os.path.relpath(path, root).replace("\\", "/")
        if rel in seen:
            continue
        seen.add(rel)
        with open(path, "rb") as f:
            digest = _sha256_bytes(f.read())
        snapshots.append({"path": rel, "sha256": digest})
    return sorted(snapshots, key=lambda x: x["path"])


def _validate_context(request, root):
    current = _snapshot_context([x["path"] for x in request.get("context", [])], root)
    if current != request.get("context", []):
        raise DecisionError("决策依据文件已经变化；旧决策不能继续使用，请创建新决策")


def _normalize_authorized_paths(paths, root):
    """Normalize future writable/executable paths without requiring existence."""
    root = os.path.realpath(root)
    normalized = []
    for raw in paths or []:
        value = str(raw).strip().replace("\\", "/").rstrip("/")
        if not value:
            continue
        absolute = os.path.realpath(os.path.join(root, value))
        try:
            inside = os.path.commonpath(
                [os.path.normcase(root), os.path.normcase(absolute)]
            ) == os.path.normcase(root)
        except ValueError:
            inside = False
        if not inside or absolute == root:
            raise DecisionError(f"authorized_paths 必须位于仓库内且不能是仓库根: {raw}")
        rel = os.path.relpath(absolute, root).replace("\\", "/")
        if rel not in normalized:
            normalized.append(rel)
    return sorted(normalized)


def _normalize_options(options, stage):
    if not isinstance(options, list) or not 2 <= len(options) <= 4:
        raise DecisionError("开放选择题需要 2–4 个实质性选项")
    normalized, seen = [], set()
    for raw in options:
        if not isinstance(raw, dict):
            raise DecisionError("每个选项必须是对象")
        option_id = str(raw.get("id", "")).strip()
        if not _ID_RE.fullmatch(option_id) or option_id == "custom":
            raise DecisionError(f"非法选项 id: {option_id!r}")
        if option_id in seen:
            raise DecisionError(f"重复选项 id: {option_id}")
        seen.add(option_id)
        label = str(raw.get("label", "")).strip()
        description = str(raw.get("description", "")).strip()
        if not label or not description:
            raise DecisionError(f"选项 {option_id} 缺少 label/description")
        item = {
            "id": option_id,
            "label": label,
            "description": description,
            "tradeoffs": [str(x).strip() for x in raw.get("tradeoffs", [])
                          if str(x).strip()],
        }
        claim_disposition = raw.get("claim_disposition")
        if stage == "claim":
            claim_disposition = str(claim_disposition or "").strip()
            if claim_disposition not in _CLAIM_DISPOSITIONS:
                raise DecisionError(
                    f"CLAIM_GATE 选项 {option_id} 必须声明 claim_disposition，"
                    f"且属于 {sorted(_CLAIM_DISPOSITIONS)}"
                )
            item["claim_disposition"] = claim_disposition
        elif claim_disposition is not None:
            raise DecisionError("claim_disposition 只能用于 CLAIM_GATE 选项")
        normalized.append(item)
    return normalized


def create_request(stage, question, recommendation, recommended_option,
                   options, resume_prompt, evidence=None, uncertainties=None,
                   allow_multiple=False, parent_decision_id=None,
                   decision_id=None, root=ROOT, why_now="", confidence="",
                   strongest_counterargument="", change_conditions=None,
                   approval_scope=None, reask_triggers=None,
                   context_paths=None, authorized_paths=None,
                   authorizing_option_ids=None,
                   max_runtime_seconds=0, max_uses=0):
    """创建一条不可覆盖的人类决策请求；相同请求重复调用保持幂等。"""
    stage = str(stage).strip().lower()
    if stage not in _STAGES:
        raise DecisionError("stage 必须是 problem、direction、design、claim 或 release")
    question = str(question).strip()
    recommendation = str(recommendation).strip()
    resume_prompt = str(resume_prompt).strip()
    why_now = str(why_now).strip()
    confidence = str(confidence).strip().lower()
    strongest_counterargument = str(strongest_counterargument).strip()
    if not all((question, why_now, recommendation, resume_prompt,
                strongest_counterargument)):
        raise DecisionError(
            "question/why_now/recommendation/strongest_counterargument/"
            "resume_prompt 均不能为空")
    if confidence not in _CONFIDENCE:
        raise DecisionError("confidence 必须是 high、medium 或 low")
    if isinstance(max_runtime_seconds, bool):
        raise DecisionError("max_runtime_seconds 必须是整数")
    try:
        max_runtime_seconds = int(max_runtime_seconds)
    except (TypeError, ValueError) as exc:
        raise DecisionError("max_runtime_seconds 必须是整数") from exc
    if not 0 <= max_runtime_seconds <= 86400:
        raise DecisionError("max_runtime_seconds 必须在 0–86400 之间")
    if isinstance(max_uses, bool):
        raise DecisionError("max_uses 必须是整数")
    try:
        max_uses = int(max_uses)
    except (TypeError, ValueError) as exc:
        raise DecisionError("max_uses 必须是整数") from exc
    if not 0 <= max_uses <= 10000:
        raise DecisionError("max_uses 必须在 0–10000 之间")

    if stage == "claim" and allow_multiple:
        raise DecisionError("CLAIM_GATE 的单一 human_disposition 不允许多选")
    normalized = _normalize_options(options, stage)
    option_ids = {x["id"] for x in normalized}
    recommended_option = str(recommended_option).strip()
    if recommended_option not in option_ids:
        raise DecisionError("recommended_option 必须对应一个现有选项")
    authorizing_option_ids = sorted({
        str(x).strip() for x in (authorizing_option_ids or []) if str(x).strip()
    })
    invalid_authorizers = set(authorizing_option_ids) - option_ids
    if invalid_authorizers:
        raise DecisionError(
            "authorizing_option_ids 必须只引用现有选项: "
            + ", ".join(sorted(invalid_authorizers))
        )

    if stage == "claim":
        accepted_option_ids = {
            item["id"] for item in normalized
            if item["claim_disposition"] == "accepted-with-scope"
        }
        if set(authorizing_option_ids) != accepted_option_ids:
            raise DecisionError(
                "CLAIM_GATE 的 authorizing_option_ids 必须精确等于 "
                "claim_disposition: accepted-with-scope 的选项集合"
            )

    evidence = [str(x).strip() for x in (evidence or []) if str(x).strip()]
    uncertainties = [str(x).strip() for x in (uncertainties or []) if str(x).strip()]
    change_conditions = [str(x).strip() for x in (change_conditions or [])
                         if str(x).strip()]
    approval_scope = [str(x).strip() for x in (approval_scope or [])
                      if str(x).strip()]
    reask_triggers = [str(x).strip() for x in (reask_triggers or [])
                      if str(x).strip()]
    if not approval_scope or not reask_triggers:
        raise DecisionError("approval_scope 和 reask_triggers 至少各需要一项")
    if stage == "problem":
        if parent_decision_id:
            validate_response(parent_decision_id, {"problem"}, root=root)
    else:
        if not parent_decision_id:
            raise DecisionError(
                f"{stage.upper()}_GATE 必须通过 parent_decision_id 连接"
                f"已回复的 {_PREVIOUS_STAGE[stage].upper()}_GATE"
            )
        parent = get_decision(parent_decision_id, root=root)
        parent_stage = parent["request"].get("stage")
        if parent_stage == stage:
            # 同阶段重问可以承接 revise/custom 等非授权回复，但必须是真实回复。
            validate_response(parent_decision_id, {stage}, root=root)
        elif parent_stage == _PREVIOUS_STAGE[stage]:
            if stage == "release":
                validate_claim_disposition(
                    parent_decision_id, "accepted-with-scope", root=root
                )
            require_decision(
                parent_decision_id, {_PREVIOUS_STAGE[stage]}, root=root
            )
        else:
            raise DecisionError(
                f"{stage.upper()}_GATE 的 parent 必须是已回复的 "
                f"{_PREVIOUS_STAGE[stage].upper()}_GATE 或同阶段重问"
            )
    normalized_authorized_paths = _normalize_authorized_paths(authorized_paths, root)
    context_snapshot = _snapshot_context(context_paths, root)
    if stage == "claim" and accepted_option_ids and not normalized_authorized_paths:
        raise DecisionError(
            "包含 accepted-with-scope 选项的 CLAIM_GATE 必须声明 authorized_paths"
        )
    if (normalized_authorized_paths or max_runtime_seconds > 0) and not authorizing_option_ids:
        raise DecisionError(
            "包含 authorized_paths 或运行预算的决策必须声明 authorizing_option_ids"
        )
    if normalized_authorized_paths or max_runtime_seconds > 0:
        if not context_snapshot:
            raise DecisionError("授权机器动作的决策必须用 context_paths 绑定至少一个依据文件")
        if max_uses < 1:
            raise DecisionError("授权机器动作的决策必须设置 max_uses >= 1")
    core = {
        "schema_version": SCHEMA_VERSION,
        "stage": stage,
        "question": question,
        "why_now": why_now,
        "recommendation": recommendation,
        "recommended_option": recommended_option,
        "confidence": confidence,
        "strongest_counterargument": strongest_counterargument,
        "change_conditions": change_conditions,
        "options": normalized,
        "allow_custom": True,
        "allow_multiple": bool(allow_multiple),
        "default_option_id": None,
        "authorizing_option_ids": authorizing_option_ids,
        "evidence": evidence,
        "uncertainties": uncertainties,
        "approval_scope": approval_scope,
        "reask_triggers": reask_triggers,
        "max_runtime_seconds": max_runtime_seconds,
        "max_uses": max_uses,
        "authorized_paths": normalized_authorized_paths,
        "context": context_snapshot,
        "resume_prompt": resume_prompt,
        "parent_decision_id": parent_decision_id or None,
    }
    request_hash = _sha256(core)
    decision_id = decision_id or f"D-{stage}-{request_hash.split(':', 1)[1][:12]}"
    ddir = _decision_dir(decision_id, root)
    request_path = os.path.join(ddir, "request.json")
    response_path = os.path.join(ddir, "response.json")

    if os.path.exists(request_path):
        existing = _read_json(request_path)
        if existing.get("request_hash") != request_hash:
            raise DecisionError(f"decision_id {decision_id} 已被另一请求占用")
        return get_decision(decision_id, root=root)
    if os.path.exists(response_path):
        raise DecisionError("发现没有 request.json 的孤立 response.json")

    payload = {
        **core,
        "decision_id": decision_id,
        "created_at": _now(),
        "request_hash": request_hash,
    }
    _write_once(request_path, payload)
    return get_decision(decision_id, root=root)


def get_decision(decision_id, root=ROOT):
    ddir = _decision_dir(decision_id, root)
    request_path = os.path.join(ddir, "request.json")
    if not os.path.exists(request_path):
        raise DecisionError(f"决策不存在: {decision_id}")
    request = _read_json(request_path)
    if request.get("decision_id") != decision_id:
        raise DecisionError("request.json 的 decision_id 与目录不匹配")
    _validate_hash(request, "request_hash", {"decision_id", "created_at"})
    response_path = os.path.join(ddir, "response.json")
    response = _read_json(response_path) if os.path.exists(response_path) else None
    if response is not None:
        if response.get("decision_id") != decision_id or \
                response.get("request_hash") != request.get("request_hash"):
            raise DecisionError("response.json 没有绑定当前决策请求")
        _validate_hash(response, "response_hash", {"decided_at"})
    return {"status": "decided" if response else "pending",
            "request": request, "response": response}


def save_checkpoint(decision_id, messages, tool_call_id,
                    role="orchestrator", root=ROOT):
    """保存暂停瞬间的完整对话；只写一次，恢复时不重放先前工具。"""
    current = get_decision(decision_id, root=root)
    if current["response"] is not None:
        raise DecisionError("不能为已响应的决策新建暂停点")
    if not isinstance(messages, list) or not messages:
        raise DecisionError("checkpoint messages 不能为空")
    if not str(tool_call_id).strip():
        raise DecisionError("checkpoint 缺少原始 tool_call_id")
    last = messages[-1]
    calls = last.get("tool_calls") if isinstance(last, dict) else None
    if not isinstance(last, dict) or last.get("role") != "assistant" or \
            not isinstance(calls, list) or len(calls) != 1:
        raise DecisionError("checkpoint 必须停在唯一的人类决策 tool call")
    call = calls[0]
    if call.get("id") != str(tool_call_id) or \
            (call.get("function") or {}).get("name") != "request_human_decision":
        raise DecisionError("checkpoint 的 tool_call_id 或工具名称不匹配")
    core = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "request_hash": current["request"]["request_hash"],
        "role": str(role),
        "tool_call_id": str(tool_call_id),
        "messages": messages,
    }
    payload = {**core, "created_at": _now(), "checkpoint_hash": _sha256(core)}
    path = os.path.join(_decision_dir(decision_id, root), "checkpoint.json")
    if os.path.exists(path):
        existing = _read_json(path)
        if existing.get("checkpoint_hash") != payload["checkpoint_hash"]:
            raise DecisionError("同一决策已有不同 checkpoint，禁止覆盖")
        return existing
    _write_once(path, payload)
    return payload


def load_checkpoint(decision_id, root=ROOT):
    current = get_decision(decision_id, root=root)
    path = os.path.join(_decision_dir(decision_id, root), "checkpoint.json")
    if not os.path.exists(path):
        raise DecisionError(f"决策 {decision_id} 没有可恢复 checkpoint")
    payload = _read_json(path)
    if payload.get("request_hash") != current["request"].get("request_hash"):
        raise DecisionError("checkpoint 与 decision request 哈希不匹配")
    _validate_hash(payload, "checkpoint_hash", {"created_at"})
    messages = payload.get("messages") or []
    if not messages or messages[-1].get("role") != "assistant":
        raise DecisionError("checkpoint 消息边界不合法")
    _validate_context(current["request"], root)
    return payload


def record_response(decision_id, choices, custom_text="", rationale="", root=ROOT):
    """记录用户选择。响应只写一次；修改意见应创建带 parent 的新决策。"""
    current = get_decision(decision_id, root=root)
    if current["response"] is not None:
        raise DecisionError(f"决策 {decision_id} 已有响应，禁止覆盖")
    request = current["request"]
    _validate_context(request, root)
    if isinstance(choices, str):
        choices = [x.strip() for x in choices.split(",") if x.strip()]
    choices = list(dict.fromkeys(str(x).strip() for x in choices if str(x).strip()))
    if not choices:
        raise DecisionError("至少选择一个选项；开放意见请使用 custom")
    known = {x["id"] for x in request["options"]} | {"custom"}
    unknown = [x for x in choices if x not in known]
    if unknown:
        raise DecisionError(f"未知选项: {', '.join(unknown)}")
    if not request.get("allow_multiple") and len(choices) > 1:
        raise DecisionError("此决策不允许多选")
    custom_text = str(custom_text).strip()
    if ({"custom", "revise"} & set(choices)) and not custom_text:
        raise DecisionError("选择 custom/revise 时必须填写 custom_text")

    core = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "request_hash": request["request_hash"],
        "actor": "human",
        "choices": choices,
        "custom_text": custom_text,
        "rationale": str(rationale).strip(),
    }
    payload = {**core, "decided_at": _now(), "response_hash": _sha256(core)}
    _write_once(os.path.join(_decision_dir(decision_id, root), "response.json"), payload)
    return get_decision(decision_id, root=root)


def list_decisions(root=ROOT, status=None):
    base = _decisions_root(root)
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if not _ID_RE.fullmatch(name):
            continue
        try:
            item = get_decision(name, root=root)
        except (DecisionError, OSError, json.JSONDecodeError):
            continue
        if status is None or item["status"] == status:
            out.append(item)
    return out


def _response_activates_scope(request, response):
    selected = set((response or {}).get("choices", []))
    authorizing = set(request.get("authorizing_option_ids", []))
    return bool(selected) and "custom" not in selected and selected.issubset(authorizing)


def _claim_effect(request, response):
    choices = (response or {}).get("choices", [])
    if "custom" in choices:
        return None
    by_id = {item["id"]: item for item in request.get("options", [])}
    effects = {
        by_id[choice].get("claim_disposition")
        for choice in choices if choice in by_id
    }
    return next(iter(effects)) if len(effects) == 1 and None not in effects else None


def _validate_stage_chain(decision_id, root=ROOT, seen=None):
    """Validate the complete immutable problem→...→release ancestry."""
    seen = set() if seen is None else set(seen)
    if decision_id in seen:
        raise DecisionError("decision parent 链存在循环")
    seen.add(decision_id)
    current = validate_response(decision_id, _STAGES, root=root)
    request = current["request"]
    stage = request.get("stage")
    parent_id = request.get("parent_decision_id")
    if stage == "problem":
        if not parent_id:
            return current
        parent = _validate_stage_chain(parent_id, root=root, seen=seen)
        if parent["request"].get("stage") != "problem":
            raise DecisionError("PROBLEM_GATE 重问只能引用上一条 PROBLEM_GATE")
        return current
    if not parent_id:
        raise DecisionError(
            f"{stage.upper()}_GATE 缺少 parent_decision_id，阶段链不完整"
        )
    parent = _validate_stage_chain(parent_id, root=root, seen=seen)
    parent_stage = parent["request"].get("stage")
    if parent_stage == stage:
        return current
    expected = _PREVIOUS_STAGE[stage]
    if parent_stage != expected:
        raise DecisionError(
            f"{stage.upper()}_GATE 的 parent 必须是 {expected.upper()}_GATE 或同阶段重问"
        )
    if not _response_activates_scope(parent["request"], parent["response"]):
        raise DecisionError(
            f"上游 {expected.upper()}_GATE 的选择没有允许进入 {stage.upper()}_GATE"
        )
    if stage == "release" and _claim_effect(
            parent["request"], parent["response"]
    ) != "accepted-with-scope":
        raise DecisionError("RELEASE_GATE 只能承接 accepted-with-scope 的 CLAIM_GATE")
    return current


def validate_response(decision_id, stages, root=ROOT):
    """Validate that a genuine response exists for one of the requested stages."""
    current = get_decision(decision_id, root=root)
    if current["response"] is None:
        raise DecisionError(f"决策 {decision_id} 尚未收到人类回复")
    request = current["request"]
    _validate_context(request, root)
    allowed_stages = {str(x) for x in stages}
    if request.get("stage") not in allowed_stages:
        raise DecisionError(
            f"决策阶段 {request.get('stage')!r} 不能用于此处；需要 {sorted(allowed_stages)}"
        )
    return current


def validate_claim_disposition(decision_id, disposition, root=ROOT,
                               subject_path=None):
    """Bind a CLAIM_GATE response to its exact machine-readable disposition."""
    disposition = str(disposition).strip()
    if disposition not in _CLAIM_DISPOSITIONS - {"pending"}:
        raise DecisionError("非 pending claim 处置必须是 accepted-with-scope/revise/reject")
    current = validate_response(decision_id, {"claim"}, root=root)
    _validate_stage_chain(decision_id, root=root)
    request = current["request"]
    response = current["response"]
    choices = response.get("choices", [])
    if "custom" in choices:
        raise DecisionError(
            "CLAIM_GATE 自定义回复不会自动映射为处置；请澄清后创建新决策"
        )
    actual = _claim_effect(request, response)
    if actual is None:
        raise DecisionError("CLAIM_GATE 回复没有唯一、机器可读的 claim_disposition")
    if actual != disposition:
        raise DecisionError(
            f"CLAIM_GATE 人类选择映射为 {actual!r}，不能记录为 {disposition!r}"
        )
    if disposition == "accepted-with-scope" and not _response_activates_scope(
            request, response):
        raise DecisionError("accepted-with-scope 选项没有激活批准范围")
    if subject_path:
        subject = str(subject_path).strip("/").replace("\\", "/")
        allowed = request.get("authorized_paths", [])
        if not any(
            subject == prefix or subject.startswith(prefix.rstrip("/") + "/")
            for prefix in allowed
        ):
            raise DecisionError(
                f"CLAIM_GATE 的主题路径 {subject!r} 不在 decision authorized_paths 内"
            )
    return current


def require_decision(decision_id, stages, root=ROOT, action_path=None,
                     action_paths=None, required_context_paths=None,
                     runtime_seconds=None):
    """验证一个真实、未过期且与执行范围相符的人类决定。"""
    current = validate_response(decision_id, stages, root=root)
    _validate_stage_chain(decision_id, root=root)
    request = current["request"]
    response = current["response"]
    if not _response_activates_scope(request, response):
        raise DecisionError(
            f"决策 {decision_id} 的人类选择未激活批准范围；"
            "自定义、修订、暂停或未列入 authorizing_option_ids 的选项不能授权机器动作"
        )
    requested_paths = []
    if action_path:
        requested_paths.append(action_path)
    requested_paths.extend(action_paths or [])
    normalized_paths = sorted({
        str(path).strip("/").replace("\\", "/")
        for path in requested_paths if str(path).strip("/")
    })
    for action in normalized_paths:
        allowed = request.get("authorized_paths", [])
        if not any(action == prefix or action.startswith(prefix.rstrip("/") + "/")
                   for prefix in allowed):
            raise DecisionError(f"动作路径 {action!r} 不在决策 authorized_paths 内")
    if required_context_paths:
        bound = {item["path"] for item in request.get("context", [])}
        required = {
            str(path).strip("/").replace("\\", "/")
            for path in required_context_paths if str(path).strip("/")
        }
        missing = sorted(required - bound)
        if missing:
            raise DecisionError(
                "执行输入没有被 decision context 哈希预先绑定: "
                + ", ".join(missing)
            )
    if runtime_seconds is not None:
        budget = int(request.get("max_runtime_seconds", 0))
        if int(runtime_seconds) > budget:
            raise DecisionError(
                f"请求运行 {runtime_seconds}s 超出决策预算 {budget}s；必须重新询问")
    return current


def _exclusive_lock(path, timeout=10.0):
    deadline = time.monotonic() + float(timeout)
    while True:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise DecisionError(f"决策使用锁超时: {path}")
            time.sleep(0.05)


def authorize_action(decision_id, stages, root=ROOT, action_path=None,
                     action_paths=None, required_context_paths=None,
                     runtime_seconds=None,
                     action_fingerprint=None):
    """Consume one explicitly bounded use and append an immutable usage receipt."""
    current = require_decision(
        decision_id, stages, root=root, action_path=action_path,
        action_paths=action_paths, required_context_paths=required_context_paths,
        runtime_seconds=runtime_seconds,
    )
    request = current["request"]
    ddir = _decision_dir(decision_id, root)
    lock_path = os.path.join(ddir, ".uses.lock")
    fd = _exclusive_lock(lock_path)
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        uses_dir = os.path.join(ddir, "uses")
        os.makedirs(uses_dir, exist_ok=True)
        existing = sorted(
            name for name in os.listdir(uses_dir)
            if name.startswith("U-") and name.endswith(".json")
        )
        maximum = int(request.get("max_uses", 0))
        if len(existing) >= maximum:
            raise DecisionError(
                f"决策 {decision_id} 已用完 max_uses={maximum}；必须重新询问"
            )
        sequence = len(existing) + 1
        requested_paths = []
        if action_path:
            requested_paths.append(action_path)
        requested_paths.extend(action_paths or [])
        normalized_paths = sorted({
            str(path).strip("/").replace("\\", "/")
            for path in requested_paths if str(path).strip("/")
        })
        core = {
            "schema_version": SCHEMA_VERSION,
            "decision_id": decision_id,
            "request_hash": request["request_hash"],
            "sequence": sequence,
            "action_paths": normalized_paths,
            "runtime_seconds": runtime_seconds,
            "action_manifest": action_fingerprint,
            "action_fingerprint": _sha256(action_fingerprint)
            if action_fingerprint is not None else None,
        }
        receipt = {**core, "authorized_at": _now(), "usage_hash": _sha256(core)}
        _write_once(os.path.join(uses_dir, f"U-{sequence:05d}.json"), receipt)
        return current
    finally:
        os.close(fd)
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass


def mark_resume_started(decision_id, root=ROOT):
    """Make checkpoint restoration single-use to prevent repeated side effects."""
    current = get_decision(decision_id, root=root)
    if current["response"] is None:
        raise DecisionError(f"决策 {decision_id} 尚未收到人类回复")
    checkpoint = load_checkpoint(decision_id, root=root)
    core = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "request_hash": current["request"]["request_hash"],
        "response_hash": current["response"]["response_hash"],
        "checkpoint_hash": checkpoint["checkpoint_hash"],
    }
    payload = {**core, "started_at": _now(), "resume_hash": _sha256(core)}
    _write_once(os.path.join(_decision_dir(decision_id, root), "resume.json"), payload)
    return payload


def render_card(decision):
    req = decision["request"]
    marker = "HUMAN_DECISION_RECORDED" if decision.get("status") == "decided" \
        else "HUMAN_DECISION_REQUIRED"
    lines = [
        f"[{marker}] {req['decision_id']}",
        f"阶段：{req['stage']}",
        f"上游决策：{req.get('parent_decision_id') or '(首个问题门)'}",
        f"问题：{req['question']}",
        f"为何现在决定：{req['why_now']}",
        f"LLM 建议：{req['recommended_option']} — {req['recommendation']}",
        f"信心：{req['confidence']}",
        f"最强反对意见：{req['strongest_counterargument']}",
    ]
    if req.get("evidence"):
        lines.append("依据：" + "；".join(req["evidence"]))
    if req.get("uncertainties"):
        lines.append("不确定性：" + "；".join(req["uncertainties"]))
    if req.get("change_conditions"):
        lines.append("会改变建议的新证据：" + "；".join(req["change_conditions"]))
    lines.append("选项：")
    for option in req["options"]:
        mark = "（推荐）" if option["id"] == req["recommended_option"] else ""
        lines.append(f"- {option['id']}: {option['label']}{mark} — {option['description']}")
        if option.get("claim_disposition"):
            lines.append(
                "  人类处置映射：" + option["claim_disposition"]
            )
        if option.get("tradeoffs"):
            lines.append("  取舍：" + "；".join(option["tradeoffs"]))
    lines.append("- custom: 自定义、组合方案或要求继续讨论（始终可用）")
    lines.append(
        "可激活批准范围的选项："
        + ("、".join(req.get("authorizing_option_ids", [])) or "(无；本卡仅收集方向意见)")
    )
    lines.append("批准范围：" + "；".join(req["approval_scope"]))
    lines.append("授权路径：" + ("；".join(req.get("authorized_paths", [])) or "(无)"))
    lines.append(f"单次本地运行预算：{req.get('max_runtime_seconds', 0)} 秒")
    lines.append(f"最多受控动作次数：{req.get('max_uses', 0)}")
    lines.append("重新询问条件：" + "；".join(req["reask_triggers"]))
    if decision.get("status") == "decided":
        resp = decision["response"]
        lines.append("已由人类选择：" + ", ".join(resp["choices"]))
        lines.append(
            "批准范围状态："
            + ("已激活" if _response_activates_scope(req, resp)
               else "未激活；只能修订、澄清或创建新决策，不能执行受控动作")
        )
    else:
        lines.append("没有默认选项；未收到明确选择前，工作流保持暂停。")
    return "\n".join(lines)


def build_resume_prompt(decision_id, root=ROOT):
    current = get_decision(decision_id, root=root)
    if current["response"] is None:
        raise DecisionError(f"决策 {decision_id} 仍在等待用户选择")
    req, resp = current["request"], current["response"]
    _validate_context(req, root)
    scope_active = _response_activates_scope(req, resp)
    scope_state = "已激活" if scope_active else (
        "未激活；本次恢复只能解释、修订或创建新的精确决策，"
        "不得执行需要授权的写入、验证器、实验或外部动作"
    )
    return (
        "恢复一个经过人类决策闸门暂停的 AI4Research 工作流。\n\n"
        f"决策 ID：{decision_id}\n"
        f"上游决策：{req.get('parent_decision_id') or '(首个问题门)'}\n"
        f"原问题：{req['question']}\n"
        f"LLM 当时建议：{req['recommended_option']} — {req['recommendation']}\n"
        f"用户明确选择：{', '.join(resp['choices'])}\n"
        f"用户自定义意见：{resp.get('custom_text') or '(无)'}\n"
        f"用户理由：{resp.get('rationale') or '(未填写)'}\n\n"
        f"可激活批准范围的选项："
        f"{('、'.join(req.get('authorizing_option_ids', [])) or '(无)')}\n"
        f"批准范围状态：{scope_state}\n"
        f"批准范围：{'；'.join(req['approval_scope'])}\n"
        f"授权路径：{'；'.join(req.get('authorized_paths', [])) or '(无)'}\n"
        f"单次本地运行上限：{req.get('max_runtime_seconds', 0)} 秒\n"
        f"最多受控动作次数：{req.get('max_uses', 0)}\n"
        f"必须重新询问的条件：{'；'.join(req['reask_triggers'])}\n\n"
        "用户选择高于先前的模型建议。按下面的恢复说明继续；若新的重大分叉出现，"
        "必须创建新的决策请求，不得沿用本次授权。\n\n"
        f"恢复说明：\n{req['resume_prompt']}"
    )


def _main():
    ap = argparse.ArgumentParser(description="AI4Research 人类决策记录")
    sub = ap.add_subparsers(dest="command", required=True)
    lp = sub.add_parser("list")
    lp.add_argument("--status", choices=["pending", "decided"], default=None)
    sp = sub.add_parser("show")
    sp.add_argument("decision_id")
    dp = sub.add_parser("decide")
    dp.add_argument("decision_id")
    dp.add_argument("--choice", action="append", required=True)
    dp.add_argument("--custom", default="")
    dp.add_argument("--rationale", default="")
    rp = sub.add_parser("resume-prompt")
    rp.add_argument("decision_id")
    args = ap.parse_args()

    if args.command == "list":
        rows = list_decisions(status=args.status)
        for item in rows:
            req = item["request"]
            print(f"{req['decision_id']}\t{item['status']}\t{req['stage']}\t{req['question']}")
    elif args.command == "show":
        print(json.dumps(get_decision(args.decision_id), ensure_ascii=False, indent=2))
    elif args.command == "decide":
        result = record_response(args.decision_id, args.choice,
                                 custom_text=args.custom, rationale=args.rationale)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(build_resume_prompt(args.decision_id))


if __name__ == "__main__":
    _main()
