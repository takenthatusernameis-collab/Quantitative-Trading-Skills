#!/usr/bin/env python3
"""
Unit tests for verify_install.py: chdb DataStore installation verification.

Run with: python3 skills/chdb-datastore/tests/test_verify_install.py
Uses only the standard library.
"""

import sys
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout
import io

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))


class MockSeries:
    """Mock pandas Series that supports comparison operations."""

    def __init__(self, data, name=None):
        self._data = list(data)
        self.name = name

    def __len__(self):
        return len(self._data)

    def __getitem__(self, idx):
        return self._data[idx]

    def __iter__(self):
        return iter(self._data)

    def __gt__(self, other):
        return MockSeries([x > other for x in self._data], name=self.name)

    def __lt__(self, other):
        return MockSeries([x < other for x in self._data], name=self.name)

    def __ge__(self, other):
        return MockSeries([x >= other for x in self._data], name=self.name)

    def __le__(self, other):
        return MockSeries([x <= other for x in self._data], name=self.name)

    def __eq__(self, other):
        return MockSeries([x == other for x in self._data], name=self.name)

    def __ne__(self, other):
        return MockSeries([x != other for x in self._data], name=self.name)

    def __bool__(self):
        # For boolean context, return True if any True
        return any(self._data)

    def __and__(self, other):
        return MockSeries([a and b for a, b in zip(self._data, other._data)], name=self.name)

    def __or__(self, other):
        return MockSeries([a or b for a, b in zip(self._data, other._data)], name=self.name)

    def __repr__(self):
        return f"MockSeries({self._data})"


class MockDataStore:
    """Mock DataStore that mimics basic pandas-like operations."""

    def __init__(self, data):
        self._data = {k: list(v) for k, v in data.items()}
        self._columns = list(data.keys())

    @property
    def columns(self):
        return self._columns

    def __getitem__(self, key):
        if isinstance(key, str):
            return MockSeries(self._data[key], name=key)
        # Boolean indexing with MockSeries
        if isinstance(key, MockSeries):
            mask = key._data
            filtered_data = {k: [v[i] for i, m in enumerate(mask) if m] for k, v in self._data.items()}
            return MockDataStore(filtered_data)
        # List of booleans
        if isinstance(key, list) and all(isinstance(x, bool) for x in key):
            filtered_data = {k: [v[i] for i, m in enumerate(key) if m] for k, v in self._data.items()}
            return MockDataStore(filtered_data)
        return self._data[key]

    def __len__(self):
        if not self._data:
            return 0
        return len(next(iter(self._data.values())))

    def sort_values(self, col):
        # Simple sort simulation
        idx = sorted(range(len(self._data[col])), key=lambda i: self._data[col][i])
        sorted_data = {k: [v[i] for i in idx] for k, v in self._data.items()}
        return MockDataStore(sorted_data)

    def groupby(self, col):
        return MockGroupBy(self, col)

    def select(self, *cols):
        return MockDataStore({c: self._data[c] for c in cols})


class MockGroupBy:
    def __init__(self, ds, col):
        self.ds = ds
        self.col = col

    def __getitem__(self, col_name):
        return MockGroupBySeries(self.ds, self.col, col_name)


class MockGroupBySeries:
    def __init__(self, ds, group_col, value_col):
        self.ds = ds
        self.group_col = group_col
        self.value_col = value_col

    def mean(self):
        groups = {}
        for i, g in enumerate(self.ds._data[self.group_col]):
            if g not in groups:
                groups[g] = []
            groups[g].append(self.ds._data[self.value_col][i])
        result = {g: sum(v) / len(v) for g, v in groups.items()}
        return MockDataStore({"group": list(result.keys()), "mean": list(result.values())})

    def __len__(self):
        groups = set(self.ds._data[self.group_col])
        return len(groups)


def create_mock_chdb():
    """Create a mock chdb module with DataStore."""
    mock_chdb = MagicMock()
    mock_chdb.__version__ = "4.1.9"
    mock_chdb.datastore = MagicMock()
    mock_chdb.datastore.DataStore = MockDataStore
    return mock_chdb


def create_mock_datastore():
    """Create a mock datastore module with DataStore."""
    mock_ds = MagicMock()
    mock_ds.DataStore = MockDataStore
    return mock_ds


def load_script_functions():
    """Load the verify_install.py functions without running main block."""
    script_path = SKILLS_DIR / "scripts" / "verify_install.py"
    code = script_path.read_text()
    g = {"__name__": "verify_install_module", "__file__": str(script_path), "sys": sys}
    exec(code, g)
    return g


def test_check_python_version():
    """Test Python version check passes for 3.9+."""
    g = load_script_functions()
    g["check_python_version"]()


