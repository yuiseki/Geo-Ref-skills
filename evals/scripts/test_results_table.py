# uvx --with pytest pytest scripts/test_results_table.py
import results_table as rt

HEAD = "id\tstyle\toutcome\n"


def write(p, rows):
    p.write_text(HEAD + "".join(f"{i}\t{s}\t{o}\n" for i, s, o in rows), encoding="utf-8")
    return p


def test_a_row_counts_correct_answers_holes_and_rejected_controls(tmp_path):
    write(tmp_path / "a.tsv", [("L1-a", "x", "ok"), ("L1-b", "x", "gate_hole"), ("L1-c", "x", "refused"),
                              ("N1-a", "x", "correct_reject"), ("N1-b", "x", "false_accept")])
    cells = rt.cells({"tsv": ["a.tsv"]}, tmp_path)
    assert cells == ["1/3", "1", "1/2"]


def test_a_row_can_join_matrices_keep_one_style_and_leave_out_the_controls(tmp_path):
    write(tmp_path / "a.tsv", [("L2-a", "bright", "ok"), ("L2-b", "carto", "ok"), ("N2-a", "bright", "correct_reject")])
    write(tmp_path / "b.tsv", [("L2-c", "bright", "refused")])
    assert rt.cells({"tsv": ["a.tsv", "b.tsv"], "style": "bright"}, tmp_path) == ["1/2", "0", "1/1"]
    assert rt.cells({"tsv": ["a.tsv"], "style": "carto", "negatives": "(同上)"}, tmp_path) == ["1/1", "0", "(同上)"]
    write(tmp_path / "c.tsv", [("L4-a", "x", "ok")])
    assert rt.cells({"tsv": ["c.tsv"]}, tmp_path)[2] == "(対照なし)"


def test_the_table_replaces_only_what_is_between_the_markers():
    doc = "before\n<!-- results:start -->\nold\n<!-- results:end -->\nafter\n"
    new = rt.replace_block(doc, "| a |\n")
    assert new == "before\n<!-- results:start -->\n| a |\n<!-- results:end -->\nafter\n"
    assert rt.replace_block(new, "| a |\n") == new
