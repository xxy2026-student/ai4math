from pathlib import Path
import unittest

from runner import loader, tools


ROOT = Path(__file__).resolve().parents[1]
GENERATED_NOTE = (
    "<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->"
)
MANDATORY_GATES = {
    "PROBLEM_GATE",
    "DIRECTION_GATE",
    "DESIGN_GATE",
    "CLAIM_GATE",
    "RELEASE_GATE",
}


class WorkflowContractTests(unittest.TestCase):
    def test_five_gates_and_open_decision_contract_are_global(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8-sig")
        for gate in MANDATORY_GATES:
            self.assertIn(gate, text)
        for field in (
            "why_now",
            "recommendation",
            "confidence",
            "strongest_counterargument",
            "approval_scope",
            "reask_triggers",
            "context_paths",
            "authorized_paths",
            "authorizing_option_ids",
            "max_runtime_seconds",
            "max_uses",
            "parent_decision_id",
            "claim_disposition",
            "default_option_id",
        ):
            self.assertIn(field, text)
        self.assertIn("自定义/组合", text)
        self.assertIn("沉默", text)

    def test_each_mandatory_gate_is_owned_by_a_workflow(self):
        skills = loader.load_skills()
        owners = {
            "ground": "PROBLEM_GATE",
            "review": "DIRECTION_GATE",
            "explore": "DESIGN_GATE",
            "audit": "CLAIM_GATE",
            "writeup": "RELEASE_GATE",
        }
        for skill, gate in owners.items():
            self.assertIn(gate, skills[skill]["body"])
        self.assertIn("decide", skills)

    def test_generated_opencode_files_are_in_sync(self):
        skills = loader.load_skills()
        roles = loader.load_roles()
        commands = {p.stem for p in (ROOT / ".opencode" / "commands").glob("*.md")}
        agents = {p.stem for p in (ROOT / ".opencode" / "agents").glob("*.md")}
        self.assertEqual(set(skills), commands)
        self.assertEqual(set(roles), agents)
        for name, skill in skills.items():
            generated = (ROOT / ".opencode" / "commands" / f"{name}.md").read_text(
                encoding="utf-8-sig"
            )
            self.assertIn(GENERATED_NOTE, generated)
            self.assertIn(skill["body"], generated)
        expected_agents = GENERATED_NOTE + "\n\n" + loader.load_claude_md()
        self.assertEqual(
            expected_agents,
            (ROOT / "AGENTS.md").read_text(encoding="utf-8-sig"),
        )

    def test_claim_status_human_disposition_and_formal_evidence_are_separate(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8-sig")
        self.assertIn("status: reviewed", text)
        self.assertIn("human_disposition", text)
        self.assertIn("formal:", text)
        self.assertIn("lean-verified", text)
        self.assertIn("claim_review_hash", text)
        self.assertIn("不自动等于数学证明", text)
        self.assertIn("不表示人类接受", text)

    def test_runner_schema_machine_enforces_decision_card_fields(self):
        schema = next(
            item["function"]
            for item in tools.SCHEMAS
            if item["function"]["name"] == "request_human_decision"
        )
        required = set(schema["parameters"]["required"])
        self.assertTrue(
            {
                "stage",
                "why_now",
                "recommendation",
                "confidence",
                "strongest_counterargument",
                "options",
                "approval_scope",
                "reask_triggers",
                "authorized_paths",
                "authorizing_option_ids",
                "max_runtime_seconds",
                "max_uses",
            }.issubset(required)
        )
        options = schema["parameters"]["properties"]["options"]
        self.assertEqual(2, options["minItems"])
        self.assertEqual(4, options["maxItems"])
        self.assertIn(
            "claim_disposition", options["items"]["properties"]
        )
        write_schema = next(
            item["function"]
            for item in tools.SCHEMAS
            if item["function"]["name"] == "write_file"
        )
        self.assertIn("decision_id", write_schema["parameters"]["properties"])


if __name__ == "__main__":
    unittest.main()