def test_check_chdb_import_success():
    """Test chdb import check passes with mocked chdb."""
    mock_chdb = create_mock_chdb()

    with patch.dict(sys.modules, {"chdb": mock_chdb}):
        g = load_script_functions()
        g["check_chdb_import"]()
        assert mock_chdb.__version__ == "4.1.9"


def test_check_chdb_import_failure():
    """Test chdb import check fails when chdb is missing."""
    with patch.dict(sys.modules, {"chdb": None}):
        g = load_script_functions()
        try:
            g["check_chdb_import"]()
            assert False, "Expected ImportError"
        except (ImportError, AttributeError):
            pass  # Expected


def test_check_datastore_import_from_datastore():
    """Test from datastore import DataStore."""
    mock_datastore = create_mock_datastore()

    with patch.dict(sys.modules, {"datastore": mock_datastore}):
        g = load_script_functions()
        g["check_datastore_import_from_datastore"]()


def test_check_datastore_import_from_chdb():
    """Test from chdb.datastore import DataStore."""
    mock_chdb = create_mock_chdb()

    with patch.dict(sys.modules, {"chdb": mock_chdb, "chdb.datastore": mock_chdb.datastore}):
        g = load_script_functions()
        g["check_datastore_import_from_chdb"]()


def test_check_datastore_as_pd():
    """Test import chdb.datastore as pd."""
    mock_chdb = create_mock_chdb()

    with patch.dict(sys.modules, {"chdb": mock_chdb, "chdb.datastore": mock_chdb.datastore}):
        g = load_script_functions()
        g["check_datastore_as_pd"]()


def test_check_basic_operations():
    """Test basic DataStore filter operation."""
    mock_datastore = create_mock_datastore()

    with patch.dict(sys.modules, {"datastore": mock_datastore}):
        g = load_script_functions()
        g["check_basic_operations"]()


def test_check_sort():
    """Test DataStore sort operation."""
    mock_datastore = create_mock_datastore()

    with patch.dict(sys.modules, {"datastore": mock_datastore}):
        g = load_script_functions()
        g["check_sort"]()


def test_check_groupby():
    """Test DataStore groupby operation."""
    mock_datastore = create_mock_datastore()

    with patch.dict(sys.modules, {"datastore": mock_datastore}):
        g = load_script_functions()
        g["check_groupby"]()


def test_full_verification_all_pass():
    """Test full verification script with all mocks in place."""
    script_path = SKILLS_DIR / "scripts" / "verify_install.py"
    code = script_path.read_text()

    mock_chdb = create_mock_chdb()
    mock_datastore = create_mock_datastore()

    with patch.dict(sys.modules, {
        "chdb": mock_chdb,
        "chdb.datastore": mock_chdb.datastore,
        "datastore": mock_datastore
    }):
        g = {"__name__": "__main__", "__file__": str(script_path), "sys": sys}

        output = io.StringIO()
        with redirect_stdout(output):
            exec(code, g)

        out_str = output.getvalue()
        assert "All checks passed!" in out_str
        assert "8/8 passed" in out_str or "8 passed" in out_str


def test_full_verification_missing_chdb():
    """Test full verification script fails when chdb is missing."""
    script_path = SKILLS_DIR / "scripts" / "verify_install.py"
    code = script_path.read_text()

    modules_to_remove = [k for k in sys.modules if k.startswith("chdb")]
    for m in modules_to_remove:
        if m in sys.modules:
            del sys.modules[m]

    with patch.dict(sys.modules, {"chdb": None}, clear=False):
        g = {"__name__": "__main__", "__file__": str(script_path), "sys": sys}

        output = io.StringIO()
        with redirect_stdout(output):
            try:
                exec(code, g)
            except SystemExit as e:
                assert e.code == 1

        out_str = output.getvalue()
        assert "FAIL" in out_str
        assert "import chdb" in out_str


def main() -> int:
    tests = [
        ("check_python_version", test_check_python_version),
        ("check_chdb_import_success", test_check_chdb_import_success),
        ("check_chdb_import_failure", test_check_chdb_import_failure),
        ("check_datastore_import_from_datastore", test_check_datastore_import_from_datastore),
        ("check_datastore_import_from_chdb", test_check_datastore_import_from_chdb),
        ("check_datastore_as_pd", test_check_datastore_as_pd),
        ("check_basic_operations", test_check_basic_operations),
        ("check_sort", test_check_sort),
        ("check_groupby", test_check_groupby),
        ("full_verification_all_pass", test_full_verification_all_pass),
        ("full_verification_missing_chdb", test_full_verification_missing_chdb),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())