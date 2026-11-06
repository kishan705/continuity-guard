from guard.parse import parse_path, parse_report, parse_text, ts_to_sec

from conftest import DEMO


def test_demo_show_parses_cleanly():
    eps = parse_path(DEMO)
    assert [e.episode for e in eps] == [1, 2, 3]
    assert eps[0].title == "The Contract"
    assert parse_report(eps)["warnings"] == []
    rose = eps[2].line("E03L003")
    assert rose.speaker == "ROSE" and rose.ts == "00:08" and rose.kind == "dialogue"
    assert eps[2].scenes[0].lines[0].kind == "heading"


def test_ids_are_stable_and_timestamps_increase():
    ep = parse_path(DEMO)[1]
    ids = [l.line_id for l in ep.all_lines()]
    assert ids[0] == "E02L001" and len(ids) == len(set(ids))
    secs = [l.ts_sec for l in ep.all_lines()]
    assert secs == sorted(secs)


def test_layout_variants():
    text = """Episode 7 - Twist
00:01 - INT. OFFICE - DAY
MAYA
(whispering)
You lied to me.
00:05 | ETHAN | I had to.
00:07 | | Ethan leaves.
Rose enters the room. (00:09)
Maya (V.O.): Some things you never forgive.
Note: lighting is dim
(00:12) CUT TO:
[00:13] ACTION: Rain on the window."""
    ep = parse_text(text, "x.txt")[0]
    rows = [(l.kind, l.speaker, l.text, l.ts) for l in ep.all_lines()]
    assert ep.episode == 7 and ep.title == "Twist"
    assert ("dialogue", "MAYA", "(whispering) You lied to me.", "00:01") in rows
    assert ("dialogue", "ETHAN", "I had to.", "00:05") in rows
    assert ("action", None, "Ethan leaves.", "00:07") in rows
    assert ("action", None, "Rose enters the room.", "00:09") in rows
    assert ("dialogue", "MAYA", "Some things you never forgive.", "00:09") in rows
    assert ("action", None, "Note: lighting is dim", "00:09") in rows
    assert ("transition", None, "CUT TO:", "00:12") in rows
    assert ("action", None, "Rain on the window.", "00:13") in rows


def test_multi_episode_file_and_sentence_not_heading():
    text = "EPISODE 1\n[00:01] MAYA: Hi.\nEPISODE 2: Next\n[00:01] - Ep 2, 01:05 is a twist\n[00:02] ETHAN: Bye."
    eps = parse_text(text, "all.txt")
    assert [e.episode for e in eps] == [1, 2]
    assert eps[1].all_lines()[0].text.startswith("- Ep 2") or eps[1].all_lines()[0].text.startswith("Ep 2")


def test_docx_input(tmp_path):
    import docx

    d = docx.Document()
    d.add_paragraph("EPISODE 5")
    d.add_paragraph("[00:00] INT. ROOF - NIGHT")
    d.add_paragraph("[00:03] LILY: Don't jump.")
    path = tmp_path / "ep_05.docx"
    d.save(path)
    ep = parse_path(path)[0]
    assert ep.episode == 5 and ep.line("E05L002").speaker == "LILY"


def test_ts_to_sec():
    assert ts_to_sec("01:05") == 65 and ts_to_sec("1:00:02") == 3602 and ts_to_sec("00:01.5") == 1.5
