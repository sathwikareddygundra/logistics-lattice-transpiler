import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError  # noqa: E402

from dag.model import NodeType  # noqa: E402
from ir.grammar import (  # noqa: E402
    AggregateOp,
    ColumnRef,
    Ir,
    IrType,
    Literal,
    allowed_ir_op_values,
)


def _linear_ir() -> dict:
    """select -> filter -> aggregate -> output, a minimal valid shape."""
    dispatch_id = {"table": "dispatch", "column": "invoice_number", "type": "string"}
    warehouse_col = {"table": "dispatch", "column": "origin_warehouse", "type": "string"}
    cost_col = {"table": "dispatch", "column": "freight_cost_usd", "type": "float"}
    return {
        "trace_id": "11111111-1111-1111-1111-111111111111",
        "nodes": [
            {
                "id": "n1",
                "op": "select",
                "params": {"table": "dispatch", "columns": [dispatch_id, warehouse_col, cost_col]},
            },
            {
                "id": "n2",
                "op": "filter",
                "params": {
                    "column": warehouse_col,
                    "operator": "eq",
                    "value": {"value": "MCW", "type": "string"},
                },
            },
            {
                "id": "n3",
                "op": "aggregate",
                "params": {
                    "group_by": [],
                    "metric": cost_col,
                    "op": "sum",
                    "result_type": "float",
                },
            },
            {"id": "n4", "op": "output", "params": {"columns": [cost_col]}},
        ],
        "edges": [
            {"from_node": "n1", "to_node": "n2"},
            {"from_node": "n2", "to_node": "n3"},
            {"from_node": "n3", "to_node": "n4"},
        ],
    }


class TestIrGrammar(unittest.TestCase):
    def test_every_dag_node_type_has_a_corresponding_ir_op(self):
        dag_types = {member.value for member in NodeType}
        ir_ops = set(allowed_ir_op_values())
        # dag "source" maps to ir "select"; every other name matches 1:1.
        expected_ir_ops = (dag_types - {"source"}) | {"select"}
        self.assertEqual(ir_ops, expected_ir_ops)

    def test_valid_linear_ir_parses(self):
        ir = Ir.model_validate(_linear_ir())
        self.assertEqual(len(ir.nodes), 4)
        self.assertEqual(len(ir.edges), 3)

    def test_filter_value_type_must_match_column_type(self):
        doc = _linear_ir()
        doc["nodes"][1]["params"]["value"] = {"value": 123, "type": "integer"}
        with self.assertRaises(ValidationError) as ctx:
            Ir.model_validate(doc)
        self.assertIn("does not match", str(ctx.exception))

    def test_join_requires_matching_key_types(self):
        doc = {
            "trace_id": "22222222-2222-2222-2222-222222222222",
            "nodes": [
                {
                    "id": "a",
                    "op": "select",
                    "params": {
                        "table": "dispatch",
                        "columns": [
                            {"table": "dispatch", "column": "invoice_number", "type": "string"}
                        ],
                    },
                },
                {
                    "id": "b",
                    "op": "select",
                    "params": {
                        "table": "tracking",
                        "columns": [
                            {"table": "tracking", "column": "invoice_number", "type": "integer"}
                        ],
                    },
                },
                {
                    "id": "j",
                    "op": "join",
                    "params": {
                        "left_key": {
                            "table": "dispatch",
                            "column": "invoice_number",
                            "type": "string",
                        },
                        "right_key": {
                            "table": "tracking",
                            "column": "invoice_number",
                            "type": "integer",
                        },
                    },
                },
                {"id": "o", "op": "output", "params": {}},
            ],
            "edges": [
                {"from_node": "a", "to_node": "j", "role": "left"},
                {"from_node": "b", "to_node": "j", "role": "right"},
                {"from_node": "j", "to_node": "o"},
            ],
        }
        with self.assertRaises(ValidationError) as ctx:
            Ir.model_validate(doc)
        self.assertIn("type mismatch", str(ctx.exception))

    def test_aggregate_result_type_must_match_op(self):
        doc = _linear_ir()
        doc["nodes"][2]["params"]["op"] = "count"
        # result_type is still "float" from _linear_ir, but count must be integer.
        with self.assertRaises(ValidationError) as ctx:
            Ir.model_validate(doc)
        self.assertIn("result_type", str(ctx.exception))

    def test_window_column_must_be_temporal(self):
        column = ColumnRef(table="dispatch", column="origin_warehouse", type=IrType.STRING)
        from ir.grammar import WindowParams

        with self.assertRaises(ValidationError):
            WindowParams(column=column, granularity="month")

    def test_duplicate_node_id_is_rejected(self):
        doc = _linear_ir()
        doc["nodes"][1]["id"] = "n1"
        with self.assertRaises(ValidationError) as ctx:
            Ir.model_validate(doc)
        self.assertIn("duplicate node id", str(ctx.exception))

    def test_cycle_is_rejected(self):
        doc = _linear_ir()
        doc["edges"].append({"from_node": "n3", "to_node": "n2"})
        with self.assertRaises(ValidationError) as ctx:
            Ir.model_validate(doc)
        self.assertIn("cycle", str(ctx.exception))

    def test_allowed_ir_op_values_are_plain_strings(self):
        values = allowed_ir_op_values()
        self.assertIn("select", values)
        self.assertIn("output", values)
        self.assertIn(AggregateOp.SUM.value, ["sum", "count", "avg", "min", "max"])

    def test_literal_and_columnref_are_plain_models(self):
        ref = ColumnRef(table="dispatch", column="invoice_number", type=IrType.STRING)
        lit = Literal(value="abc", type=IrType.STRING)
        self.assertEqual(ref.type, IrType.STRING)
        self.assertEqual(lit.value, "abc")


if __name__ == "__main__":
    unittest.main()
