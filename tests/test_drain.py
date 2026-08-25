from src.core.drain_filter import DrainFilter, compression_ratio


def _oom_lines(count: int) -> list[str]:
    return [
        f"2026-08-25T10:{i:02d}:00Z ERROR OOMKilled pod checkout-7d9f{i} memory limit exceeded"
        for i in range(count)
    ]


def test_similar_lines_collapse_into_one_template():
    clusters = DrainFilter().cluster(_oom_lines(50))
    assert len(clusters) == 1
    assert clusters[0].count == 50
    assert "OOMKilled" in clusters[0].template


def test_distinct_patterns_stay_separate():
    lines = _oom_lines(5) + ["INFO connection pool resized to 20"] * 3
    clusters = DrainFilter().cluster(lines)
    assert len(clusters) == 2


def test_errors_rank_above_info():
    lines = ["INFO heartbeat ok"] * 40 + _oom_lines(2)
    clusters = DrainFilter().cluster(lines)
    assert clusters[0].severity_hint == "ERROR"


def test_blank_lines_are_ignored():
    assert DrainFilter().cluster(["", "   ", "\n"]) == []


def test_samples_are_capped():
    cluster = DrainFilter().cluster(_oom_lines(20))[0]
    assert len(cluster.sample_lines) <= cluster.MAX_SAMPLES


def test_compression_ratio():
    assert compression_ratio(100, 10) == 0.9
    assert compression_ratio(0, 0) == 0.0
