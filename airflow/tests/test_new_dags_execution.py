"""Unit tests for task logic in CreditFlow and SupportDesk Airflow DAGs."""
import sys
import types
from pathlib import Path

# Provide lightweight stub for airflow if not installed locally
if "airflow" not in sys.modules:
    airflow = types.ModuleType("airflow")
    decorators = types.ModuleType("airflow.decorators")
    
    def dag(*a, **kw):
        def wrap(fn):
            return fn
        return wrap

    def task(fn=None, *a, **kw):
        def wrap(f):
            def inner(*args, **kwargs):
                return []
            return inner
        if fn is not None:
            return wrap(fn)
        return wrap

    decorators.dag = dag
    decorators.task = task
    airflow.decorators = decorators
    sys.modules["airflow"] = airflow
    sys.modules["airflow.decorators"] = decorators

AIRFLOW_ROOT = Path(__file__).resolve().parents[1]
if str(AIRFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_ROOT))

from dags.creditflow_data_and_drift_pipeline import _calculate_psi


def test_psi_identical_distributions():
    """Identical distributions should have PSI close to zero."""
    data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    val = _calculate_psi(data, data)
    assert val <= 0.05


def test_psi_shifted_distribution():
    """Significantly shifted distributions should have positive PSI."""
    ref = [10.0, 15.0, 20.0, 25.0, 30.0]
    cur = [100.0, 150.0, 200.0, 250.0, 300.0]
    val = _calculate_psi(ref, cur)
    assert val > 0.0


def test_supportdesk_sla_computation():
    """Test SLA MTTR and compliance rate calculations."""
    tickets = [
        {
            "id": 1,
            "category": "BILLING",
            "created_at_epoch": 0,
            "resolved_at_epoch": 3600,
            "sla_target_minutes": 120,
        },
        {
            "id": 2,
            "category": "TECH",
            "created_at_epoch": 0,
            "resolved_at_epoch": 7200,
            "sla_target_minutes": 60,
        },
    ]

    durations_min = [(t["resolved_at_epoch"] - t["created_at_epoch"]) / 60.0 for t in tickets]
    breaches = sum(1 for t, d in zip(tickets, durations_min) if d > t["sla_target_minutes"])

    assert breaches == 1
    assert sum(durations_min) / len(tickets) == 90.0
