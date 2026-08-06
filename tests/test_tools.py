import os
import json
import shutil
import subprocess
import unittest
import uuid
from unittest import mock

from runner import decisions, tools
import gate as gate_module


TEST_TMP = os.path.join(os.path.dirname(__file__), ".tmp")


class ToolBoundaryTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(TEST_TMP, exist_ok=True)
        self.root = os.path.join(TEST_TMP, "tools-" + uuid.uuid4().hex)
        model_dir = os.path.join(self.root, "problems", "demo")
        experiment_dir = os.path.join(model_dir, "experiments")
        os.makedirs(experiment_dir)
        self.model = os.path.join(model_dir, "model.md")
        self.script = os.path.join(experiment_dir, "pilot.py")
        with open(self.model, "w", encoding="utf-8") as f:
            f.write("# model v1\n")
        with open(self.script, "w", encoding="utf-8") as f:
            f.write("print('pilot')\n")
        spec_dir = os.path.join(model_dir, "specs")
        os.makedirs(spec_dir)
        predicate_dir = os.path.join(model_dir, "predicates")
        os.makedirs(predicate_dir)
        self.predicate = os.path.join(predicate_dir, "pilot.py")
        with open(self.predicate, "w", encoding="utf-8") as f:
            f.write("def check(params):\n    return True\n")
        self.spec = os.path.join(spec_dir, "pilot.json")
        with open(self.spec, "w", encoding="utf-8") as f:
            json.dump({
                "predicate": "problems/demo/predicates/pilot.py",
                "evidence": "problems/demo/results/pilot.json",
            }, f)
        for rel in (
            "verifiers/search/counterexample_search.py",
            "verifiers/numeric/nash_check.py",
            "verifiers/symbolic/stackelberg_demo.py",
        ):
            target = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write("print('VERDICT: PASS')\n")

    def tearDown(self):
        shutil.rmtree(self.root)

    def approved_decision(self, budget=5, stage="design",
                          authorized_paths=("problems/demo/experiments",),
                          context_paths=None):
        order = ["problem", "direction", "design", "claim"]
        parent = None
        for current_stage in order[:order.index(stage) + 1]:
            final = current_stage == stage
            if current_stage == "claim":
                options = [
                    {"id": "accept", "label": "接受", "description": "按范围接受主张",
                     "claim_disposition": "accepted-with-scope"},
                    {"id": "revise", "label": "修订", "description": "收缩或补证据",
                     "claim_disposition": "revise"},
                ]
                recommendation = "accept"
                authorizing = ["accept"]
                choice = "accept"
            else:
                options = [
                    {"id": "run", "label": "继续", "description": "进入下一阶段"},
                    {"id": "revise", "label": "修订", "description": "先修改当前阶段"},
                ]
                recommendation = "run"
                authorizing = ["run"]
                choice = "run"
            paths = list(authorized_paths) if final else ["problems/demo"]
            default_context = [
                "problems/demo/model.md",
                "problems/demo/experiments/pilot.py",
                "problems/demo/specs/pilot.json",
                "problems/demo/predicates/pilot.py",
                "verifiers/search/counterexample_search.py",
                "verifiers/numeric/nash_check.py",
            ]
            item = decisions.create_request(
                stage=current_stage,
                question=f"是否通过 {current_stage} 门？",
                why_now="下一步会固定范围或产生计算副作用。",
                recommendation="在明确范围内继续。",
                recommended_option=recommendation,
                confidence="medium",
                strongest_counterargument="当前证据可能不足以代表完整研究。",
                options=options,
                resume_prompt="按选择继续。",
                approval_scope=["problems/demo 的受限研究动作"],
                reask_triggers=["超过预算", "范围或输入发生变化"],
                context_paths=(context_paths if final and context_paths is not None
                               else default_context),
                authorized_paths=paths,
                authorizing_option_ids=authorizing,
                max_runtime_seconds=budget,
                max_uses=100,
                parent_decision_id=parent,
                root=self.root,
            )
            parent = item["request"]["decision_id"]
            if item["status"] == "pending":
                decisions.record_response(parent, [choice], root=self.root)
        return parent

    def test_model_has_no_arbitrary_shell_tool(self):
        names = {x["function"]["name"] for x in tools.SCHEMAS}
        self.assertNotIn("run", names)
        self.assertIn("run_python", names)
        self.assertEqual("[未知工具] run", tools.dispatch("run", {"command": "echo x"}))

    def test_problem_experiment_requires_bound_decision_and_budget(self):
        with mock.patch.object(tools, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "decision_id"):
                tools.run_python("problems/demo/experiments/pilot.py", timeout=1)
            decision_id = self.approved_decision(budget=5)
            with self.assertRaisesRegex(decisions.DecisionError, "超出决策预算"):
                tools.run_python(
                    "problems/demo/experiments/pilot.py", timeout=6,
                    decision_id=decision_id)
            completed = subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")
            with mock.patch.object(tools, "venv_python", return_value="python"), \
                    mock.patch.object(tools.subprocess, "run", return_value=completed) as run:
                result = tools.run_python(
                    "problems/demo/experiments/pilot.py", args=["--seed", "1"],
                    timeout=5, decision_id=decision_id)
            self.assertIn("[exit 0]", result)
            argv = run.call_args.args[0]
            self.assertEqual("python", argv[0])
            self.assertEqual(["--seed", "1"], argv[-2:])
            self.assertFalse(run.call_args.kwargs["shell"])

    def test_stale_context_revokes_experiment_authorization(self):
        with mock.patch.object(tools, "ROOT", self.root):
            decision_id = self.approved_decision()
            with open(self.model, "w", encoding="utf-8") as f:
                f.write("# model v2\n")
            with self.assertRaisesRegex(decisions.DecisionError, "依据文件已经变化"):
                tools.run_python(
                    "problems/demo/experiments/pilot.py", timeout=1,
                    decision_id=decision_id)

    def test_experiment_outside_authorized_paths_is_rejected(self):
        with mock.patch.object(tools, "ROOT", self.root):
            decision_id = self.approved_decision(
                authorized_paths=("problems/other/experiments",))
            with self.assertRaisesRegex(decisions.DecisionError, "authorized_paths"):
                tools.run_python(
                    "problems/demo/experiments/pilot.py", timeout=1,
                    decision_id=decision_id)

    def test_model_file_tool_cannot_write_human_responses(self):
        with mock.patch.object(tools, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "控制目录"):
                tools.write_file("decisions/fake/response.json", "{}")
            with self.assertRaisesRegex(ValueError, "控制目录"):
                tools.write_file("remote/jobs.json", "{}")
            with self.assertRaisesRegex(ValueError, "控制目录"):
                tools.write_file("verifiers/unsafe.py", "print('unsafe')")
            os.makedirs(os.path.join(self.root, "remote"), exist_ok=True)
            with open(os.path.join(self.root, "remote", "jobs.json"), "w") as f:
                f.write("{}")
            with self.assertRaisesRegex(ValueError, "不得读取"):
                tools.read_file("remote/jobs.json")

    def test_executable_write_requires_bound_decision_and_path(self):
        with mock.patch.object(tools, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "decision_id"):
                tools.write_file(
                    "problems/demo/experiments/pilot.py", "print('changed')\n")
            wrong = self.approved_decision(
                stage="direction",
                authorized_paths=("problems/other/experiments",))
            with self.assertRaisesRegex(decisions.DecisionError, "authorized_paths"):
                tools.write_file(
                    "problems/demo/experiments/pilot.py", "print('changed')\n",
                    decision_id=wrong)
            approved = self.approved_decision(stage="direction")
            result = tools.write_file(
                "problems/demo/experiments/pilot.py", "print('changed')\n",
                decision_id=approved)
            self.assertIn("已写入", result)

    def test_trusted_verifier_arguments_cannot_expand_repo_scope(self):
        with self.assertRaisesRegex(ValueError, "只允许运行 gate.py"):
            tools.run_python(
                "verifiers/gate.py", args=["--root", "..", "--all"], timeout=1)
        with self.assertRaisesRegex(ValueError, "只能运行固定验证器"):
            tools.run_python(
                "verifiers/symbolic/stackelberg_demo.py", timeout=1
            )

    def test_workflow_artifacts_require_their_human_gate(self):
        with mock.patch.object(tools, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "direction"):
                tools.write_file("problems/demo/model.md", "# changed model\n")
            design = self.approved_decision(
                stage="design", authorized_paths=("problems/demo",))
            with self.assertRaisesRegex(decisions.DecisionError, "决策阶段"):
                tools.write_file(
                    "problems/demo/model.md", "# changed model\n",
                    decision_id=design)
            direction = self.approved_decision(
                stage="direction", authorized_paths=("problems/demo",))
            self.assertIn(
                "已写入",
                tools.write_file(
                    "problems/demo/model.md", "# changed model\n",
                    decision_id=direction),
            )

            claim = self.approved_decision(
                stage="claim", authorized_paths=("paper/demo",))
            self.assertIn(
                "已写入",
                tools.write_file(
                    "paper/demo/draft.md", "# scoped draft\n",
                    decision_id=claim),
            )

    def test_accepted_claim_requires_matching_claim_decision(self):
        claim_path = "problems/demo/conjectures/C-accepted.md"
        content_template = """---
id: C-accepted
problem: demo
status: open
human_disposition: accepted-with-scope
decision: {decision}
formal: not-requested
---

# Accepted claim
"""
        with mock.patch.object(tools, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "claim"):
                tools.write_file(
                    claim_path, content_template.format(decision="D-fake"))
            claim = self.approved_decision(
                stage="claim", authorized_paths=(claim_path,))
            with self.assertRaisesRegex(ValueError, "必须等于"):
                tools.write_file(
                    claim_path, content_template.format(decision="D-other"),
                    decision_id=claim)
            with self.assertRaisesRegex(decisions.DecisionError, "主题路径"):
                tools.write_file(
                    "problems/demo/conjectures/C-other.md",
                    content_template.format(decision=claim),
                    decision_id=claim,
                )
            other_content = content_template.replace(
                "C-accepted", "C-other"
            ).format(decision=claim)
            ok, message = gate_module.check_text(
                "problems/demo/conjectures/C-other.md",
                other_content,
                root=self.root,
                execute_verifiers=False,
            )
            self.assertFalse(ok)
            self.assertIn("authorized_paths", message)
            self.assertIn(
                "已写入",
                tools.write_file(
                    claim_path, content_template.format(decision=claim),
                    decision_id=claim),
            )

    def test_problem_verifier_requires_decision_and_safe_spec(self):
        completed = subprocess.CompletedProcess([], 0, stdout="VERDICT: PASS\n", stderr="")
        with mock.patch.object(tools, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "decision_id"):
                tools.run_python(
                    "verifiers/search/counterexample_search.py",
                    args=["--spec", "problems/demo/specs/pilot.json"], timeout=1)
            approved = self.approved_decision(
                authorized_paths=(
                    "problems/demo", "verifiers/numeric/nash_check.py",
                ))
            with mock.patch.object(tools, "venv_python", return_value="python"), \
                    mock.patch.object(tools.subprocess, "run", return_value=completed):
                result = tools.run_python(
                    "verifiers/numeric/nash_check.py",
                    args=["--spec", "problems/demo/specs/pilot.json"],
                    timeout=1, decision_id=approved)
            self.assertIn("[exit 0]", result)

            decision_dir = os.path.join(
                self.root, "decisions", approved, "uses"
            )
            receipt_name = sorted(os.listdir(decision_dir))[-1]
            with open(os.path.join(decision_dir, receipt_name), encoding="utf-8") as f:
                receipt = json.load(f)
            input_paths = {
                item["path"] for item in receipt["action_manifest"]["inputs"]
            }
            self.assertIn("problems/demo/specs/pilot.json", input_paths)
            self.assertIn("problems/demo/predicates/pilot.py", input_paths)
            self.assertIn(
                "verifiers/numeric/nash_check.py", receipt["action_paths"]
            )
            self.assertTrue(receipt["action_manifest"]["driver_sha256"].startswith(
                "sha256:"
            ))

    def test_verifier_requires_transitive_paths_and_exact_context_hashes(self):
        with mock.patch.object(tools, "ROOT", self.root):
            narrow = self.approved_decision(
                authorized_paths=(
                    "problems/demo/specs",
                    "verifiers/search/counterexample_search.py",
                )
            )
            with self.assertRaisesRegex(decisions.DecisionError, "authorized_paths"):
                tools.run_python(
                    "verifiers/search/counterexample_search.py",
                    args=["--spec", "problems/demo/specs/pilot.json"],
                    timeout=1,
                    decision_id=narrow,
                )

            missing_predicate_context = self.approved_decision(
                authorized_paths=(
                    "problems/demo",
                    "verifiers/search/counterexample_search.py",
                ),
                context_paths=[
                    "problems/demo/model.md",
                    "problems/demo/experiments/pilot.py",
                    "problems/demo/specs/pilot.json",
                    "verifiers/search/counterexample_search.py",
                ],
            )
            with self.assertRaisesRegex(decisions.DecisionError, "context 哈希"):
                tools.run_python(
                    "verifiers/search/counterexample_search.py",
                    args=["--spec", "problems/demo/specs/pilot.json"],
                    timeout=1,
                    decision_id=missing_predicate_context,
                )

    def test_dependency_write_rolls_back_when_tree_becomes_invalid(self):
        target = os.path.join(self.root, "notes.md")
        with open(target, "w", encoding="utf-8") as f:
            f.write("old")
        with mock.patch.object(tools, "ROOT", self.root), \
                mock.patch.object(gate_module, "check_text", return_value=(True, "")), \
                mock.patch.object(
                    gate_module, "check_tree",
                    side_effect=[(False, "dependent claim failed"), (True, "")],
                ) as tree:
            result = tools.write_file("notes.md", "new")
        self.assertIn("写入已回滚", result)
        with open(target, encoding="utf-8") as f:
            self.assertEqual("old", f.read())
        self.assertEqual(2, tree.call_count)


if __name__ == "__main__":
    unittest.main()
