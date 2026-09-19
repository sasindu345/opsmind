import React from "react";

export function KnowledgePage({
  query,
  onQuery,
  onSearch,
  isSearching,
  results,
  onOpenPostmortem,
  mode = "beginner",
}) {
  return (
    <div className="knowledge-page">
      <div className="page-header-row">
        <div className="page-header-titles">
          <h1>Knowledge</h1>
          <p>
            {mode === "beginner"
              ? "Search past incidents and how they were fixed."
              : "Search incident memory. Engineer mode also shows match strength."}
          </p>
        </div>
      </div>

      <div className="card glass-panel memory-search-card">
        <div className="search-bar-row">
          <input
            type="text"
            className="form-control flex-1"
            placeholder="Try connection timeout, memory, or deployment"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
          />
          <button type="button" className="btn btn-primary" onClick={onSearch} disabled={isSearching}>
            {isSearching ? "Searching..." : "Search"}
          </button>
        </div>
      </div>

      <div className="memory-results-container">
        {results === null ? (
          <div className="empty-state-placeholder glass-panel">
            <p>Search past outages to see what fixed them.</p>
          </div>
        ) : results.length === 0 ? (
          <div className="empty-state-placeholder glass-panel">
            <p>No matching past incidents.</p>
          </div>
        ) : (
          results.map(({ item, score }) => (
            <div key={item.incident_id} className="glass-panel memory-result-card">
              <div className="memory-card-header">
                <strong>{item.title || "Past incident"}</strong>
                <span className="beginner-only">Similar past incident</span>
                <span className="engineer-only score-badge">{score}% match</span>
              </div>
              <p>{item.probable_cause || "No cause recorded."}</p>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => onOpenPostmortem(item.incident_id)}>
                Open resolution
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
