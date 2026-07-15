{/*AuthScreen.jsx*/ }
import React, { useState } from 'react';

const API = 'http://localhost:8000';

export default function AuthScreen({ onLogin }) {
  const [mode, setMode] = useState('login'); // 'login' or 'register'
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handle = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  const submit = async () => {
    setLoading(true);
    setError('');
    try {
      if (mode === 'register') {
        await fetch(`${API}/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        });
        setMode('login');
        setError('Registered! Please log in.');
      } else {
        const res = await fetch(`${API}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: form.email, password: form.password }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Login failed');

        // Decode role from JWT payload (middle part of token)
        const payload = JSON.parse(atob(data.access_token.split('.')[1]));
        onLogin(data.access_token, payload.role);
      }
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  return (
    <div style={{
      display: 'flex', height: '100vh',
      alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)',
    }}>
      <div style={{
        background: 'var(--surface)', padding: '40px',
        borderRadius: '12px', border: '1px solid var(--border)',
        width: '360px', display: 'flex', flexDirection: 'column', gap: '14px',
      }}>
        <h2 style={{ color: 'var(--text)', margin: 0 }}>
          {mode === 'login' ? 'Sign In' : 'Create Account'}
        </h2>

        {mode === 'register' && (
          <input name="name" placeholder="Name" value={form.name}
            onChange={handle} style={inputStyle} />
        )}
        <input name="email" placeholder="Email" value={form.email}
          onChange={handle} style={inputStyle} />
        <input name="password" type="password" placeholder="Password"
          value={form.password} onChange={handle} style={inputStyle} />

        {error && (
          <span style={{ fontSize: '13px', color: 'var(--danger)' }}>{error}</span>
        )}

        <button onClick={submit} disabled={loading} style={btnStyle}>
          {loading ? 'Please wait…' : mode === 'login' ? 'Login' : 'Register'}
        </button>

        <span style={{ fontSize: '13px', color: 'var(--text3)', textAlign: 'center' }}>
          {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
          <span onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
            style={{ color: 'var(--accent)', cursor: 'pointer' }}>
            {mode === 'login' ? 'Register' : 'Login'}
          </span>
        </span>
      </div>
    </div>
  );
}

const inputStyle = {
  padding: '10px 14px', borderRadius: '8px',
  border: '1px solid var(--border)', background: 'var(--bg)',
  color: 'var(--text)', fontSize: '14px', outline: 'none',
};
const btnStyle = {
  padding: '10px', borderRadius: '8px',
  background: 'var(--accent)', color: '#fff',
  border: 'none', cursor: 'pointer', fontWeight: 600,
};