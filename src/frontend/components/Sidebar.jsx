import React from "react";

export function Sidebar({ activeTab, onSelectTab, incidentCount = 0, applicationCount = 0 }) {
  const primaryNavItems = [
    { id: "overview", label: "Overview", icon: "✦", badge: null },
    { id: "applications", label: "Applications", icon: "▦", badge: applicationCount > 0 ? applicationCount : null },
    { id: "incidents", label: "Incidents", icon: "⚠", badge: incidentCount > 0 ? incidentCount : null, alert: incidentCount > 0 },
    { id: "copilot", label: "AI Copilot", icon: "💬", badge: "AI" },
    { id: "runbooks", label: "Runbooks", icon: "⚡", badge: null },
    { id: "knowledge", label: "Knowledge", icon: "📖", badge: null },
  ];

  const secondaryNavItems = [
    { id: "triage", label: "Triage Playground", icon: "🔬" },
    { id: "settings", label: "Settings", icon: "⚙" },
  ];

  return (
    <aside className="app-sidebar">
      <div className="sidebar-section">
        <span className="sidebar-section-title">Operations</span>
        <nav className="sidebar-nav">
          {primaryNavItems.map((item) => {
            const isActive = activeTab === item.id
              || (item.id === "incidents" && activeTab === "incident-detail")
              || (item.id === "applications" && activeTab === "application-detail");
            return (
              <button
                key={item.id}
                type="button"
                className={`sidebar-nav-item ${isActive ? "active" : ""}`}
                onClick={() => onSelectTab(item.id)}
              >
                <span className="nav-item-icon">{item.icon}</span>
                <span className="nav-item-label">{item.label}</span>
                {item.badge && (
                  <span className={`nav-item-badge ${item.alert ? "alert-badge" : ""}`}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="sidebar-section">
        <span className="sidebar-section-title">Settings & Tools</span>
        <nav className="sidebar-nav">
          {secondaryNavItems.map((item) => {
            const isActive = activeTab === item.id
              || (item.id === "incidents" && activeTab === "incident-detail")
              || (item.id === "applications" && activeTab === "application-detail");
            return (
              <button
                key={item.id}
                type="button"
                className={`sidebar-nav-item ${isActive ? "active" : ""}`}
                onClick={() => onSelectTab(item.id)}
              >
                <span className="nav-item-icon">{item.icon}</span>
                <span className="nav-item-label">{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <div className="sidebar-footer">
        <div className="footer-status-box">
          <span className="footer-status-label">OpsMind Engine</span>
          <span className="footer-status-version">v1.0.0 · Production</span>
        </div>
      </div>
    </aside>
  );
}
