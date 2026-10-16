"""可选的 LLM 适配器。

TravelMind 的核心修复/重规划逻辑是确定性的规则引擎;LLM 只用于"提出候选",
其输出必须再次经过 Pydantic 校验与规则引擎复检才会被采纳。

- `FakeLLM`:测试用,返回预置文本,不访问网络。
- `build_repair_llm()`:真实场景下返回一个 `(prompt) -> str` 可调用对象;
  仅在 `TRAVELMIND_ENABLE_LLM_REPAIR=true` 且配置了 LLM Key 时启用。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from ...config import get_settings

RepairLLM = Callable[[str], str]


class FakeLLM:
    """测试/演示用 LLM:按顺序返回预置响应。"""

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        self.responses = list(responses or [])
        self.calls: List[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            raise RuntimeError("FakeLLM 没有更多预置响应")
        return self.responses.pop(0)


def build_repair_llm() -> Optional[RepairLLM]:
    """按配置构建真实 LLM 调用;不可用时返回 None。"""
    settings = get_settings()
    if not getattr(settings, "travelmind_enable_llm_repair", False):
        return None
    try:
        from ..llm_service import get_llm

        llm = get_llm()
    except Exception:
        return None

    def _call(prompt: str) -> str:
        return llm.invoke([{"role": "user", "content": prompt}])

    return _call
