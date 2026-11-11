import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError  # noqa: E402

from ast_.nodes import AstDocument, AstTarget, allowed_ast_op_values  # noqa: E402
from ir.grammar import allowed_ir_op_values  # noqa: E402


def _linear_ast(target: str) -> dict:
    """select -> filter -> aggregate -> output, a minimal valid shape."""
    warehouse_col = {"table": "dispatch", "column": "origin_warehouse", "type": "string"}
    cost_col = {"table": "dispatch", "column": "freight_cost_usd", "type": "float"}
    return {
        "trace_id": "11111111-1111-1111-1111-111111111111",
        "target": target,
        "nodes": [
            {
                "id": "n1",
                "op": "select",
                "var": "t1",
                "params": {"table": "dispatch", "columns": [warehouse_col, cost_col]},
            },
            {
                "id": "n2",
                "op": "filter",
                "var": "t2",
                "params": {
                    "column": warehouse_col,
                    "operator": "eq",
                    "value": {"value": "MCW", "type": "string"},
                },
            },
            {
                "id": "n3",
                "op": "aggregate",
                "var": "t3",
                "params": {"group_by": [], "metric": cost_col, "op": "sum", "result_type": "float"},
            },
            {"id": "n4", "op": "output", "var": "result", "params": {"columns": [cost_col]}},
        ],
        "edges": [
            {"from_node": "n1", "to_node": "n2"},
            {"from_node": "n2", "to_node": "n3"},
            {"from_node": "n3", "to_node": "n4"},
        ],
    }


class TestAstNodes(unittest.TestCase):
    def test_ast_op_vocabulary_matches_ir_exactly(self):
        """T-63's core decision: AST reuses IR's op vocabulary unchanged."""
        self.assertEqual(set(allowed_ast_op_values()), set(allowed_ir_op_values()))

    def test_valid_python_target_parses(self):
        doc = AstDocument.model_validate(_linear_ast("python"))
        self.assertEqual(doc.target, AstTarget.PYTHON)
        self.assertEqual(len(doc.nodes), 4)

    def test_valid_sql_target_parses(self):
        doc = AstDocument.model_validate(_linear_ast("sql"))
        self.assertEqual(doc.target, AstTarget.SQL)
        self.assertEqual(len(doc.nodes), 4)

    def test_same_shape_is_valid_for_both_targets(self):
        """The grammar is shared: identical node/edge shape works for
        either target, since target only says which codegen pass consumes
        the document, not what the document is allowed to contain."""
        python_doc = AstDocument.model_validate(_linear_ast("python"))
        sql_doc = AstDocument.model_validate(_linear_ast("sql"))
        self.assertEqual(
            [n.op for n in python_doc.nodes],
            [n.op for n in sql_doc.nodes],
        )

    def test_duplicate_var_binding_is_rejected(self):
        doc = _linear_ast("python")
        doc["nodes"][1]["var"] = "t1"  # collides with the select node's var
        with self.assertRaises(ValidationError) as ctx:
            AstDocument.model_validate(doc)
        self.assertIn("duplicate var binding", str(ctx.exception))

    def test_node_params_are_validated_same_as_ir(self):
        doc = _linear_ast("python")
        doc["nodes"][1]["params"] = {"column": doc["nodes"][1]["params"]["column"]}
        with self.assertRaises(ValidationError) as ctx:
            AstDocument.model_validate(doc)
        self.assertIn("invalid params", str(ctx.exception))

    def test_duplicate_node_id_is_rejected(self):
        doc = _linear_ast("python")
        doc["nodes"][1]["id"] = "n1"
        with self.assertRaises(ValidationError) as ctx:
            AstDocument.model_validate(doc)
        self.assertIn("duplicate node id", str(ctx.exception))

    def test_cycle_is_rejected(self):
        doc = _linear_ast("sql")
        doc["edges"].append({"from_node": "n3", "to_node": "n2"})
        with self.assertRaises(ValidationError) as ctx:
            AstDocument.model_validate(doc)
        self.assertIn("cycle", str(ctx.exception))

    def test_unknown_target_is_rejected(self):
        doc = _linear_ast("python")
        doc["target"] = "rust"
        with self.assertRaises(ValidationError):
            AstDocument.model_validate(doc)


if __name__ == "__main__":
    unittest.main()
