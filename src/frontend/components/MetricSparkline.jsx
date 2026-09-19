import React, { useState, useMemo } from "react";

export function MetricSparkline({
  series = [],
  p95 = 0,
  avg = 0,
  isLoading = false,
  mode = "beginner",
}) {
  const [hoverIndex, setHoverIndex] = useState(null);

  // Filter series points or check if empty
  const validPoints = useMemo(() => {
    return series.filter((p) => p.total_count > 0 || p.avg_latency_ms > 0);
  }, [series]);

  // Chart dimensions
  const width = 600;
  const height = 180;
  const padding = { top: 20, right: 30, bottom: 30, left: 50 };

  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;

  // Compute domain
  const { minVal, maxVal } = useMemo(() => {
    if (series.length === 0) return { minVal: 0, maxVal: 100 };
    const maxLatency = Math.max(...series.map((p) => p.max_latency_ms || p.avg_latency_ms || 0), p95, avg, 50);
    // Add 20% headroom
    return {
      minVal: 0,
      maxVal: Math.ceil((maxLatency * 1.25) / 10) * 10,
    };
  }, [series, p95, avg]);

  // Map series to SVG coordinates
  const coordinates = useMemo(() => {
    if (series.length < 2) return [];
    return series.map((p, idx) => {
      const x = padding.left + (idx / (series.length - 1)) * innerWidth;
      const yVal = p.avg_latency_ms || 0;
      const y = padding.top + innerHeight - (yVal / (maxVal || 1)) * innerHeight;
      return { x, y, point: p, index: idx };
    });
  }, [series, innerWidth, innerHeight, maxVal, padding.left, padding.top]);

  // Generate SVG path string
  const linePath = useMemo(() => {
    if (coordinates.length < 2) return "";
    return coordinates.reduce((acc, curr, idx) => {
      return idx === 0 ? `M ${curr.x} ${curr.y}` : `${acc} L ${curr.x} ${curr.y}`;
    }, "");
  }, [coordinates]);

  // Generate Area path string
  const areaPath = useMemo(() => {
    if (coordinates.length < 2) return "";
    const firstX = coordinates[0].x;
    const lastX = coordinates[coordinates.length - 1].x;
    const bottomY = padding.top + innerHeight;
    return `${linePath} L ${lastX} ${bottomY} L ${firstX} ${bottomY} Z`;
  }, [linePath, coordinates, innerHeight, padding.top]);

  // P95 line Y coordinate
  const p95Y = useMemo(() => {
    if (!p95 || maxVal === 0) return null;
    return padding.top + innerHeight - (p95 / maxVal) * innerHeight;
  }, [p95, maxVal, innerHeight, padding.top]);

  // Grid lines
  const yTicks = [0, Math.round(maxVal * 0.5), Math.round(maxVal)];

  if (isLoading) {
    return (
      <div className="metric-sparkline-placeholder glass-panel">
        <div className="spinner" style={{ width: "24px", height: "24px" }} />
        <span style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>Aggregating telemetry buckets...</span>
      </div>
    );
  }

  if (series.length === 0 || validPoints.length === 0) {
    return (
      <div className="metric-sparkline-placeholder glass-panel">
        <div style={{ fontSize: "1.4rem", marginBottom: "4px" }}>📈</div>
        <p style={{ margin: 0, fontWeight: 600, color: "var(--text-primary)" }}>No Response Time Samples</p>
        <p style={{ margin: "4px 0 0", fontSize: "0.8rem", color: "var(--text-secondary)" }}>
          Synthetic health checks will automatically populate this response-time trend. You can also click "Check Now" above.
        </p>
      </div>
    );
  }

  const activePoint = hoverIndex !== null && coordinates[hoverIndex] ? coordinates[hoverIndex] : null;

  return (
    <div className="metric-sparkline-container" style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="metric-sparkline-svg"
        style={{ width: "100%", height: "auto", display: "block" }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        <defs>
          <linearGradient id="latencyGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#06B6D4" stopOpacity="0.35" />
            <stop offset="85%" stopColor="#06B6D4" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#06B6D4" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Background Grid Lines & Y Axis Labels */}
        {yTicks.map((val) => {
          const y = padding.top + innerHeight - (val / (maxVal || 1)) * innerHeight;
          return (
            <g key={val} className="sparkline-grid-row">
              <line
                x1={padding.left}
                y1={y}
                x2={padding.left + innerWidth}
                y2={y}
                stroke="rgba(255, 255, 255, 0.08)"
                strokeDasharray={val === 0 ? "none" : "3,3"}
              />
              <text
                x={padding.left - 8}
                y={y + 4}
                textAnchor="end"
                fontSize="10"
                fill="var(--text-dim)"
                fontFamily="var(--font-mono)"
              >
                {val}ms
              </text>
            </g>
          );
        })}

        {/* P95 Reference Line */}
        {p95Y !== null && p95Y >= padding.top && (
          <g className="sparkline-p95-reference">
            <line
              x1={padding.left}
              y1={p95Y}
              x2={padding.left + innerWidth}
              y2={p95Y}
              stroke="#F59E0B"
              strokeWidth="1.2"
              strokeDasharray="4,4"
              opacity="0.8"
            />
            <text
              x={padding.left + innerWidth - 4}
              y={p95Y - 4}
              textAnchor="end"
              fontSize="9"
              fill="#F59E0B"
              fontFamily="var(--font-mono)"
            >
              p95: {Math.round(p95)}ms
            </text>
          </g>
        )}

        {/* Gradient Area Fill */}
        {areaPath && <path d={areaPath} fill="url(#latencyGradient)" />}

        {/* Primary Latency Trend Line */}
        {linePath && (
          <path
            d={linePath}
            fill="none"
            stroke="#06B6D4"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* Interactive Hover Columns & Crosshairs */}
        {coordinates.map((c) => (
          <rect
            key={c.index}
            x={c.x - (innerWidth / (coordinates.length || 1)) / 2}
            y={padding.top}
            width={innerWidth / (coordinates.length || 1)}
            height={innerHeight}
            fill="transparent"
            style={{ cursor: "crosshair" }}
            onMouseEnter={() => setHoverIndex(c.index)}
          />
        ))}

        {/* Active Hover Target */}
        {activePoint && (
          <g>
            <line
              x1={activePoint.x}
              y1={padding.top}
              x2={activePoint.x}
              y2={padding.top + innerHeight}
              stroke="#38BDF8"
              strokeWidth="1"
              strokeDasharray="2,2"
            />
            <circle
              cx={activePoint.x}
              cy={activePoint.y}
              r="4.5"
              fill="#06B6D4"
              stroke="#FFFFFF"
              strokeWidth="2"
            />
          </g>
        )}

        {/* X-Axis time start and end */}
        {coordinates.length > 0 && (
          <g className="sparkline-xaxis-labels">
            <text
              x={padding.left}
              y={height - 8}
              textAnchor="start"
              fontSize="10"
              fill="var(--text-dim)"
              fontFamily="var(--font-mono)"
            >
              {new Date(coordinates[0].point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </text>
            <text
              x={padding.left + innerWidth}
              y={height - 8}
              textAnchor="end"
              fontSize="10"
              fill="var(--text-dim)"
              fontFamily="var(--font-mono)"
            >
              {new Date(coordinates[coordinates.length - 1].point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </text>
          </g>
        )}
      </svg>

      {/* Floating Hover Tooltip */}
      {activePoint && (
        <div
          className="sparkline-tooltip glass-panel"
          style={{
            position: "absolute",
            left: `${(activePoint.x / width) * 100}%`,
            top: "10px",
            transform: activePoint.x > width * 0.7 ? "translateX(-105%)" : "translateX(10px)",
            pointerEvents: "none",
            zIndex: 10,
            padding: "8px 12px",
            borderRadius: "6px",
            fontSize: "0.78rem",
            whiteSpace: "nowrap",
            boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
            border: "1px solid rgba(255,255,255,0.15)",
          }}
        >
          <div style={{ fontWeight: 600, color: "var(--text-primary)", marginBottom: "4px" }}>
            {new Date(activePoint.point.timestamp).toLocaleString([], {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", color: "var(--accent-cyan)" }}>
            <span>Latency:</span>
            <strong>{activePoint.point.avg_latency_ms > 0 ? `${Math.round(activePoint.point.avg_latency_ms)} ms` : "No activity"}</strong>
          </div>
          {mode === "engineer" && (
            <div style={{ fontSize: "0.72rem", color: "var(--text-dim)", marginTop: "4px" }}>
              <span>Min: {Math.round(activePoint.point.min_latency_ms)}ms</span> ·{" "}
              <span>Max: {Math.round(activePoint.point.max_latency_ms)}ms</span> ·{" "}
              <span>Probes: {activePoint.point.total_count}</span>
            </div>
          )}
          {activePoint.point.failure_count > 0 && (
            <div style={{ color: "#F87171", fontSize: "0.72rem", marginTop: "2px" }}>
              ⚠️ {activePoint.point.failure_count} failed probe{activePoint.point.failure_count > 1 ? "s" : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
