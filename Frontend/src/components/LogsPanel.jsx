// LogsPanel.jsx
import React, { useEffect, useState } from 'react';

const API = 'http://localhost:8000';

const roleColors = {
  admin:    { bg: 'var(--danger-dim)',  color: 'var(--danger)' },
  manager:  { bg: 'var(--accent-dim)', color: 'var(--accent-light)' },
  employee: { bg: 'var(--surface3)',   color: 'var(--text3)' },
};

export default function LogsPanel({ token }) {
  const [logs,  setLogs]  = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchAll = async () => {
    try {
      const [logsRes, statsRes] = await Promise.all([
        fetch(`${API}/admin/logs`,       { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API}/admin/logs/stats`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      const logsData  = await logsRes.json();
      const statsData = await statsRes.json();
      setLogs(logsData);
      setStats(statsData);
    } catch {
      // silent
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchAll();
    // Refresh every 10 seconds
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, []);

  const statCards = stats ? [
    { label: 'Total Queries',       value: stats.total_queries,        icon: 'ti-message-dots' },
    { label: 'Avg Response Time',   value: `${stats.avg_response_time}s`, icon: 'ti-clock' },
    { label: 'Guardrail Violations',value: stats.guardrail_violations,  icon: 'ti-shield-x' },
    { label: 'Avg Chunks Used',     value: stats.avg_chunks,           icon: 'ti-packages' },
  ] : [];

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>

      {/* Header */}
      <div style={{
        fontSize: '10px', fontWeight: 600, color: 'var(--text3)',
        letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '14px',
      }}>
        Monitoring Dashboard
      </div>

      {/* Stat cards */}
      {stats && (
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr',
          gap: '8px', marginBottom: '16px',
        }}>
          {statCards.map((s, i) => (
            <div key={i} style={{
              background: 'var(--surface2)', border: '1px solid var(--border)',
              borderRadius: '8px', padding: '10px 12px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <i className={`ti ${s.icon}`} style={{ fontSize: '13px', color: 'var(--accent-light)' }} />
                <span style={{ fontSize: '10px', color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  {s.label}
                </span>
              </div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text)' }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Log entries */}
      <div style={{
        fontSize: '10px', fontWeight: 600, color: 'var(--text3)',
        letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '10px',
      }}>
        Recent Queries
      </div>

      {loading ? (
        <div style={{ fontSize: '12px', color: 'var(--text3)', textAlign: 'center', padding: '20px 0' }}>
          <i className="ti ti-loader-2" style={{ animation: 'spin 0.8s linear infinite' }} /> Loading…
        </div>
      ) : logs.length === 0 ? (
        <div style={{ fontSize: '12px', color: 'var(--text3)', textAlign: 'center', padding: '20px 0' }}>
          No queries yet.
        </div>
      ) : (
        logs.map(log => (
          <div key={log.id} style={{
            background: log.guardrail_hit ? 'var(--danger-dim)' : 'var(--surface2)',
            border: `1px solid ${log.guardrail_hit ? 'var(--danger)' : 'var(--border)'}`,
            borderRadius: '8px', padding: '10px 12px', marginBottom: '8px',
          }}>
            {/* Top row — email + role + time */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text)' }}>
                {log.user_email}
              </span>
              <span style={{
                fontSize: '10px', padding: '1px 7px', borderRadius: '20px', fontWeight: 600,
                background: roleColors[log.user_role]?.bg || 'var(--surface3)',
                color:      roleColors[log.user_role]?.color || 'var(--text3)',
              }}>
                {log.user_role}
              </span>
              {log.guardrail_hit && (
                <span style={{
                  fontSize: '10px', padding: '1px 7px', borderRadius: '20px',
                  background: 'var(--danger-dim)', color: 'var(--danger)', fontWeight: 600,
                }}>
                  <i className="ti ti-shield-x" style={{ marginRight: '3px' }} />
                  BLOCKED
                </span>
              )}
              <span style={{ fontSize: '10px', color: 'var(--text3)', marginLeft: 'auto' }}>
                {new Date(log.timestamp).toLocaleString()}
              </span>
            </div>

            {/* Question */}
            <div style={{
              fontSize: '12px', color: 'var(--text2)',
              marginBottom: '6px', fontStyle: 'italic',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              "{log.question}"
            </div>

            {/* Bottom row — stats */}
            {!log.guardrail_hit && (
              <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
                {[
                  { icon: 'ti-clock',    val: `${log.response_time}s` },
                  { icon: 'ti-packages', val: `${log.chunks_retrieved} chunks` },
                  { icon: 'ti-text-size',val: `${log.answer_length} chars` },
                ].map((m, i) => (
                  <span key={i} style={{ fontSize: '11px', color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <i className={`ti ${m.icon}`} style={{ fontSize: '12px' }} />
                    {m.val}
                  </span>
                ))}
              </div>
            )}

            {/* Guardrail reason */}
            {log.guardrail_hit && (
              <div style={{ fontSize: '11px', color: 'var(--danger)', marginTop: '4px' }}>
                {log.guardrail_hit}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}