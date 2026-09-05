"""提示模板、答案抽取与自洽投票。"""

from __future__ import annotations

import re

from dive.prompting import (
    COT_TRIGGER,
    Example,
    chain_of_thought_prompt,
    extract_answer,
    few_shot_prompt,
    majority_vote,
    self_consistency,
    zero_shot_prompt,
)


def test_zero_shot_prompt_shape():
    prompt = zero_shot_prompt("12+7 等于多少", instruction="请只输出数字")
    assert prompt.startswith("请只输出数字")
    assert prompt.endswith("答案：")
    assert "12+7 等于多少" in prompt


def test_few_shot_prompt_includes_every_example():
    examples = [Example("1+1", "2"), Example("2+2", "4")]
    prompt = few_shot_prompt(examples, "3+3")
    assert prompt.count("问题：") == 3
    assert "2" in prompt and "4" in prompt
    assert prompt.endswith("答案：")


def test_few_shot_cot_prompt_shows_reasoning_and_asks_for_it():
    examples = [Example("1+1", "2", reasoning="个位 1+1=2")]
    prompt = few_shot_prompt(examples, "3+4", with_reasoning=True)
    assert "推理：个位 1+1=2" in prompt
    assert prompt.endswith("推理：")


def test_few_shot_prompt_ignores_missing_reasoning():
    prompt = few_shot_prompt([Example("1+1", "2")], "3+4", with_reasoning=True)
    assert "推理：2" not in prompt


def test_chain_of_thought_prompt_appends_trigger():
    assert COT_TRIGGER in chain_of_thought_prompt("难题")
    assert "自定义触发语" in chain_of_thought_prompt("难题", trigger="自定义触发语")


def test_extract_answer_takes_the_last_number_by_default():
    text = "先算 3+4=7，再算 7+10=17，所以答案是 17"
    assert extract_answer(text) == "17"
    assert extract_answer(text, last=False) == "3"


def test_extract_answer_handles_negatives_and_decimals():
    assert extract_answer("结果是 -2.5") == "-2.5"


def test_extract_answer_returns_none_without_match():
    assert extract_answer("完全没有数字") is None


def test_extract_answer_accepts_custom_pattern():
    pattern = re.compile(r"答案是([A-D])")
    assert extract_answer("我认为答案是C", pattern=pattern) == "C"


def test_majority_vote_picks_the_most_common_answer():
    answer, votes, total = majority_vote(["7", "8", "7", None, "7"])
    assert (answer, votes, total) == ("7", 3, 4)


def test_majority_vote_on_all_invalid_answers():
    assert majority_vote([None, None]) == (None, 0, 0)


def test_self_consistency_beats_a_single_wrong_sample():
    """8 条采样里 5 条算对——多数投票能把正确答案捞回来。"""
    samples = ["答案是 17"] * 5 + ["答案是 16", "答案是 18", "没有数字"]

    result = self_consistency(lambda index: samples[index], k=8)

    assert result.answer == "17"
    assert result.votes == 5
    assert result.total == 7
    assert result.confidence == 5 / 7
    assert len(result.samples) == 8
    assert result.answers[-1] is None
