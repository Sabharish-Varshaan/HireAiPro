"""Drive a PydanticAI agent with a scripted FunctionModel: each step sees the
previous tool's return value and decides the next tool call. Lets tests
prove tools are registered and executed without depending on LLM quality."""

import json
from collections.abc import Callable
from typing import Any

from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

Step = Callable[[Any], tuple[str, dict]]


def scripted(steps: list[Step]) -> FunctionModel:
    state = {"i": 0}

    def fn(messages, info: AgentInfo) -> ModelResponse:
        last = None
        for part in messages[-1].parts:
            if isinstance(part, ToolReturnPart):
                last = part.content
                if hasattr(last, "model_dump"):
                    last = last.model_dump(mode="json")
        name, args = steps[min(state["i"], len(steps) - 1)](last)
        state["i"] += 1
        if name == "__final__":
            name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=json.dumps(args, default=str))])

    return FunctionModel(fn)


def call(name: str, **args) -> Step:
    return lambda last: (name, args)


def final(**args) -> Step:
    return lambda last: ("__final__", args)
