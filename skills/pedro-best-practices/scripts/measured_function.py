"""One function's complexity scores and the limits they are held to."""

from __future__ import annotations

from dataclasses import dataclass, field

PEDRO_LIMITS = {"cognitive": 8, "cyclomatic": 16}


@dataclass
class Function:
    path: str
    name: str
    line: int
    end_line: int
    cognitive: int | None = None
    cyclomatic: int | None = None
    # metric -> (severity, repository max) for metrics the repository's own lint flags;
    # None when no repository lint was consulted.
    lint: dict[str, tuple[str, int | None]] | None = None
    limits: dict[str, int] = field(default_factory=lambda: dict(PEDRO_LIMITS))

    def score(self, metric: str) -> int | None:
        return self.cognitive if metric == "cognitive" else self.cyclomatic

    def excess(self) -> dict[str, int]:
        """metric -> the limit it exceeds (the stricter of Pedro's and the repository's)."""
        over = {}
        for metric, limit in self.limits.items():
            score = self.score(metric)
            if score is None:
                continue
            flagged = (self.lint or {}).get(metric)
            if flagged and flagged[1] is not None:
                limit = min(limit, flagged[1])
            if score > limit or flagged:
                over[metric] = limit
        return over

    def over(self) -> list[str]:
        return [f"{metric} {self.score(metric)} > {limit}" for metric, limit in self.excess().items()]

    def lint_tag(self) -> str:
        if self.lint is None:
            return " [not lint-checked]"
        severities = {self.lint[m][0] for m in self.excess() if m in self.lint}
        if "error" in severities:
            return " [lint: error]"
        return " [lint: warning]" if severities else " [lint passes]"
