import React, { useState } from "react";

export function AvailabilityBar({
  segments = [],
  uptimePercent = 100.0,
  range = "24h",
  mode = "beginner",
}) {
  const [hoveredSegment, setHoveredSegment] = useState(null);

  const getStatusColor = (status) => {
    switch (status) {
      case "healthy":
        return "#10B981"; // Emerald
      case "degraded":
        return "#F59E0B"; // Amber
      case "down":
        return "#EF4444"; // Rose
      case "nodata":
      default:
        return "rgba(255, 255, 255, 0.12)"; // Slate / Dim
    }
  };

  const getStatusLabel = (status, pct) => {
    switch (status) {
      case "healthy":
        return "100% Operational";
      case "degraded":
        return `Degraded (${pct}% operational)`;
      case "down":
        return `Service Outage (${pct}% operational)`;
      case "nodata":
      default:
        return "No probe history in this slice";
    }
  };

  return (
    <div className="availability-bar-widget" style={{ position: "relative" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
        <span className="metric-stat-label" style={{ fontSize: "0.82rem", fontWeight: 600 }}>
          {range.toUpperCase()} Availability Timeline
        </span>
        <span
          style={{
            fontSize: "0.85rem",
            fontWeight: 700,
            color: uptimePercent >= 99.0 ? "#10B981" : uptimePercent >= 95.0 ? "#F59E0B" : "#EF4444",
          }}
        >
          {uptimePercent.toFixed(1)}% uptime
        </span>
      </div>

      {/* Segmented Bar Track */}
      <div
        className="availability-segments-track"
        style={{
          display: "flex",
          gap: "3px",
          height: "28px",
          borderRadius: "6px",
          overflow: "hidden",
          background: "rgba(0, 0, 0, 0.2)",
          padding: "3px",
        }}
        onMouseLeave={() => setHoveredSegment(null)}
      >
        {segments.map((seg, idx) => (
          <div
            key={idx}
            className="availability-segment"
            style={{
              flex: 1,
              borderRadius: "3px",
              backgroundColor: getStatusColor(seg.status),
              cursor: "pointer",
              transition: "transform 0.15s ease, opacity 0.15s ease",
              transform: hoveredSegment?.index === idx ? "scaleY(1.15)" : "scaleY(1)",
              opacity: hoveredSegment && hoveredSegment.index !== idx ? 0.65 : 1,
            }}
            onMouseEnter={() => setHoveredSegment({ ...seg, index: idx })}
          />
        ))}
      </div>

      {/* Bottom Time Annotations */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: "6px",
          fontSize: "0.72rem",
          color: "var(--text-dim)",
          fontFamily: "var(--font-mono)",
        }}
      >
        <span>-{range}</span>
        <span>
          {mode === "beginner" ? (
            uptimePercent >= 99.0 ? "● Flawless uptime" : "▲ Minor degradation detected"
          ) : (
            `${segments.filter((s) => s.status !== "nodata").length} Active Time Slices`
          )}
        </span>
        <span>Now</span>
      </div>

      {/* Floating Segment Tooltip */}
      {hoveredSegment && (
        <div
          className="availability-tooltip glass-panel"
          style={{
            position: "absolute",
            left: `${((hoveredSegment.index + 0.5) / (segments.length || 1)) * 100}%`,
            bottom: "45px",
            transform:
              hoveredSegment.index > segments.length * 0.7
                ? "translateX(-90%)"
                : hoveredSegment.index < segments.length * 0.3
                ? "translateX(-10%)"
                : "translateX(-50%)",
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
          <div style={{ fontWeight: 600, color: "var(--text-primary)", marginBottom: "3px" }}>
            {new Date(hoveredSegment.timestamp).toLocaleString([], {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </div>
          <div style={{ color: getStatusColor(hoveredSegment.status), fontWeight: 600 }}>
            {getStatusLabel(hoveredSegment.status, hoveredSegment.availability_percent)}
          </div>
          {mode === "engineer" && hoveredSegment.total_count > 0 && (
            <div style={{ fontSize: "0.72rem", color: "var(--text-dim)", marginTop: "2px" }}>
              Total Probes in Slice: {hoveredSegment.total_count}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
