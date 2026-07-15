{/*WelcomeScreen.jsx*/ }
import React from 'react';

const SUGGESTIONS = [
  'Summarize the main topics in this document',
  'What are the key findings?',
  'List the most important concepts',
  'What conclusions are drawn?',
  'Give me an overview of this document',
];

export default function WelcomeScreen({ onSuggestion, hasDoc }) {
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      padding: '40px 32px',
      gap: '0',
      animation: 'fadeIn 0.4s ease',
    }}>
      {/* Icon ring */}
      <div style={{
        width: '68px',
        height: '68px',
        borderRadius: '50%',
        background: 'var(--accent-dim)',
        border: '1px solid rgba(91,110,245,0.25)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: '22px',
      }}>
        <i className="ti ti-message-dots" style={{
          fontSize: '30px',
          color: 'var(--accent-light)',
        }} />
      </div>

      <h2 style={{
        fontFamily: 'var(--font-head)',
        fontSize: '28px',
        fontWeight: 400,
        color: 'var(--text)',
        marginBottom: '12px',
        letterSpacing: '-0.3px',
      }}>
        What would you like to know?
      </h2>

      <p style={{
        fontSize: '14px',
        color: 'var(--text2)',
        maxWidth: '380px',
        lineHeight: 1.8,
        marginBottom: '32px',
      }}>
        {hasDoc
          ? 'Your document is ready. Ask me anything about its contents.'
          : 'Upload a PDF from the sidebar, then ask me anything about it.'}
      </p>

      {/* Suggestion chips */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '8px',
        justifyContent: 'center',
        maxWidth: '500px',
      }}>
        {SUGGESTIONS.map((s, i) => (
          <button
            key={i}
            onClick={() => onSuggestion(s)}
            disabled={!hasDoc}
            style={{
              padding: '8px 15px',
              background: 'var(--surface2)',
              border: '1px solid var(--border2)',
              borderRadius: '20px',
              fontSize: '12px',
              color: hasDoc ? 'var(--text2)' : 'var(--text3)',
              cursor: hasDoc ? 'pointer' : 'not-allowed',
              fontFamily: 'var(--font-body)',
              transition: 'all var(--transition)',
            }}
            onMouseEnter={e => {
              if (hasDoc) {
                e.currentTarget.style.borderColor = 'var(--accent)';
                e.currentTarget.style.color = 'var(--accent-light)';
                e.currentTarget.style.background = 'var(--accent-glow)';
              }
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--border2)';
              e.currentTarget.style.color = hasDoc ? 'var(--text2)' : 'var(--text3)';
              e.currentTarget.style.background = 'var(--surface2)';
            }}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
