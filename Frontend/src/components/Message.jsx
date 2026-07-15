{/*Message.jsx*/ }
import React from 'react';

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

export default function Message({ role, text }) {
  const isUser = role === 'user';

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
        {text}
      </div>
    </div>
  );
}
