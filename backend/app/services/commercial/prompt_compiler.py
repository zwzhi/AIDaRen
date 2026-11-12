"""统一镜头提示词组装器。

融合 7 个开源 Skill 的最佳实践：
- Replicate prompt-videos：七要素分层（Subject/Context/Action/Style/Camera/Composition/Ambiance）
- image-storyboard：连续性约束（same person, same outfit, same lighting）
- video-storyboard：分镜=图+配对提示词输出（每锚帧保存完整提示词）
- shuohao-skills：角色/服装/道具/场景标签体系
- ecommerce-image-workflow：商品状态匹配（包装/开盖/质地/使用/效果）
- video-production-skills：审批前不执行昂贵生成

只使用已审核的模板文字与我方素材描述，不含原片身份素材（INV-01）。
"""

# 提示词七要素模板（来自 Replicate prompt-videos Skill）
SHOT_PROMPT_TEMPLATE = """Subject: {composition_and_subject}

Context: {context}
Action: {action}
Style: {style}
Camera: {camera}
Composition: {composition}
Ambiance: {ambiance}

Continuity requirements:
- Same person as the reference image: {actor_description}
- Same outfit: {wardrobe_description}
- Product shown: {product_description} in {product_state} state
- Do not change the person's identity, facial features, or body proportions
- Maintain consistent lighting and color grading across shots
"""

# 商品状态键标准化（来自 ecommerce-image-workflow Skill）
PRODUCT_STATE_LABELS = {
    "packaging": "sealed packaging / product box",
    "opening": "opening the package / uncapping",
    "dispensing": "dispensing / squeezing out product",
    "texture": "product texture close-up / swatch",
    "application": "applying the product (on face/hand)",
    "effect": "visible result after use",
}

# 参考帧角色标签（来自 shuohao-skills + avatar-skills）
REFERENCE_FRAME_ROLES = {
    "identity": "面部身份参考（正面/侧面清晰人脸）",
    "expression": "表情参考（微笑/严肃/惊讶等）",
    "shot_scale": "景别参考（特写/近景/中景/全景）",
    "pose": "姿态参考（站/坐/手持/转头等）",
    "wardrobe": "服装参考（穿着效果）",
    "prop": "道具参考（手持商品/工具等）",
}


def compile_shot_prompt(
    *,
    # 模板结构（来自校准后的模板）
    shot_observation: str = "",
    shot_inference: str = "",
    shot_action_template: str = "",
    # 我方素材
    actor_description: str = "",
    wardrobe_description: str = "",
    product_name: str = "",
    product_state: str = "",
    # 台词与时长
    approved_dialogue: str = "",
    duration_seconds: float = 0,
    # 画面设定
    aspect_ratio: str = "9:16",
) -> str:
    """组装单个镜头的完整生成提示词。

    遵循七要素分层模板，每个维度必须具体不模糊。
    连续性约束显式声明，防止跨镜头外观漂移。
    """
    subject = shot_observation or "达人面向镜头"
    if product_name:
        subject = f"{subject}，手持{product_name}"

    context = "室内简洁背景，适合商品展示" if not shot_inference else shot_inference
    action = shot_action_template or "自然展示商品，不遮挡产品标识"
    style = "高清商业广告风格，色彩自然，画面干净"
    camera = "固定机位，轻微推近" if duration_seconds <= 6 else "缓慢跟拍"
    composition = f"竖屏 {aspect_ratio} 构图，主体居中偏上，商品清晰可见"
    ambiance = "柔光，均匀照明，无强烈阴影"

    state_desc = PRODUCT_STATE_LABELS.get(product_state, product_state or "自然展示状态")

    prompt = SHOT_PROMPT_TEMPLATE.format(
        composition_and_subject=subject,
        context=context,
        action=action,
        style=style,
        camera=camera,
        composition=composition,
        ambiance=ambiance,
        actor_description=actor_description or "参考图中的人物",
        wardrobe_description=wardrobe_description or "参考图中的服装",
        product_description=product_name or "参考图中的商品",
        product_state=state_desc,
    )

    # 台词（如果有口播）
    if approved_dialogue.strip():
        prompt += f"\nDialogue (speak naturally in this exact wording): \"{approved_dialogue.strip()}\""

    return prompt.strip()


def compile_continuity_constraint(
    *,
    actor_appearance: str = "",
    wardrobe_color: str = "",
    product_position: str = "右手持商品",
) -> str:
    """跨镜头连续性约束片段（可附加到任何提示词末尾）。"""
    parts = ["Maintain exact continuity with previous shots:"]
    if actor_appearance:
        parts.append(f"- Person: {actor_appearance}")
    if wardrobe_color:
        parts.append(f"- Outfit color: {wardrobe_color} (unchanged)")
    parts.append(f"- Product position: {product_position}")
    return "\n".join(parts)


def label_reference_frame(role: str, **attrs) -> str:
    """为参考帧生成人类可读的标签描述。"""
    label = REFERENCE_FRAME_ROLES.get(role, role)
    extras = []
    if attrs.get("yaw") is not None:
        extras.append(f"yaw={attrs['yaw']}°")
    if attrs.get("expression"):
        extras.append(f"表情={attrs['expression']}")
    if attrs.get("shot_scale"):
        extras.append(f"景别={attrs['shot_scale']}")
    return f"{label}（{'，'.join(extras) or '标准'}）"
