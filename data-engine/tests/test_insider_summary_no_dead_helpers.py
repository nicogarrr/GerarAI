"""insider_summary no debe acumular helpers privados sin uso (código muerto)."""

import ast
from pathlib import Path

import app.services.insider_summary as mod


def test_no_unreferenced_private_functions():
    tree = ast.parse(Path(mod.__file__).read_text())
    private = {
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("_") and not n.name.startswith("__")
    }
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert private - used == set()
