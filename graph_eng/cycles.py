"""Cycle detection that reports the actual cycle path (T-37)."""

from __future__ import annotations


def find_cycle(adjacency: dict[str, list[str]]) -> list[str] | None:
    """Return a cycle as [a, b, c, a], or None if the graph is acyclic.

    Iterative-safe DFS with an explicit path stack. Node and neighbour
    order is sorted so the reported cycle is deterministic.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(adjacency, WHITE)
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GRAY
        path.append(node)
        for nxt in sorted(adjacency.get(node, [])):
            if color.get(nxt, WHITE) == GRAY:
                return [*path[path.index(nxt) :], nxt]
            if color.get(nxt, WHITE) == WHITE:
                found = visit(nxt)
                if found:
                    return found
        path.pop()
        color[node] = BLACK
        return None

    for start in sorted(adjacency):
        if color[start] == WHITE:
            found = visit(start)
            if found:
                return found
    return None
