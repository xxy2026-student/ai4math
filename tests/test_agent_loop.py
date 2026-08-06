import json
import os
import shutil
import unittest
import uuid
from unittest import mock

from runner import agent_loop, tools

TEST_TMP = os.path.join(os.path.dirname(__file__), ".tmp")


def _call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _response(content="", calls=None):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {"choices": [{"message": message}]}


class AgentLoopTests(unittest.TestCase):
    def config(self):
        return {
            "default": {"base_url": "https://invalid.test/v1", "model": "m"},
            "limits": {"max_turns": 5, "tool_output_chars": 8000},
        }

    def loader_patches(self):
        return (
            mock.patch.object(agent_loop.loader, "load_roles", return_value={}),
            mock.patch.object(agent_loop.loader, "load_skills", return_value={}),
            mock.patch.object(agent_loop.loader, "load_claude_md", return_value="rules"),
            mock.patch.object(agent_loop.loader, "resolve_prompt", side_effect=lambda x, _: x),
        )

    def test_mixed_decision_batch_executes_no_tool_in_either_order(self):
        decision = _call("d", "request_human_decision", {})
        write = _call("w", "write_file", {"path": "side-effect.txt", "content": "x"})
        for calls in ([decision, write], [write, decision]):
            with self.subTest(order=[x["id"] for x in calls]):
                api = mock.Mock(side_effect=[_response(calls=calls), _response("stopped")])
                patches = self.loader_patches()
                with patches[0], patches[1], patches[2], patches[3], \
                        mock.patch.object(agent_loop, "_api_call", api), \
                        mock.patch.object(agent_loop.tools, "dispatch") as dispatch:
                    result = agent_loop.run_agent(self.config(), "orchestrator", "task")
                self.assertEqual("stopped", result)
                dispatch.assert_not_called()
                self.assertEqual(2, api.call_count)

    def test_single_decision_pauses_without_another_api_call(self):
        os.makedirs(TEST_TMP, exist_ok=True)
        root = os.path.join(TEST_TMP, "agent-loop-" + uuid.uuid4().hex)
        os.makedirs(root)
        try:
            idea = os.path.join(root, "ideas", "demo", "idea.md")
            os.makedirs(os.path.dirname(idea))
            with open(idea, "w", encoding="utf-8") as f:
                f.write("# idea\n")
            args = {
                "stage": "problem",
                "question": "这个问题值得进入正式研究吗？",
                "why_now": "下一步会固定研究范围。",
                "recommendation": "先收缩边界。",
                "recommended_option": "A",
                "confidence": "medium",
                "strongest_counterargument": "过早收缩可能错过高价值方向。",
                "change_conditions": ["出现直接相关的新文献"],
                "options": [
                    {"id": "A", "label": "收缩", "description": "限定一个场景"},
                    {"id": "B", "label": "保持", "description": "保留宽问题"},
                ],
                "resume_prompt": "把选择写入研究问题说明。",
                "evidence": ["当前目标包含三个不同任务"],
                "uncertainties": ["用户优先级未知"],
                "approval_scope": ["只建立问题说明"],
                "reask_triggers": ["问题范围再次变化"],
                "authorized_paths": ["ideas/demo"],
                "authorizing_option_ids": ["A"],
                "context_paths": ["ideas/demo/idea.md"],
                "max_runtime_seconds": 0,
                "max_uses": 1,
            }
            api = mock.Mock(return_value=_response(calls=[
                _call("human-call", "request_human_decision", args)
            ]))
            patches = self.loader_patches()
            with patches[0], patches[1], patches[2], patches[3], \
                    mock.patch.object(agent_loop, "_api_call", api), \
                    mock.patch.object(tools, "ROOT", root):
                result = agent_loop.run_agent(self.config(), "orchestrator", "task")
            self.assertIn("HUMAN_DECISION_REQUIRED", result)
            self.assertEqual(1, api.call_count)
            decision_dirs = os.listdir(os.path.join(root, "decisions"))
            self.assertEqual(1, len(decision_dirs))
            checkpoint = os.path.join(root, "decisions", decision_dirs[0], "checkpoint.json")
            with open(checkpoint, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual("human-call", saved["tool_call_id"])
            self.assertEqual("assistant", saved["messages"][-1]["role"])
        finally:
            shutil.rmtree(root)

    def test_resume_history_is_used_without_replaying_old_tools(self):
        history = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "", "tool_calls": [
                _call("human-call", "request_human_decision", {})]},
            {"role": "tool", "tool_call_id": "human-call", "content": "human chose A"},
        ]
        captured = {}

        def api(_cfg, messages, _schemas):
            captured["messages"] = messages
            return _response("continued")

        with mock.patch.object(agent_loop.loader, "load_roles", return_value={}), \
                mock.patch.object(agent_loop, "_api_call", side_effect=api), \
                mock.patch.object(agent_loop.tools, "dispatch") as dispatch:
            result = agent_loop.run_agent(
                self.config(), "orchestrator", initial_messages=history)
        self.assertEqual("continued", result)
        dispatch.assert_not_called()
        self.assertEqual("tool", captured["messages"][3]["role"])
        self.assertEqual("human-call", captured["messages"][3]["tool_call_id"])

    def test_subagent_cannot_receive_human_decision_tool(self):
        seen = {}

        def api(_cfg, _messages, schemas):
            seen["names"] = [x["function"]["name"] for x in schemas]
            return _response("done")

        with mock.patch.object(agent_loop.loader, "load_roles", return_value={}), \
                mock.patch.object(agent_loop.loader, "load_claude_md", return_value="rules"), \
                mock.patch.object(agent_loop, "_api_call", side_effect=api):
            agent_loop.run_agent(self.config(), "scholar", "task", depth=1)
        self.assertNotIn("request_human_decision", seen["names"])

    def test_subagent_undeclared_decision_call_is_not_dispatched(self):
        api = mock.Mock(side_effect=[
            _response(calls=[_call("bad", "request_human_decision", {})]),
            _response("rejected safely"),
        ])
        with mock.patch.object(agent_loop.loader, "load_roles", return_value={}), \
                mock.patch.object(agent_loop.loader, "load_claude_md", return_value="rules"), \
                mock.patch.object(agent_loop.loader, "resolve_prompt", side_effect=lambda x, _: x), \
                mock.patch.object(agent_loop, "_api_call", api), \
                mock.patch.object(agent_loop.tools, "dispatch") as dispatch:
            result = agent_loop.run_agent(
                self.config(), "scholar", "task", depth=1)
        self.assertEqual("rejected safely", result)
        dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
