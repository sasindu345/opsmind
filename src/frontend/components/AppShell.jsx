import React from "react";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";

export function AppShell({
  activeTab,
  onSelectTab,
  systemStatus,
  incidentCount = 0,
  applicationCount = 0,
  mode = "beginner",
  onModeToggle,
  onOpenSearch,
  children,
}) {
  return (
    <div className={`opsmind-app-shell mode-${mode}`}>
      <TopBar
        systemStatus={systemStatus}
        activeIncidentCount={incidentCount}
        mode={mode}
        onModeToggle={onModeToggle}
        onOpenSearch={onOpenSearch}
        appEnv={systemStatus?.app_env || "production"}
      />
      <div className="shell-body">
        <Sidebar
          activeTab={activeTab}
          onSelectTab={onSelectTab}
          incidentCount={incidentCount}
          applicationCount={applicationCount}
        />
        <main className="shell-main-content">
          <div className="content-container">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
