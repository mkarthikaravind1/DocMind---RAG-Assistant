{/*ChatInput.jsx*/ }
import React, { useRef, useEffect } from 'react';

export default function ChatInput({ value, onChange, onSend, disabled }) {
  const textareaRef = useRef(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 130) + 'px';
  }, [value]);

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) onSend();
    }
  };

  const canSend = !disabled && value.trim().length > 0;

  return (
    <div style={{
      padding: '16px 28px 20px',
      borderTop: '1px solid var(--border)',
      background: 'var(--surface)',
      flexShrink: 0,
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: '10px',
        background: 'var(--surface2)',
        border: `1px solid var(--border2)`,
        borderRadius: 'var(--radius-lg)',
        padding: '10px 12px 10px 16px',
        transition: 'border-color var(--transition), box-shadow var(--transition)',
      }}
        onFocus={() => {}}
        ref={el => {
          if (el) {
            el.addEventListener('focusin', () => {
              el.style.borderColor = 'var(--accent)';
              el.style.boxShadow = '0 0 0 3px var(--accent-glow)';
            });
            el.addEventListener('focusout', () => {
              el.style.borderColor = 'var(--border2)';
              el.style.boxShadow = 'none';
            });
          }
        }}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask a question about your documents…"
          rows={1}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: 'var(--text)',
            fontFamily: 'var(--font-body)',
            fontSize: '14px',
            resize: 'none',
            lineHeight: 1.65,
            maxHeight: '130px',
            minHeight: '24px',
            padding: '2px 0',
          }}
        />
        <button
          onClick={onSend}
          disabled={!canSend}
          title="Send (Enter)"
          style={{
            width: '36px',
            height: '36px',
            borderRadius: 'var(--radius-md)',
            background: canSend ? 'var(--accent)' : 'var(--surface3)',
            border: 'none',
            color: canSend ? 'white' : 'var(--text3)',
            cursor: canSend ? 'pointer' : 'not-allowed',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '16px',
            flexShrink: 0,
            transition: 'all var(--transition)',
          }}
        >
          <i className="ti ti-arrow-up" />
        </button>
      </div>

      <div style={{
        fontSize: '11px',
        color: 'var(--text3)',
        textAlign: 'right',
        marginTop: '7px',
        paddingRight: '2px',
      }}>
        Enter to send &nbsp;·&nbsp; Shift+Enter for new line
      </div>
    </div>
  );
}
