"""Checks for the v4 participant task cards (web/src/content/taskcard.*.v4.*.md).

The pages are drafts behind the v4 switch; no page imports them yet. These checks keep them ready:
matching zh/en pairs, stage separation (the same patterns as tests/test_current_competition_browser.py),
the fixed facts, and no hidden-truth vocabulary.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[1] / "web" / "src" / "content"
FORMAL_WORDS = re.compile(r"正式赛|正式比赛|线上比赛|online competition|finals-preview|competition scenarios|正式大会|オンライン大会|compétition en ligne", re.I)
PRACTICE_WORDS = re.compile(r"练习赛|练习场景|Playground|\bpractice\b|練習|entraînement", re.I)
HIDDEN_WORDS = re.compile(r"seed|种子|pointing offset|指向偏差|efficiency multiplier|效率乘数|window_max_fraction|magnitude|震级", re.I)
PRACTICE_CARDS = ("alpha", "beta")


def body(name: str) -> str:
    text = (CONTENT / name).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)  # the organizer note is not rendered


def headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("#")]


@pytest.mark.parametrize("stem", ["template", *PRACTICE_CARDS])
def test_zh_and_en_pages_exist_and_have_the_same_shape(stem):
    en, zh = body(f"taskcard.{stem}.v4.en.md"), body(f"taskcard.{stem}.v4.zh.md")
    assert len(headings(en)) == len(headings(zh)) >= 8
    assert en.count("|") == zh.count("|")  # same tables
    for text in (en, zh):
        assert "Paranal" in text or "帕拉纳尔" in text
        assert "1.08" in text and "0.90" in text  # the worked example
        assert "`observe`" in text and "`wait`" in text and "`report`" in text and "`finish`" in text


@pytest.mark.parametrize("card", PRACTICE_CARDS)
@pytest.mark.parametrize("language", ["en", "zh"])
def test_practice_cards_use_only_practice_wording(card, language):
    text = body(f"taskcard.{card}.v4.{language}.md")
    match = FORMAL_WORDS.search(text)
    assert match is None, f"formal-stage wording on a Playground card: {match.group(0)!r}"
    assert "900" in text
    assert "{{" not in text, "unfilled card field"
    # Playground cards publish their weather files; the agent still only gets bulletins step by step.
    assert ("public" in text and "bulletin" in text) if language == "en" else ("公开" in text and "简报" in text)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_template_is_stage_neutral(language):
    text = body(f"taskcard.template.v4.{language}.md")
    for pattern in (FORMAL_WORDS, PRACTICE_WORDS):
        match = pattern.search(text)
        assert match is None, f"stage wording in the neutral template: {match.group(0)!r}"


@pytest.mark.parametrize("name", sorted(p.name for p in CONTENT.glob("taskcard.*.v4.*.md")))
def test_no_hidden_truth_vocabulary(name):
    match = HIDDEN_WORDS.search(body(name))
    assert match is None, f"{name}: {match.group(0)!r}"
