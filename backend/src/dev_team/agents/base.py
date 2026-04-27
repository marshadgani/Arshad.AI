"""DevAgent ABC.

Each concrete agent is ~30 lines: declarative class attributes (slug,
output_dir, schemas, prompt path) plus an optional `build_user_message`
override for agents that need to assemble more than just `payload.json()`.

Behaviour is 100% prompt-driven. No business logic in the class.
"""

from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from ..llm import structured_call
from ..storage import repo_root, write_artifact


class DevAgent(ABC):
    name: ClassVar[str]  # short slug (ba, ea, sa, ...)
    output_dir: ClassVar[str]  # tasks/agent-outputs/<dir>/
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]
    prompt_file: ClassVar[str]  # filename in prompts/

    @classmethod
    def system_prompt(cls) -> str:
        path = Path(__file__).resolve().parent.parent / "prompts" / cls.prompt_file
        return path.read_text()

    def build_user_message(
        self, *, feature_id: str, payload: BaseModel, **extra: Any
    ) -> str:
        """Default: 'Feature ID: <id>\n\nInput:\n<json>'. Subclasses override
        when they need to inject additional context (e.g., timestamp for PO,
        previous code for BugFixer).
        """
        return (
            f"Feature ID: {feature_id}\n\nInput:\n{payload.model_dump_json(indent=2)}"
        )

    async def run(
        self,
        *,
        feature_id: str,
        payload: BaseModel,
        suffix: str = "",
        **extra: Any,
    ) -> BaseModel:
        if not isinstance(payload, self.input_schema):
            raise TypeError(
                f"{self.name}.run expected {self.input_schema.__name__}, "
                f"got {type(payload).__name__}"
            )
        user_message = self.build_user_message(
            feature_id=feature_id, payload=payload, **extra
        )
        result = await structured_call(
            system=self.system_prompt(),
            user_message=user_message,
            output_schema=self.output_schema,
        )
        write_artifact(
            agent_dir=self.output_dir,
            feature_id=feature_id,
            payload=result,
            suffix=suffix,
        )
        return result


def repo_relative(p: Path) -> str:
    try:
        return str(p.relative_to(repo_root()))
    except ValueError:
        return str(p)
