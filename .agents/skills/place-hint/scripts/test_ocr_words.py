# uvx --with numpy --with opencv-python-headless --with pytest pytest scripts/test_ocr_words.py
import shutil

import cv2
import numpy as np
import pytest

import ocr_words

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not installed")


@needs_tesseract
def test_reads_a_printed_name_at_its_place(tmp_path):
    img = np.full((300, 800, 3), 255, np.uint8)
    cv2.putText(img, "KANAZAWA", (420, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    p = tmp_path / "a.png"
    cv2.imwrite(str(p), img)
    words = ocr_words.read_words(p, "eng")
    hit = [w for w in words if "KANAZAWA" in w["text"]]
    assert hit, words
    w = hit[0]
    # the word spans about x 420..600, baseline at y 200
    assert 450 < w["col"] < 580 and 170 < w["row"] < 200


@needs_tesseract
def test_missing_image_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        ocr_words.read_words(tmp_path / "nope.png")


@needs_tesseract
def test_rotated_text_is_read_when_turned_back_and_placed_in_the_original(tmp_path):
    img = np.full((600, 900, 3), 255, np.uint8)
    cv2.putText(img, "KANAZAWA", (330, 320), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    M = cv2.getRotationMatrix2D((450, 300), 30, 1.0)  # text now runs up to the right at 30 degrees
    img = cv2.warpAffine(img, M, (900, 600), borderValue=(255, 255, 255))
    p = tmp_path / "r.png"
    cv2.imwrite(str(p), img)
    level = [w for w in ocr_words.read_words(p, "eng") if "KANAZAWA" in w["text"]]
    assert not level
    hits = [w for w in ocr_words.read_words(p, "eng", angles=[0, -30]) if "KANAZAWA" in w["text"]]
    assert hits and hits[0]["angle"] == -30
    # the word's centre was about (450, 305) before the turn; the turn is about (450, 300)
    assert abs(hits[0]["col"] - 450) < 40 and abs(hits[0]["row"] - 305) < 40


TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
5\t1\t1\t1\t1\t1\t100\t50\t20\t22\t90\t中
5\t1\t1\t1\t1\t2\t122\t50\t20\t22\t85\t伏
5\t1\t1\t1\t1\t3\t144\t51\t20\t22\t88\t古
5\t1\t1\t1\t1\t4\t300\t50\t20\t22\t80\t東
5\t1\t2\t1\t1\t1\t100\t200\t60\t20\t95\tKANDA
"""


def test_join_cjk_joins_touching_characters_on_a_line():
    words = ocr_words.parse_tsv(TSV)
    joined = ocr_words.join_cjk(words)
    assert [j["text"] for j in joined] == ["中伏古"]
    assert joined[0]["conf"] == 85
    assert 100 < joined[0]["col"] < 164


CHOME_TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
5\t1\t1\t1\t1\t1\t100\t50\t120\t20\t92\tKANOCHO
5\t1\t1\t1\t2\t1\t110\t76\t110\t20\t88\t3-CHOME
5\t1\t2\t1\t1\t1\t500\t50\t120\t20\t90\tKOTONO
5\t1\t3\t1\t1\t1\t500\t300\t110\t20\t90\t2-CHOME
"""


def test_a_name_and_the_chome_line_under_it_are_joined():
    words = ocr_words.parse_tsv(CHOME_TSV)
    joined = ocr_words.join_chome(words)
    assert [j["text"] for j in joined] == ["KANOCHO 3-CHOME"]  # KOTONO's chome line is far below: not joined
    j = joined[0]
    assert j["conf"] == 88 and j["kind"] == "chome"
    assert 100 < j["col"] < 220 and 50 < j["row"] < 96  # the box of both lines


@needs_tesseract
def test_both_grey_and_colour_are_read_by_default(tmp_path):
    img = np.full((300, 800, 3), (200, 220, 240), np.uint8)
    cv2.putText(img, "KANAZAWA", (420, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (90, 60, 120), 3)
    p = tmp_path / "c.png"
    cv2.imwrite(str(p), img)
    ws = ocr_words.read_words(p, "eng")
    assert {w["mode"] for w in ws if "KANAZAWA" in w["text"]} == {"grey", "colour"}


PHRASE_TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
5\t1\t1\t1\t1\t1\t100\t50\t80\t20\t92\tOxford
5\t1\t1\t1\t1\t2\t188\t50\t70\t20\t90\tStreet
5\t1\t1\t1\t1\t3\t600\t50\t70\t20\t90\tSoho
5\t1\t2\t1\t1\t1\t300\t200\t90\t20\t91\tCOVENT
5\t1\t2\t1\t2\t1\t296\t226\t96\t20\t89\tGARDEN
"""


def test_words_side_by_side_on_a_line_are_joined_into_a_phrase():
    words = ocr_words.parse_tsv(PHRASE_TSV)
    texts = [j["text"] for j in ocr_words.join_phrases(words)]
    assert "Oxford Street" in texts
    assert not any("Soho" in t for t in texts)  # too far to the right


def test_a_word_stacked_on_another_is_joined():
    words = ocr_words.parse_tsv(PHRASE_TSV)
    texts = [j["text"] for j in ocr_words.join_chome(words)]
    assert "COVENT GARDEN" in texts
