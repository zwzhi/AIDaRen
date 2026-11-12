"""提示词组装器测试：七要素完整性、连续性约束、状态匹配。"""
from __future__ import annotations

import pytest

from app.services.commercial.prompt_compiler import (
    PRODUCT_STATE_LABELS,
    compile_continuity_constraint,
    compile_shot_prompt,
    label_reference_frame,
)


def test_prompt_contains_all_seven_elements() -> None:
    """七要素（Subject/Context/Action/Style/Camera/Composition/Ambiance）全部出现。"""
    prompt = compile_shot_prompt(
        shot_observation="达人手持精华液面向镜头",
        shot_inference="介绍产品卖点",
        shot_action_template="拧开瓶盖滴在掌心",
        actor_description="20岁亚洲女性，长黑发，白皙肤色",
        product_name="The Ordinary 烟酰胺精华",
        product_state="dispensing",
        approved_dialogue="这款精华质地清爽不粘腻",
        duration_seconds=6,
    )
    for keyword in ["Subject", "Context", "Action", "Style", "Camera", "Composition", "Ambiance"]:
        assert keyword in prompt, f"缺少七要素之一：{keyword}"
    assert "烟酰胺精华" in prompt
    assert "dispensing" in prompt  # 商品状态匹配
    assert "质地清爽不粘腻" in prompt  # 台词
    assert "continuity" in prompt.lower()  # 连续性约束


def test_continuity_constraint() -> None:
    constraint = compile_continuity_constraint(
        actor_appearance="长发女性，白T恤",
        wardrobe_color="白色",
        product_position="左手持瓶",
    )
    assert "长发女性" in constraint
    assert "白色" in constraint
    assert "左手持瓶" in constraint
    assert "unchanged" in constraint


def test_product_state_labels_complete() -> None:
    """商品状态键覆盖完整生命周期。"""
    expected = {"packaging", "opening", "dispensing", "texture", "application", "effect"}
    assert expected <= set(PRODUCT_STATE_LABELS.keys())


def test_reference_frame_labels() -> None:
    label = label_reference_frame("identity", yaw=15, expression="微笑", shot_scale="近景")
    assert "面部身份" in label
    assert "yaw=15" in label
    assert "微笑" in label


def test_prompt_no_source_video_reference() -> None:
    """提示词不含原片身份素材（INV-01）。"""
    prompt = compile_shot_prompt(shot_observation="测试")
    for banned in ("source_video", "reference_source", "原片", "原视频"):
        assert banned not in prompt.lower(), f"提示词包含禁止内容：{banned}"


def test_empty_dialogue_omitted() -> None:
    prompt = compile_shot_prompt(shot_observation="画面", approved_dialogue="")
    assert "Dialogue" not in prompt
