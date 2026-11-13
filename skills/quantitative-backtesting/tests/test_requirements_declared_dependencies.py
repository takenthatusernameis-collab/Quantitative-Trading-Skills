#!/usr/bin/env python3
"""Static guard: runtime third-party imports must be declared in requirements.txt.

A missing declaration is a reproducibility defect rather than a code bug: a
clean ``pip install -r requirements.txt`` would fail at import time even though
the source and tests are correct. This happened for ``scipy``:
``utils.hierarchical_risk_parity`` imports it, but ``requirements.txt`` omitted
it, so 15 HRP tests and the HRP worked example failed on a documented install.

The check parses the AST of ``scripts/*.py`` (the runtime code path), so it
runs with the standard library alone and does not need the third-party
packages installed.
"""

import ast
import pathlib
import re
import sys

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
EXAMPLES_DIR = SKILL_DIR / "examples"
REQUIREMENTS_PATH = SKILL_DIR / "requirements.txt"


def _imported_top_level_modules(paths):
    names = set()
    for path in paths:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])
    return names


def _third_party_runtime_imports():
    stdlib = set(sys.stdlib_module_names)
    # Sibling modules (scripts and importable examples) are local, not
    # third-party, even though they are not installed packages.
    local = {p.stem for p in SCRIPTS_DIR.glob("*.py")}
    local |= {p.stem for p in EXAMPLES_DIR.glob("*.py")}
    imported = _imported_top_level_modules(sorted(SCRIPTS_DIR.glob("*.py")))
    return sorted(m for m in imported if m and m not in stdlib and m not in local)


def _declared_requirements():
    declared = set()
    for raw in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=!~\[\s;]", line, maxsplit=1)[0].strip()
        if name:
            declared.add(name.lower().replace("_", "-"))
    return declared


def test_runtime_third_party_imports_are_declared():
    declared = _declared_requirements()
    missing = [
        module
        for module in _third_party_runtime_imports()
        if module.lower().replace("_", "-") not in declared
    ]
    assert not missing, (
        "runtime scripts import third-party modules that requirements.txt does "
        f"not declare: {missing}. Add them so a clean install can run the code."
    )


def test_scipy_declared_for_hierarchical_risk_parity():
    assert "scipy" in _declared_requirements(), (
        "scipy must be declared: utils.hierarchical_risk_parity and its tests "
        "and example import it"
    )