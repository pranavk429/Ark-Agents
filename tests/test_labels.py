import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from kernel.labels import HandleStore


def test_stores_and_returns_handle_id():
    s = HandleStore()
    h = s.put("j1", value="Priya Nair, balance 4200", source="customer_db",
              trust="trusted", sensitivity="private", subject="customer:8823",
              step=1, records=1)
    assert h.id.startswith("h_")
    assert s.get("j1", h.id).subject == "customer:8823"


def test_resolves_explicit_handle_reference():
    s = HandleStore()
    h = s.put("j1", value="secret", source="customer_db", trust="trusted",
              sensitivity="private", subject="customer:8823", step=1, records=1)
    found = s.contributing("j1", {"body": f"see @{h.id} for details"})
    assert [x.id for x in found] == [h.id]


def test_resolves_by_content_when_agent_pastes_value():
    # The LLM often pastes the text instead of using the handle reference.
    # Provenance must survive that, or taint tracking is decorative.
    s = HandleStore()
    h = s.put("j1", value="Priya Nair, account balance 4200 INR",
              source="customer_db", trust="trusted", sensitivity="private",
              subject="customer:8823", step=1, records=1)
    found = s.contributing("j1", {"body": "Hi, Priya Nair, account balance 4200 INR"})
    assert [x.id for x in found] == [h.id]


def test_ignores_short_incidental_overlap():
    s = HandleStore()
    s.put("j1", value="ok", source="internal_kb", trust="trusted",
          sensitivity="internal", subject=None, step=1, records=1)
    assert s.contributing("j1", {"body": "ok thanks"}) == []
