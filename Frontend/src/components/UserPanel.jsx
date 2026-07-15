{/* UserPanel.jsx*/ }
import React, { useEffect, useState } from 'react';

const API = 'http://localhost:8000';
const ROLES = ['employee', 'manager', 'admin'];

const roleColors = {
  admin:    { bg: 'var(--danger-dim)',  color: 'var(--danger)' },
  manager:  { bg: 'var(--accent-dim)', color: 'var(--accent-light)' },
  employee: { bg: 'var(--surface3)',   color: 'var(--text3)' },
};

export default function UserPanel({ token }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(null); // user id being updated
  const [error, setError] = useState('');

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/admin/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setUsers(data);
    } catch {
      setError('Failed to load users');
    }
    setLoading(false);
  };

  useEffect(() => { fetchUsers(); }, []);

  const handleRoleChange = async (userId, newRole) => {
    setUpdating(userId);
    setError('');
    try {
      const res = await fetch(`${API}/admin/users/${userId}/role`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ role: newRole }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Update failed');
      } else {
        // Update local state instantly without refetch
        setUsers(prev =>
          prev.map(u => u.id === userId ? { ...u, role: newRole } : u)
        );
      }
    } catch {
      setError('Failed to update role');
    }
    setUpdating(null);
  };

  return (
    <div style={{ padding: '16px 20px' }}>
      <div style={{
        fontSize: '10px', fontWeight: 600, color: 'var(--text3)',
        letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '12px',
      }}>
        Manage Users
      </div>

      {error && (
        <div style={{
          fontSize: '12px', color: 'var(--danger)',
          background: 'var(--danger-dim)', padding: '8px 10px',
          borderRadius: '6px', marginBottom: '10px',
        }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ fontSize: '12px', color: 'var(--text3)', textAlign: 'center', padding: '16px 0' }}>
          <i className="ti ti-loader-2" style={{ animation: 'spin 0.8s linear infinite' }} /> Loading…
        </div>
      ) : (
        users.map(user => (
          <div key={user.id} style={{
            padding: '10px 12px',
            borderRadius: '8px',
            background: 'var(--surface2)',
            border: '1px solid var(--border)',
            marginBottom: '8px',
          }}>
            {/* Name & email */}
            <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text)', marginBottom: '2px' }}>
              {user.name}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text3)', marginBottom: '8px' }}>
              {user.email}
            </div>

            {/* Role selector */}
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {ROLES.map(r => (
                <button
                  key={r}
                  onClick={() => handleRoleChange(user.id, r)}
                  disabled={user.role === r || updating === user.id}
                  style={{
                    padding: '3px 10px',
                    borderRadius: '20px',
                    fontSize: '11px',
                    fontWeight: 600,
                    border: 'none',
                    cursor: user.role === r ? 'default' : 'pointer',
                    textTransform: 'capitalize',
                    transition: 'all 0.15s',
                    background: user.role === r
                      ? roleColors[r].bg
                      : 'var(--surface3)',
                    color: user.role === r
                      ? roleColors[r].color
                      : 'var(--text3)',
                    opacity: updating === user.id && user.role !== r ? 0.5 : 1,
                  }}
                >
                  {updating === user.id && user.role !== r
                    ? <i className="ti ti-loader-2" style={{ animation: 'spin 0.8s linear infinite' }} />
                    : r}
                </button>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}