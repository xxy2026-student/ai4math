import json
import os
import shutil
import unittest
import uuid

from runner import decisions

TEST_TMP = os.path.join(os.path.dirname(__file__), ".tmp")


class DecisionTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(TEST_TMP, exist_ok=True)
        self.root = os.path.join(TEST_TMP, "decisions-" + uuid.uuid4().hex)
        os.makedirs(self.root)
        os.makedirs(os.path.join(self.root, "problems", "demo"))
        self.context_path = os.path.join(self.root, "problems", "demo", "model.md")
        with open(self.context_path, "w", encoding="utf-8") as f:
            f.write("# model r1\n")
        self.problem_parent = self._approved_parent("problem", None)
        self.direction_parent = self._approved_parent(
            "direction", self.problem_parent
        )

    def tearDown(self):
        shutil.rmtree(self.root)

    def _approved_parent(self, stage, parent):
        item = decisions.create_request(
            stage=stage,
            question=f"是否通过 {stage} 门？",
            why_now="下一阶段需要固定范围。",
            recommendation="继续受限路线。",
            recommended_option="continue",
            confidence="medium",
            strongest_counterargument="当前依据仍可能不足。",
            options=[
                {"id": "continue", "label": "继续", "description": "进入下一阶段"},
                {"id": "revise", "label": "修订", "description": "留在当前阶段"},
            ],
            resume_prompt="按人类选择继续。",
            approval_scope=["只在 demo 问题内继续"],
            reask_triggers=["问题范围变化"],
            context_paths=["problems/demo/model.md"],
            authorized_paths=["problems/demo"],
            authorizing_option_ids=["continue"],
            max_uses=100,
            parent_decision_id=parent,
            root=self.root,
        )
        decision_id = item["request"]["decision_id"]
        if item["status"] == "pending":
            decisions.record_response(decision_id, ["continue"], root=self.root)
        return decision_id

    def request(self, **overrides):
        args = {
            "stage": "design",
            "question": "采用哪一个实验设计？",
            "why_now": "正式实验会消耗预算并固定主要指标。",
            "recommendation": "先采用小样本设计 A。",
            "recommended_option": "A",
            "confidence": "medium",
            "strongest_counterargument": "小样本可能低估方差。",
            "change_conditions": ["pilot 方差超过阈值"],
            "options": [
                {"id": "A", "label": "小样本", "description": "先验证信号",
                 "tradeoffs": ["成本低", "统计功效有限"]},
                {"id": "B", "label": "完整实验", "description": "直接运行主实验",
                 "tradeoffs": ["成本高"]},
            ],
            "resume_prompt": "按人类选择更新 design，再继续。",
            "evidence": ["pilot 可在两分钟内完成"],
            "uncertainties": ["真实方差未知"],
            "approval_scope": ["只运行本地 pilot", "不安装新依赖"],
            "reask_triggers": ["需要远程机器", "主要指标变化"],
            "context_paths": ["problems/demo/model.md"],
            "authorized_paths": ["problems/demo/experiments"],
            "authorizing_option_ids": ["A"],
            "max_uses": 3,
            "parent_decision_id": self.direction_parent,
            "root": self.root,
        }
        args.update(overrides)
        return decisions.create_request(**args)

    def test_request_has_recommendation_but_no_default_approval(self):
        item = self.request()
        request = item["request"]
        self.assertEqual("A", request["recommended_option"])
        self.assertIsNone(request["default_option_id"])
        self.assertTrue(request["allow_custom"])
        self.assertEqual(["problems/demo/experiments"], request["authorized_paths"])
        self.assertEqual(["A"], request["authorizing_option_ids"])
        self.assertEqual(3, request["max_uses"])
        self.assertEqual("pending", item["status"])
        self.assertIn("没有默认选项", decisions.render_card(item))

    def test_custom_requires_text_and_response_is_immutable(self):
        item = self.request()
        decision_id = item["request"]["decision_id"]
        with self.assertRaises(decisions.DecisionError):
            decisions.record_response(decision_id, ["custom"], root=self.root)
        decided = decisions.record_response(
            decision_id, ["custom"], custom_text="采用 A，但 seed 增加到 5 个",
            root=self.root)
        self.assertEqual("human", decided["response"]["actor"])
        with self.assertRaises(decisions.DecisionError):
            decisions.record_response(decision_id, ["B"], root=self.root)

    def test_context_change_invalidates_old_request(self):
        item = self.request()
        decision_id = item["request"]["decision_id"]
        with open(self.context_path, "w", encoding="utf-8") as f:
            f.write("# model r2\n")
        with self.assertRaisesRegex(decisions.DecisionError, "依据文件已经变化"):
            decisions.record_response(decision_id, ["A"], root=self.root)

    def test_checkpoint_resumes_at_original_tool_call(self):
        item = self.request()
        decision_id = item["request"]["decision_id"]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call-7",
                "type": "function",
                "function": {"name": "request_human_decision", "arguments": "{}"},
            }]},
        ]
        decisions.save_checkpoint(
            decision_id, messages, tool_call_id="call-7", root=self.root)
        decisions.record_response(decision_id, ["A"], root=self.root)
        checkpoint = decisions.load_checkpoint(decision_id, root=self.root)
        self.assertEqual("call-7", checkpoint["tool_call_id"])
        self.assertEqual("assistant", checkpoint["messages"][-1]["role"])
        prompt = decisions.build_resume_prompt(decision_id, root=self.root)
        self.assertIn("用户明确选择：A", prompt)
        self.assertIn("批准范围：只运行本地 pilot；不安装新依赖", prompt)
        self.assertIn("授权路径：problems/demo/experiments", prompt)
        self.assertIn("批准范围状态：已激活", prompt)
        self.assertIn("最多受控动作次数：3", prompt)
        self.assertIn("单次本地运行上限：0 秒", prompt)

    def test_tampering_is_detected(self):
        item = self.request()
        decision_id = item["request"]["decision_id"]
        path = os.path.join(self.root, "decisions", decision_id, "request.json")
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        payload["recommendation"] = "被篡改"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        with self.assertRaisesRegex(decisions.DecisionError, "request_hash"):
            decisions.get_decision(decision_id, root=self.root)

    def test_decision_card_requires_open_reasoning_fields(self):
        with self.assertRaises(decisions.DecisionError):
            self.request(strongest_counterargument="")
        with self.assertRaises(decisions.DecisionError):
            self.request(confidence="certain")
        with self.assertRaises(decisions.DecisionError):
            self.request(approval_scope=[])

    def test_mandatory_gate_sequence_cannot_be_skipped(self):
        with self.assertRaisesRegex(decisions.DecisionError, "DESIGN_GATE"):
            self.request(parent_decision_id=None)
        with self.assertRaisesRegex(decisions.DecisionError, "parent 必须"):
            self.request(parent_decision_id=self.problem_parent)

    def test_claim_choice_is_bound_to_exact_disposition(self):
        design = self.request(decision_id="D-design-for-claim")
        design_id = design["request"]["decision_id"]
        decisions.record_response(design_id, ["A"], root=self.root)
        common = {
            "stage": "claim",
            "question": "如何处置这条主张？",
            "why_now": "审计已完成，写作前必须确定证据措辞。",
            "recommendation": "先修订。",
            "recommended_option": "revise",
            "confidence": "medium",
            "strongest_counterargument": "现有证据也可能足以支持窄结论。",
            "options": [
                {"id": "accept", "label": "接受窄结论", "description": "进入写作",
                 "claim_disposition": "accepted-with-scope"},
                {"id": "revise", "label": "继续修订", "description": "补证据或收缩",
                 "claim_disposition": "revise"},
            ],
            "resume_prompt": "按处置继续。",
            "approval_scope": ["只处理 demo 的窄主张"],
            "reask_triggers": ["主张或证据变化"],
            "context_paths": ["problems/demo/model.md"],
            "authorized_paths": ["problems/demo/conjectures", "paper/demo"],
            "authorizing_option_ids": ["accept"],
            "max_uses": 3,
            "parent_decision_id": design_id,
            "root": self.root,
        }
        item = decisions.create_request(**common)
        claim_id = item["request"]["decision_id"]
        decisions.record_response(
            claim_id, ["revise"], custom_text="补充稳健性证据后再审",
            root=self.root,
        )
        decisions.validate_claim_disposition(claim_id, "revise", root=self.root)
        with self.assertRaisesRegex(decisions.DecisionError, "不能记录"):
            decisions.validate_claim_disposition(
                claim_id, "accepted-with-scope", root=self.root
            )

        invalid = dict(common)
        invalid["decision_id"] = "D-claim-bad-authorizer"
        invalid["authorizing_option_ids"] = ["revise"]
        with self.assertRaisesRegex(decisions.DecisionError, "精确等于"):
            decisions.create_request(**invalid)

    def test_authorized_paths_cannot_escape_or_authorize_repo_root(self):
        with self.assertRaisesRegex(decisions.DecisionError, "authorized_paths"):
            self.request(authorized_paths=["."])
        with self.assertRaisesRegex(decisions.DecisionError, "authorized_paths"):
            self.request(authorized_paths=["../outside"])

    def test_non_authorizing_or_custom_choice_never_grants_machine_actions(self):
        for choice, custom in (("B", ""), ("custom", "不要运行，先改设计")):
            with self.subTest(choice=choice):
                item = self.request(decision_id=f"D-design-nonauth-{choice}")
                decision_id = item["request"]["decision_id"]
                decisions.record_response(
                    decision_id, [choice], custom_text=custom, root=self.root)
                with self.assertRaisesRegex(decisions.DecisionError, "未激活批准范围"):
                    decisions.require_decision(
                        decision_id, {"design"}, root=self.root,
                        action_path="problems/demo/experiments/pilot.py",
                        runtime_seconds=1,
                    )

    def test_action_usage_is_bounded_and_receipted(self):
        item = self.request(
            max_uses=1, max_runtime_seconds=1,
            decision_id="D-design-one-use",
        )
        decision_id = item["request"]["decision_id"]
        decisions.record_response(decision_id, ["A"], root=self.root)
        decisions.authorize_action(
            decision_id, {"design"}, root=self.root,
            action_path="problems/demo/experiments/pilot.py",
            runtime_seconds=1,
            action_fingerprint={"script": "sha256:first", "args": []},
        )
        uses = os.listdir(os.path.join(self.root, "decisions", decision_id, "uses"))
        self.assertEqual(["U-00001.json"], uses)
        with self.assertRaisesRegex(decisions.DecisionError, "max_uses"):
            decisions.authorize_action(
                decision_id, {"design"}, root=self.root,
                action_path="problems/demo/experiments/pilot.py",
                runtime_seconds=1,
            )

    def test_checkpoint_can_only_be_marked_for_resume_once(self):
        item = self.request(decision_id="D-design-single-resume")
        decision_id = item["request"]["decision_id"]
        decisions.save_checkpoint(
            decision_id,
            [{"role": "assistant", "content": "", "tool_calls": [{
                "id": "call-once",
                "type": "function",
                "function": {"name": "request_human_decision", "arguments": "{}"},
            }]}],
            tool_call_id="call-once", root=self.root,
        )
        decisions.record_response(decision_id, ["A"], root=self.root)
        decisions.mark_resume_started(decision_id, root=self.root)
        with self.assertRaisesRegex(decisions.DecisionError, "禁止覆盖"):
            decisions.mark_resume_started(decision_id, root=self.root)


if __name__ == "__main__":
    unittest.main()
