import React, { useEffect, useRef, useState } from "react";

// A real conversation with the copilot. Breadcrumbs show which read-only tools
// it consulted, so an answer can be checked rather than taken on trust.

function Breadcrumbs({ tools }) {
  if (!tools || tools.length === 0) return null;
  return (
    <div className="copilot-breadcrumbs">
      {tools.map((tool, index) => (
        <span key={index} className={`breadcrumb ${tool.ok ? "" : "breadcrumb-failed"}`}>
          {tool.ok ? "checked" : "failed"} {tool.name.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

function Citations({ citations, mode }) {
  // Raw tool payloads are detail an engineer wants and a beginner does not.
  if (mode !== "engineer" || !citations || citations.length === 0) return null;
  return (
    <details className="copilot-citations">
      <summary>Evidence used ({citations.length})</summary>
      {citations.map((citation, index) => (
        <pre key={index} className="copilot-citation">
          {citation.tool}({JSON.stringify(citation.arguments)}){"\n"}
          {JSON.stringify(citation.data, null, 2)}
        </pre>
      ))}
    </details>
  );
}

export function CopilotPage({ api, mode, showToast }) {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const endRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    api
      .copilotSuggestions()
      .then((items) => {
        if (!cancelled) setSuggestions(items || []);
      })
      .catch(() => {
        // Starter prompts are a convenience; failing to load them is not an error.
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  useEffect(() => {
    if (endRef.current) endRef.current.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  const send = async (text) => {
    const trimmed = (text || "").trim();
    if (!trimmed || isThinking) return;

    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setQuestion("");
    setIsThinking(true);

    try {
      const reply = await api.copilotChat({ question: trimmed, session_id: sessionId });
      setSessionId(reply.session_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: reply.answer,
          tools: reply.tools_used,
          citations: reply.citations,
          degraded: reply.degraded,
          model: reply.model,
        },
      ]);
    } catch (err) {
      showToast(err.message, "error");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `I could not answer that: ${err.message}`, error: true },
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  return (
    <div className="page copilot-page">
      <header className="page-header">
        <div>
          <h1>AI Copilot</h1>
          <p className="page-subtitle">
            Ask about your applications. Answers cite real health checks, commits and past
            incidents. The copilot can read your telemetry but cannot change anything.
          </p>
        </div>
      </header>

      {messages.length === 0 && (
        <div className="copilot-empty">
          <p className="copilot-empty-title">Try asking</p>
          <div className="copilot-suggestions">
            {suggestions.map((item) => (
              <button
                key={item}
                type="button"
                className="btn btn-secondary"
                onClick={() => send(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="copilot-thread">
        {messages.map((message, index) => (
          <div key={index} className={`copilot-message copilot-${message.role}`}>
            {message.role === "assistant" && <Breadcrumbs tools={message.tools} />}
            <div className={`copilot-bubble ${message.error ? "copilot-bubble-error" : ""}`}>
              {message.content.split("\n").map((line, lineIndex) => (
                <p key={lineIndex}>{line}</p>
              ))}
            </div>
            {message.degraded && (
              <p className="copilot-note">
                No language model is configured, so this is a direct data summary rather than an
                analysis.
              </p>
            )}
            <Citations citations={message.citations} mode={mode} />
          </div>
        ))}
        {isThinking && (
          <div className="copilot-message copilot-assistant">
            <div className="copilot-bubble copilot-thinking">Looking at your telemetry...</div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="copilot-composer"
        onSubmit={(event) => {
          event.preventDefault();
          send(question);
        }}
      >
        <input
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Why is my application slow?"
          aria-label="Ask the copilot a question"
          disabled={isThinking}
        />
        <button type="submit" className="btn btn-primary" disabled={isThinking || !question.trim()}>
          {isThinking ? "Thinking..." : "Ask"}
        </button>
      </form>
    </div>
  );
}
