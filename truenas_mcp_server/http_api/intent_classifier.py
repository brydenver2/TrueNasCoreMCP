"""Simple keyword-based intent classifier for TrueNAS domains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List


class IntentClassifierBase(ABC):
    """Base class for intent classifiers."""

    @abstractmethod
    def classify_intent(self, query: str) -> List[str]:
        raise NotImplementedError


class KeywordIntentClassifier(IntentClassifierBase):
    """Map natural language queries to task types using keyword heuristics."""

    def __init__(self, keyword_mappings: Dict[str, List[str]] | None = None) -> None:
        self.keyword_mappings = keyword_mappings or self._default_keywords()

    def classify_intent(self, query: str) -> List[str]:
        lowered = query.lower()
        matches: list[str] = []

        for task_type, keywords in self.keyword_mappings.items():
            if any(keyword in lowered for keyword in keywords):
                matches.append(task_type)

        return matches

    def _default_keywords(self) -> Dict[str, List[str]]:
        return {
            "user-ops": ["user", "account", "permission", "login", "ssh"],
            "storage-ops": [
                "pool",
                "zfs",
                "dataset",
                "volume",
                "quota",
                "replication",
                "disk",
            ],
            "sharing-ops": ["smb", "cifs", "nfs", "share", "iscsi", "afp"],
            "snapshot-ops": ["snapshot", "rollback", "clone", "replica"],
            "apps-ops": ["app", "chart", "helm", "docker", "compose"],
            "instance-ops": ["incus", "vm", "virtual", "guest"],
            "vm-ops": ["bhyve", "legacy vm", "virt"],
            "debug-ops": ["debug", "diagnostic", "trace"],
            "meta-ops": ["tool", "metadata", "list tools"],
        }

    def get_keyword_mappings(self) -> Dict[str, List[str]]:
        return self.keyword_mappings
