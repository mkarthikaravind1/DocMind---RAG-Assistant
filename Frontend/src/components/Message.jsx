// Message.jsx
import React, { useState } from 'react';

export function TypingBubble() {
  return (
    <div style={{
      display: 'flex',
      gap: '12px',
      animation: 'fadeUp 0.3s ease',
      maxWidth: '75%',
    }}>
      <div style={{
        width: '32px',
        height: '32px',
        borderRadius: '50%',
        background: 'linear-gradient(135deg, var(--accent) 0%, #8b5cf6 100%)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: '14px',
        color: 'white',
        flexShrink: 0,
        marginTop: '2px',
      }}>
        <i className="ti ti-brain" />
      </div>
      <div style={{
        padding: '14px 18px',
        borderRadius: 'var(--radius-lg)',
        borderTopLeftRadius: 'var(--radius-sm)',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        display: 'flex',
        gap: '5px',
        alignItems: 'center',
        boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
      }}>
        {[0, 0.2, 0.4].map((delay, i) => (
          <span key={i} style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            background: 'var(--text3)',
            display: 'block',
            animation: `bounce 1.2s ${delay}s infinite`,
          }} />
        ))}
      </div>
    </div>
  );
}

// The LLM answers with light Markdown and numbered citations such as [1].
// Render **bold** as real bold text and each [n] as a small clickable marker
// (as React elements, never as raw HTML).
function renderText(text, sourceIds, openId, onCite) {
  return String(text).split(/(\*\*[^*\n]+\*\*|\[\d+\])/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    const cite = /^\[(\d+)\]$/.exec(part);
    if (cite && sourceIds.has(Number(cite[1]))) {
      const id = Number(cite[1]);
      const active = openId === id;
      return (
        <button
          key={i}
          onClick={() => onCite(id)}
          title="Show source"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: '17px',
            height: '17px',
            padding: '0 4px',
            margin: '0 2px',
            verticalAlign: 'text-top',
            borderRadius: '9px',
            border: 'none',
            background: active ? 'var(--accent)' : 'var(--accent-dim)',
            color: active ? 'white' : 'var(--accent-light)',
            fontFamily: 'var(--font-body)',
            fontSize: '10px',
            fontWeight: 700,
            lineHeight: 1,
            cursor: 'pointer',
          }}
        >
          {id}
        </button>
      );
    }
    return part;
  });
}

// The documents an answer was built from: one chip per source, click to read the excerpt
function Sources({ sources, openId, onToggle }) {
  const open = sources.find(s => s.id === openId);
  return (
    <div style={{
      marginTop: '12px',
      paddingTop: '10px',
      borderTop: '1px solid var(--border)',
      whiteSpace: 'normal',
    }}>
      <div style={{
        fontSize: '10px', fontWeight: 600, color: 'var(--text3)',
        letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '7px',
      }}>
        Sources
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        {sources.map(s => {
          const active = s.id === openId;
          return (
            <button
              key={s.id}
              onClick={() => onToggle(s.id)}
              title={active ? 'Hide excerpt' : 'Show excerpt'}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                maxWidth: '100%',
                padding: '4px 10px 4px 5px',
                borderRadius: '20px',
                border: `1px solid ${active ? 'var(--accent)' : 'var(--border2)'}`,
                background: active ? 'var(--accent-dim)' : 'var(--surface2)',
                color: active ? 'var(--accent-light)' : 'var(--text2)',
                fontFamily: 'var(--font-body)',
                fontSize: '11px',
                cursor: 'pointer',
                transition: 'all var(--transition)',
              }}
            >
              <span style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                minWidth: '17px', height: '17px', borderRadius: '9px', padding: '0 4px',
                background: active ? 'var(--accent)' : 'var(--accent-dim)',
                color: active ? 'white' : 'var(--accent-light)',
                fontSize: '10px', fontWeight: 700, flexShrink: 0,
              }}>
                {s.id}
              </span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {s.filename}
              </span>
              {s.page != null && (
                <span style={{ color: 'var(--text3)', flexShrink: 0 }}>p.{s.page}</span>
              )}
            </button>
          );
        })}
      </div>

      {open && (
        <div style={{
          marginTop: '8px',
          padding: '9px 12px',
          borderRadius: 'var(--radius-sm)',
          background: 'var(--surface2)',
          borderLeft: '3px solid var(--accent)',
          fontSize: '12px',
          lineHeight: 1.65,
          color: 'var(--text2)',
          fontStyle: 'italic',
        }}>
          “{open.snippet}”
        </div>
      )}
    </div>
  );
}

export default function Message({ role, text, sources = [], streaming = false }) {
  const isUser = role === 'user';
  const [openId, setOpenId] = useState(null);   // which source excerpt is expanded
  const toggle = (id) => setOpenId(prev => (prev === id ? null : id));
  const hasSources = !isUser && sources.length > 0;
  const sourceIds = new Set(sources.map(s => s.id));

  return (
    <div style={{
      display: 'flex',
      gap: '12px',
      maxWidth: '78%',
      alignSelf: isUser ? 'flex-end' : 'flex-start',
      flexDirection: isUser ? 'row-reverse' : 'row',
      animation: 'fadeUp 0.28s ease',
    }}>
      {/* Avatar */}
      <div style={{
        width: '32px',
        height: '32px',
        borderRadius: '50%',
        background: isUser
          ? 'var(--surface2)'
          : 'linear-gradient(135deg, var(--accent) 0%, #8b5cf6 100%)',
        border: isUser ? '1px solid var(--border2)' : 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: '14px',
        color: isUser ? 'var(--text2)' : 'white',
        flexShrink: 0,
        marginTop: '2px',
      }}>
        <i className={`ti ${isUser ? 'ti-user' : 'ti-brain'}`} />
      </div>

      {/* Bubble */}
      <div style={{
        padding: '13px 16px',
        borderRadius: 'var(--radius-lg)',
        borderTopLeftRadius: isUser ? 'var(--radius-lg)' : 'var(--radius-sm)',
        borderTopRightRadius: isUser ? 'var(--radius-sm)' : 'var(--radius-lg)',
        background: isUser ? 'var(--accent)' : 'var(--surface)',
        border: isUser ? 'none' : '1px solid var(--border)',
        boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
        fontSize: '14px',
        lineHeight: 1.75,
        color: isUser ? 'white' : 'var(--text)',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {isUser ? text : renderText(text, sourceIds, openId, toggle)}
        {streaming && (
          // Blinking caret while the answer is still being written
          <span style={{
            display: 'inline-block',
            width: '7px',
            height: '15px',
            marginLeft: '2px',
            verticalAlign: 'text-bottom',
            borderRadius: '1px',
            background: 'var(--accent)',
            animation: 'blink 1s steps(2, start) infinite',
          }} />
        )}
        {hasSources && <Sources sources={sources} openId={openId} onToggle={toggle} />}
      </div>
    </div>
  );
}
