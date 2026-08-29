from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(frozen=True)
class ExecutionAlgorithmConfig:
    """Shared configuration for a Nautilus execution algorithm."""

    exec_algorithm_id: str
    exec_algorithm_path: str
    config_path: str
    config: dict[str, Any] = field(default_factory=dict)
    order_params: dict[str, Any] = field(default_factory=dict)

    def to_importable_config(self):
        from nautilus_trader.config import ImportableExecAlgorithmConfig

        config = dict(self.config)
        configured_id = config.get("exec_algorithm_id")
        if configured_id is not None and str(configured_id) != self.exec_algorithm_id:
            raise ValueError(
                "execution_algorithm.config.exec_algorithm_id must match "
                "execution_algorithm.exec_algorithm_id",
            )
        config["exec_algorithm_id"] = self.exec_algorithm_id
        return ImportableExecAlgorithmConfig(
            exec_algorithm_path=self.exec_algorithm_path,
            config_path=self.config_path,
            config=config,
        )


def execution_algorithm_config_from_payload(
    payload: dict[str, Any] | None,
) -> ExecutionAlgorithmConfig | None:
    if payload is None:
        return None
    return ExecutionAlgorithmConfig(**payload)
