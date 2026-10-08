"""Integrity and syntax test for all 4 Airflow DAGs across SmartDocument, CreditFlow, and SupportDesk."""
import ast
import glob
import os
import pytest

DAG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dags"))

def test_dag_files_exist():
    dag_files = glob.glob(os.path.join(DAG_DIR, "*.py"))
    assert len(dag_files) >= 4, f"Expected at least 4 DAG files, found {len(dag_files)}: {dag_files}"

@pytest.mark.parametrize("dag_path", glob.glob(os.path.join(DAG_DIR, "*.py")))
def test_dag_python_syntax(dag_path):
    """Ensure every DAG file parses valid Python AST."""
    with open(dag_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=dag_path)
    assert tree is not None
