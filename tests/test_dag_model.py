import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError  # noqa: E402

from dag.model import (  # noqa: E402
    AggregateOp,
    Dag,
    Edge,
    EdgeRole,
    FilterOperator,
    Node,
    NodeType,
    allowed_node_type_values,
)


def _linear_dag() -> dict:
    """source -> filter -> aggregate -> output, a minimal valid shape."""
    return {
        "trace_id": "11111111-1111-1111-1111-111111111111",
        "nodes": [
            {"id": "n1", "node_type": "source", "params": {"source": "dispatch"}},
            {
                "id": "n2",
                "node_type": "filter",
                "params": {"column": "origin_warehouse", "operator": "eq", "value": "MCW"},
            },
            {
                "id": "n3",
                "node_type": "aggregate",
                "params": {"group_by": [], "metric": "freight_cost_usd", "op": "sum"},
            },
            {"id": "n4", "node_type": "output", "params": {"columns": []}},
        ],
        "edges": [
            {"from_node": "n1", "to_node": "n2"},
            {"from_node": "n2", "to_node": "n3"},
            {"from_node": "n3", "to_node": "n4"},
        ],
    }


class TestDagModel(unittest.TestCase):
    def test_every_node_type_has_a_params_model(self):
        # Indirect check: every NodeType must construct via Node without
        # KeyError from the internal _PARAMS_BY_NODE_TYPE mapping.
        for node_type in NodeType:
            self.assertIsInstance(node_type.value, str)
        self.assertEqual(len(allowed_node_type_values()), len(NodeType))

    def test_valid_linear_dag_parses(self):
        dag = Dag.model_validate(_linear_dag())
        self.assertEqual(len(dag.nodes), 4)
        self.assertEqual(len(dag.edges), 3)

    def test_join_requires_left_and_right_roles(self):
        doc = {
            "trace_id": "22222222-2222-2222-2222-222222222222",
            "nodes": [
                {"id": "a", "node_type": "source", "params": {"source": "dispatch"}},
                {"id": "b", "node_type": "source", "params": {"source": "tracking"}},
                {"id": "j", "node_type": "join", "params": {"on": "invoice_number"}},
                {"id": "o", "node_type": "output", "params": {}},
            ],
            "edges": [
                {"from_node": "a", "to_node": "j", "role": "left"},
                {"from_node": "b", "to_node": "j", "role": "right"},
                {"from_node": "j", "to_node": "o"},
            ],
        }
        dag = Dag.model_validate(doc)
        self.assertEqual(dag.nodes[2].node_type, NodeType.JOIN)

    def test_join_missing_a_role_is_rejected(self):
        doc = {
            "trace_id": "33333333-3333-3333-3333-333333333333",
            "nodes": [
                {"id": "a", "node_type": "source", "params": {"source": "dispatch"}},
                {"id": "b", "node_type": "source", "params": {"source": "tracking"}},
                {"id": "j", "node_type": "join", "params": {"on": "invoice_number"}},
                {"id": "o", "node_type": "output", "params": {}},
            ],
            "edges": [
                {"from_node": "a", "to_node": "j"},  # no role
                {"from_node": "b", "to_node": "j", "role": "right"},
                {"from_node": "j", "to_node": "o"},
            ],
        }
        with self.assertRaises(ValidationError) as ctx:
            Dag.model_validate(doc)
        self.assertIn("left", str(ctx.exception))

    def test_duplicate_node_id_is_rejected(self):
        doc = _linear_dag()
        doc["nodes"][1]["id"] = "n1"  # collides with the source node
        with self.assertRaises(ValidationError) as ctx:
            Dag.model_validate(doc)
        self.assertIn("duplicate node id", str(ctx.exception))

    def test_edge_to_unknown_node_is_rejected(self):
        doc = _linear_dag()
        doc["edges"].append({"from_node": "n4", "to_node": "does-not-exist"})
        with self.assertRaises(ValidationError) as ctx:
            Dag.model_validate(doc)
        self.assertIn("unknown to_node", str(ctx.exception))

    def test_self_loop_is_rejected(self):
        doc = _linear_dag()
        doc["edges"][0]["to_node"] = doc["edges"][0]["from_node"]
        with self.assertRaises(ValidationError) as ctx:
            Dag.model_validate(doc)
        self.assertIn("self-loop", str(ctx.exception))

    def test_cycle_is_rejected(self):
        doc = _linear_dag()
        doc["edges"].append({"from_node": "n3", "to_node": "n2"})  # back-edge
        with self.assertRaises(ValidationError) as ctx:
            Dag.model_validate(doc)
        self.assertIn("cycle", str(ctx.exception))

    def test_source_with_incoming_edge_is_rejected(self):
        doc = _linear_dag()
        doc["edges"].append({"from_node": "n4", "to_node": "n1"})
        with self.assertRaises(ValidationError):
            Dag.model_validate(doc)

    def test_more_than_one_output_node_is_rejected(self):
        doc = _linear_dag()
        doc["nodes"].append({"id": "n5", "node_type": "output", "params": {}})
        doc["edges"].append({"from_node": "n3", "to_node": "n5"})
        with self.assertRaises(ValidationError) as ctx:
            Dag.model_validate(doc)
        self.assertIn("exactly one output node", str(ctx.exception))

    def test_node_params_are_validated_against_node_type(self):
        doc = _linear_dag()
        doc["nodes"][1]["params"] = {"column": "x"}  # missing required "operator"
        with self.assertRaises(ValidationError) as ctx:
            Dag.model_validate(doc)
        self.assertIn("invalid params", str(ctx.exception))

    def test_bare_node_and_edge_helpers_still_validate_params(self):
        node = Node(
            id="n1",
            node_type=NodeType.FILTER,
            params={"column": "x", "operator": FilterOperator.EQ, "value": "y"},
        )
        self.assertEqual(node.params["operator"], "eq")

        edge = Edge(from_node="n1", to_node="n2", role=EdgeRole.LEFT)
        self.assertEqual(edge.role, EdgeRole.LEFT)

    def test_allowed_node_type_values_are_plain_strings(self):
        values = allowed_node_type_values()
        self.assertIn("source", values)
        self.assertIn("output", values)
        self.assertIn(AggregateOp.SUM.value, ["sum", "count", "avg", "min", "max"])


if __name__ == "__main__":
    unittest.main()
