# Logistics Lattice Transpiler

An NL-to-SQL/Python transpiler pipeline for logistics data across the MCW, YCW, and VGU plants.

## Pipeline

schema -> NLU -> confirm -> DAG -> graph_eng -> CAG -> IR -> AST -> codegen -> sandbox
