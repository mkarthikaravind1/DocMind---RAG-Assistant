// ChatsPanel.jsx
// The signed-in user's saved conversations: start a new one, reopen or delete an old one.
import React from 'react';

function whenLabel(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

export default function ChatsPanel({ conversations, activeId, onSelect, onNew, onDelete }) {
  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
      <button
        onClick={onNew}
        style={{
          width: '100%',
          padding: '9px 14px',
          marginBottom: '16px',
          background: 'var(--accent)',
          color: 'white',
          border: 'none',
          borderRadius: 'var(--radius-md)',
          fontFamily: 'var(--font-body)',
          fontSize: '13px',
          fontWeight: 500,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '7px',
        }}
      >
        <i className="ti ti-plus" /> New chat
      </button>

      <div style={{
        fontSize: '10px', fontWeight: 600, color: 'var(--text3)',
        letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '11px',
      }}>
        Your Chats
      </div>

      {conversations.length === 0 ? (
        <div style={{
          textAlign: 'center', color: 'var(--text3)', fontSize: '12px',
          padding: '24px 0', lineHeight: 1.9,
        }}>
          <i className="ti ti-messages" style={{ fontSize: '30px', display: 'block', marginBottom: '8px', opacity: 0.25 }} />
          No saved chats yet.<br />Ask a question to start one.
        </div>
      ) : (
        conversations.map(c => {
          const active = c.id === activeId;
          return (
            <div
              key={c.id}
              onClick={() => onSelect(c.id)}
              title={c.title}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '9px',
                padding: '9px 11px',
                marginBottom: '6px',
                borderRadius: 'var(--radius-md)',
                background: active ? 'var(--accent-dim)' : 'var(--surface2)',
                border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                cursor: 'pointer',
                transition: 'all var(--transition)',
              }}
            >
              <i className="ti ti-message" style={{
                fontSize: '15px', flexShrink: 0,
                color: active ? 'var(--accent-light)' : 'var(--text3)',
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: '12px',
                  fontWeight: active ? 600 : 400,
                  color: 'var(--text)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {c.title || 'Untitled chat'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text3)', marginTop: '1px' }}>
                  {whenLabel(c.updated_at)}
                </div>
              </div>
              <button
                onClick={e => { e.stopPropagation(); onDelete(c.id, c.title); }}
                title="Delete chat"
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--danger)', padding: '2px 4px', flexShrink: 0,
                }}
              >
                <i className="ti ti-trash" style={{ fontSize: '14px' }} />
              </button>
            </div>
          );
        })
      )}
    </div>
  );
}
