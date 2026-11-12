// AuditPanel.jsx
// Admin: the audit trail (who changed what, sign-ins and refused attempts).
import React, { useCallback, useEffect, useState } from 'react';

import { API, errorMessage } from '../config';
import { apiFetch } from '../api';

const PAGE = 30;

const ACTIONS = {
  role_change:     { label: 'Role changes',     icon: 'ti-user-shield' },
  document_upload: { label: 'Uploads',          icon: 'ti-upload' },
  document_delete: { label: 'Deletes',          icon: 'ti-trash' },
  access_change:   { label: 'Access changes',   icon: 'ti-lock-cog' },
  user_register:   { label: 'New accounts',     icon: 'ti-user-plus' },
  login:           { label: 'Sign-ins',         icon: 'ti-login' },
  login_failed:    { label: 'Failed sign-ins',  icon: 'ti-lock-x' },
  access_denied:   { label: 'Denied attempts',  icon: 'ti-shield-x' },
  rate_limited:    { label: 'Rate limits hit',  icon: 'ti-clock-pause' },
  logout:          { label: 'Sign-outs',        icon: 'ti-logout' },
  token_reuse:     { label: 'Session theft',    icon: 'ti-alert-triangle' },
};

const outcomeColors = {
  success: { bg: 'var(--surface2)',   border: 'var(--border)',  icon: 'var(--accent-light)' },
  failed:  { bg: 'var(--danger-dim)', border: 'var(--danger)',  icon: 'var(--danger)' },
  denied:  { bg: 'var(--danger-dim)', border: 'var(--danger)',  icon: 'var(--danger)' },
};

// ["manager", "admin"] -> "Managers & Admins"
function audience(roles) {
  if (!Array.isArray(roles)) return 'unknown';
  if (roles.includes('employee')) return 'Everyone';
  if (roles.includes('manager')) return 'Managers & Admins';
  return 'Admins only';
}

const limits = {
  login: 'failed sign-in',
  login_ip: 'sign-in attempts',
  register: 'new account',
  chat: 'question',
  upload: 'upload',
};

const reasons = {
  wrong_password: 'wrong password',
  unknown_account: 'no such account',
};

// One plain sentence per event
function describe(e) {
  const d = e.details || {};
  const who = e.actor_email || 'Someone';
  const failed = e.outcome !== 'success';
  switch (e.action) {
    case 'role_change':
      return `${who} changed ${e.target} from ${d.from} to ${d.to}`;
    case 'document_upload':
      if (failed) {
        const pages = Array.isArray(d.pages) && d.pages.length ? ` (page ${d.pages.join(', ')})` : '';
        return `${who} could not upload ${e.target}: ${d.reason || e.outcome}${pages}`;
      }
      if (d.injection_override) {
        return `${who} uploaded ${e.target} despite a prompt-injection warning (page ${(d.flagged_pages || []).join(', ')})`;
      }
      return d.replaced
        ? `${who} replaced ${e.target} (${audience(d.allowed_roles)}, ${d.chunks} chunks)`
        : `${who} uploaded ${e.target} (${audience(d.allowed_roles)}, ${d.chunks} chunks)`;
    case 'document_delete':
      if (failed) return `${who} could not delete ${e.target}: ${d.reason || e.outcome}`;
      return `${who} deleted ${e.target}${d.allowed_roles ? ` (was ${audience(d.allowed_roles)})` : ''}`;
    case 'access_change':
      if (failed) return `${who} could not change access to ${e.target}: ${d.reason || e.outcome}`;
      return `${who} changed ${e.target} access: ${audience(d.from)} → ${audience(d.to)}`;
    case 'user_register':
      return `${e.target} registered as ${d.role}${d.first_admin ? ' (first account)' : ''}`;
    case 'login':
      return `${who} signed in`;
    case 'login_failed':
      return `Failed sign-in for ${e.target} (${reasons[d.reason] || d.reason || 'invalid credentials'})`;
    case 'access_denied':
      return `${who} was refused ${e.target}`;
    case 'rate_limited':
      return `${e.actor_email || e.target || 'Someone'} hit the ${limits[d.limit] || d.limit} limit`;
    case 'logout':
      return `${who} signed out`;
    case 'token_reuse':
      return `A retired session token for ${e.target} was used again; that sign-in was ended`;
    default:
      return `${who}: ${e.action} ${e.target || ''}`;
  }
}

