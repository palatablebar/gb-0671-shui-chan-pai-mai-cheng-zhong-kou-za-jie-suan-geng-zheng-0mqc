import pytest
from app.engine import evaluate
from app.compensation.engine import evaluate_comp
from app.config import ROOT
@pytest.fixture
def sample():
    return evaluate()
@pytest.fixture
def clean():
    return evaluate({'dataset':'clean'})
@pytest.fixture
def comp_clean():
    return evaluate_comp({'dataset':'clean'})
@pytest.fixture
def comp_dirty():
    return evaluate_comp({'dataset':'dirty'})
@pytest.fixture
def comp_legacy():
    return evaluate_comp({'dataset':'legacy'})
@pytest.fixture
def comp_db(tmp_path):
    return str(tmp_path/'comp.sqlite')
