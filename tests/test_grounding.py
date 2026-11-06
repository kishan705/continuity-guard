from guard.grounding import ground_facts, quote_in
from guard.parse import parse_path
from guard.schemas import Fact

from conftest import DEMO


def test_quote_matching_is_strict_but_forgiving_about_formatting():
    line = "Rose Sterling, 78, Ethan’s grandmother, taps her cane."
    assert quote_in("Ethan's grandmother", line)              # curly vs straight apostrophe
    assert quote_in("ROSE STERLING, 78", line)                # case
    assert quote_in("Rose Sterling ... taps her cane", line)  # ellipsis
    assert quote_in('"taps her cane."', line)                 # wrapping quotes / punctuation
    assert not quote_in("Rose is Ethan's mother", line)        # invented words
    assert not quote_in("a", line)                            # too short to mean anything


def _fact(line_id, quote):
    return Fact(line_id=line_id, entity="rose", fact_type="status", attribute="alive", value="false",
                quote=quote, episode=2)


def test_ground_facts_keeps_repairs_and_rejects():
    ep = parse_path(DEMO)[1]
    good = _fact("E02L013", "covers Rose's face")
    off_by_one = _fact("E02L012", "covers Rose's face")        # model cited the wrong line
    invented = _fact("E02L013", "Rose is buried in Paris")
    kept, rejected = ground_facts([good, off_by_one, invented], ep)
    assert len(kept) == 2 and rejected == [invented]
    assert kept[1].line_id == "E02L013" and kept[1].repaired