export default function AuditPanel({ token }) {
  const [events, setEvents] = useState([]);
  const [nextBefore, setNextBefore] = useState(null);
  const [action, setAction] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (before) => {
    const params = new URLSearchParams({ limit: String(PAGE) });
    if (action) params.set('action', action);
    if (before) params.set('before', String(before));
    try {
      const res = await apiFetch(`${API}/admin/audit?${params}`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !Array.isArray(data.events)) {
        setError(errorMessage(data, 'Failed to load the audit trail'));
      } else {
        setEvents(prev => (before ? [...prev, ...data.events] : data.events));
        setNextBefore(data.next_before);
        setError('');
      }
    } catch {
      setError('Cannot connect to backend');
    }
    setLoading(false);
  }, [token, action]);

  // (Re)load from the top when the panel opens or the filter changes
  useEffect(() => {
    setLoading(true);
    load(null);
  }, [load]);

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
        <div style={{
          fontSize: '10px', fontWeight: 600, color: 'var(--text3)',
          letterSpacing: '1px', textTransform: 'uppercase', flex: 1,
        }}>
          Audit Trail
        </div>
        <button
          type="button"
          onClick={() => { setLoading(true); load(null); }}
          title="Refresh"
          aria-label="Refresh the audit trail"
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', fontSize: '14px' }}
        >
          <i className="ti ti-refresh" />
        </button>
      </div>

      <select
        value={action}
        onChange={e => setAction(e.target.value)}
        aria-label="Filter by event type"
        style={{
          width: '100%', marginBottom: '12px', padding: '7px 9px', fontSize: '12px',
          borderRadius: '6px', border: '1px solid var(--border2)',
          background: 'var(--surface2)', color: 'var(--text)', fontFamily: 'inherit',
        }}
      >
        <option value="">All events</option>
        {Object.entries(ACTIONS).map(([key, a]) => <option key={key} value={key}>{a.label}</option>)}
      </select>

      {error && (
        <div style={{
          fontSize: '12px', color: 'var(--danger)', background: 'var(--danger-dim)',
          padding: '8px 10px', borderRadius: '6px', marginBottom: '10px',
        }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ fontSize: '12px', color: 'var(--text3)', textAlign: 'center', padding: '20px 0' }}>
          <i className="ti ti-loader-2" style={{ animation: 'spin 0.8s linear infinite' }} /> Loading…
        </div>
      ) : events.length === 0 ? (
        <div style={{ fontSize: '12px', color: 'var(--text3)', textAlign: 'center', padding: '20px 0' }}>
          No events.
        </div>
      ) : (
        <>
          {events.map(e => {
            const c = outcomeColors[e.outcome] || outcomeColors.success;
            return (
              <div key={e.id} style={{
                background: c.bg, border: `1px solid ${c.border}`,
                borderRadius: '8px', padding: '9px 11px', marginBottom: '7px',
                display: 'flex', gap: '9px',
              }}>
                <i className={`ti ${ACTIONS[e.action]?.icon || 'ti-point'}`}
                   style={{ fontSize: '14px', color: c.icon, marginTop: '2px', flexShrink: 0 }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: '12px', color: 'var(--text)', lineHeight: 1.45, wordBreak: 'break-word' }}>
                    {describe(e)}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text3)', marginTop: '3px' }}>
                    {e.timestamp ? new Date(e.timestamp).toLocaleString() : ''}
                    {e.actor_role ? ` · ${e.actor_role}` : ''}
                    {e.outcome !== 'success' ? ` · ${e.outcome}` : ''}
                  </div>
                </div>
              </div>
            );
          })}
          {nextBefore && (
            <button
              type="button"
              onClick={() => load(nextBefore)}
              style={{
                width: '100%', padding: '8px', fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                borderRadius: '6px', border: '1px solid var(--border2)',
                background: 'var(--surface2)', color: 'var(--text2)', fontFamily: 'inherit',
              }}
            >
              Load more
            </button>
          )}
        </>
      )}
    </div>
  );
}
