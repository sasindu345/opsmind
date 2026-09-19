"""Drain3 log clustering.

Raw log streams are massively repetitive: a crash-looping pod emits the same
line hundreds of times with only an id or timestamp changing. Drain3 collapses
those into a single template plus a count, which is what actually goes into the
LLM prompt — typically an 80%+ reduction in tokens.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

DRAIN3_CONFIG_PATH = PROJECT_ROOT / "config" / "drain3.ini"

# Leading severity token, e.g. "2026-08-25T10:11:12Z ERROR ..." or "[warn] ...".
_LEVEL_PATTERN = re.compile(
    r"\b(CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\b", re.IGNORECASE
)
_SEVERITY_RANK = {
    "FATAL": 5,
    "CRITICAL": 5,
    "ERROR": 4,
    "WARNING": 3,
    "WARN": 3,
    "INFO": 2,
    "DEBUG": 1,
    "TRACE": 1,
}


@dataclass
class LogCluster:
    """One pattern discovered across a batch of log lines."""

    cluster_id: int
    template: str
    count: int = 0
    levels: set[str] = field(default_factory=set)
    sample_lines: list[str] = field(default_factory=list)
    parameters: list[list[str]] = field(default_factory=list)

    MAX_SAMPLES = 3

    @property
    def severity_hint(self) -> str:
        """Highest log level seen in this cluster, or ``UNKNOWN``."""
        if not self.levels:
            return "UNKNOWN"
        return max(self.levels, key=lambda level: _SEVERITY_RANK.get(level, 0))

    def add(self, line: str, parameters: list[str]) -> None:
        self.count += 1
        if match := _LEVEL_PATTERN.search(line):
            self.levels.add(match.group(1).upper())
        if len(self.sample_lines) < self.MAX_SAMPLES:
            self.sample_lines.append(line)
        if parameters and len(self.parameters) < self.MAX_SAMPLES:
            self.parameters.append(parameters)

    def to_prompt_dict(self) -> dict[str, object]:
        """Compact representation handed to the LLM."""
        return {
            "template": self.template,
            "occurrences": self.count,
            "level": self.severity_hint,
            "sample": self.sample_lines[0] if self.sample_lines else "",
        }


class DrainFilter:
    """Wraps a Drain3 ``TemplateMiner``.

    State is kept in memory per instance: each analysis request gets a fresh
    filter so clusters from unrelated services never bleed together.
    """

    def __init__(self, config_path=DRAIN3_CONFIG_PATH) -> None:
        config = TemplateMinerConfig()
        if config_path and config_path.exists():
            config.load(str(config_path))
        else:
            logger.warning("drain3 config not found at %s — using defaults", config_path)
        config.profiling_enabled = False
        self._miner = TemplateMiner(config=config)

    def cluster(self, lines: list[str]) -> list[LogCluster]:
        """Cluster ``lines`` into templates, most frequent first."""
        clusters: dict[int, LogCluster] = {}

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            result = self._miner.add_log_message(line)
            cluster_id = result["cluster_id"]
            template = result["template_mined"]
            cluster = clusters.get(cluster_id)
            if cluster is None:
                cluster = LogCluster(cluster_id=cluster_id, template=template)
                clusters[cluster_id] = cluster
            # A late-arriving line can generalise the template further.
            cluster.template = template
            cluster.add(line, self._miner.extract_parameters(template, line) or [])

        return sorted(
            clusters.values(),
            key=lambda c: (_SEVERITY_RANK.get(c.severity_hint, 0), c.count),
            reverse=True,
        )


def compression_ratio(line_count: int, cluster_count: int) -> float:
    """Fraction of lines eliminated by clustering (0.0–1.0)."""
    if line_count <= 0:
        return 0.0
    return round(1 - (cluster_count / line_count), 4)
