"""Schema contracts (T-12..T-16) hold for everything the real pipeline produces."""

import json
import uuid

import pytest

from ast_.nodes import AstTarget
from dag.serialization import to_json
from nlu.evaluation import EVAL_TODAY, load_dataset
from nlu.parser import parse
from nlu.wire import to_wire
from pipeline import lower
from plan.federation import plan_branches
from plantdb.plants import Plant
from schemas import validate_ast, validate_dag, validate_ir, validate_parsed_intent
from tests.conftest import TODAY
from tests.golden_queries import GOLDEN_QUERIES


def test_every_labeled_query_serializes_to_a_valid_parsed_intent():
    for row in load_dataset():
        wire = to_wire(parse(row["query"], EVAL_TODAY), str(uuid.uuid4()))
        errors = validate_parsed_intent.validate(wire)
        assert errors == [], (row["query"], errors)


def test_malformed_parsed_intent_fails_with_a_readable_error():
    wire = to_wire(parse("total freight cost", TODAY), str(uuid.uuid4()))
    wire["entities"][0]["entity_type"] = "spaceship"
    with pytest.raises(Exception, match="entity_type"):
        validate_parsed_intent.validate_or_raise(wire)


@pytest.mark.parametrize("gid,query", sorted(GOLDEN_QUERIES.items()))
def test_dag_ir_and_ast_documents_validate_against_their_schemas(gid, query):
    intent = parse(query, TODAY)
    branch = plan_branches(intent, ["MCW"])[0].intent
    for plant in Plant:
        sql = lower(branch, plant.value, AstTarget.SQL, str(uuid.uuid4()))
        validate_dag.validate_or_raise(json.loads(to_json(sql.dag)))
        validate_ir.validate_or_raise(sql.ir.model_dump(mode="json", exclude_none=True))
        validate_ast.validate_or_raise(sql.ast.model_dump(mode="json", exclude_none=True))
        py = lower(branch, plant.value, AstTarget.PYTHON, str(uuid.uuid4()))
        validate_ast.validate_or_raise(py.ast.model_dump(mode="json", exclude_none=True))


def test_an_invented_operation_is_rejected_by_every_schema():
    sql = lower(parse("total freight cost", TODAY), "MCW", AstTarget.SQL, str(uuid.uuid4()))
    for doc, validator in (
        (json.loads(to_json(sql.dag)), validate_dag),
        (sql.ir.model_dump(mode="json", exclude_none=True), validate_ir),
        (sql.ast.model_dump(mode="json", exclude_none=True), validate_ast),
    ):
        key = "node_type" if "node_type" in doc["nodes"][0] else "op"
        doc["nodes"][1][key] = "teleport"
        assert validator.validate(doc), validator.__name__


def test_every_schema_file_declares_a_version():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "schemas"
    for name in ("dag", "ir", "ast", "parsed_intent"):
        schema = json.loads((root / f"{name}.schema.json").read_text())
        assert "schema_version" in schema["properties"]
