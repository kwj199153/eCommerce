"""技能模块 提示词（**业务资产**）。

★ 第 283 轮 A 档：图标提示词从 `icon.py` 归位到这里并注册为 `"skills_icon"`。
  取用方 `icon.py::_llm_generate` 走 `get_prompt_template("skills_icon")`。
"""
from ai_infra.llm import register_prompt_template

ICON_SYSTEM_PROMPT = (
    "你是图标选择助手。根据用户给出的技能名称与用途，"
    "返回**一个**最能代表它的 emoji 作为图标。\n"
    "要求：\n"
    "1. 只输出这一个 emoji，不要任何其他文字、标点、引号或解释；\n"
    "2. 选含义直观的通用 emoji（例如利润→💰、价格→🏷、评论→💬、"
    "广告→📣、标题→📝、图→🖼、复盘→📊、客服→🎧）；\n"
    "3. 不要用国旗、手势、人脸这类与业务无关的。"
)

register_prompt_template("skills_icon", ICON_SYSTEM_PROMPT)

__all__ = ["ICON_SYSTEM_PROMPT"]
