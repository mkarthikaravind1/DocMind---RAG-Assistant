// AuthScreen.jsx
import React, { useState } from 'react';
import { API, errorMessage } from '../config';

export default function AuthScreen({ onLogin }) {
  const [mode, setMode] = useState('login'); // 'login' or 'register'
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handle = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  const switchMode = (next) => {
    setMode(next);
    setError('');
    setSuccess('');
  };

  const submit = async (e) => {
    e?.preventDefault();
    if (loading) return;

    const email = form.email.trim();
    if (!email || !form.password || (mode === 'register' && !form.name.trim())) {
      setError('Please fill in all fields.');
      return;
    }
    if (mode === 'register' && form.password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setLoading(true);
    setError('');
    setSuccess('');
    try {
      if (mode === 'register') {
        const res = await fetch(`${API}/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: form.name.trim(), email, password: form.password }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(errorMessage(data, 'Registration failed'));

        setMode('login');
        setForm(f => ({ ...f, password: '' }));
        setSuccess('Registered! Please log in.');
      } else {
        const res = await fetch(`${API}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password: form.password }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(errorMessage(data, 'Login failed'));

        // Decode role from JWT payload (middle part of token, base64url encoded)
        const b64 = data.access_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
        const payload = JSON.parse(atob(b64));
        onLogin(data.access_token, payload.role);
      }
    } catch (err) {
      setError(
        err instanceof TypeError
          ? 'Cannot reach the server. Make sure the backend is running.'
          : err.message
      );
    }
    setLoading(false);
  };

  return (
    <div style={{
      display: 'flex', height: '100vh',
      alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)',
    }}>
      {/* A real <form> so pressing Enter submits */}
      <form onSubmit={submit} style={{
        background: 'var(--surface)', padding: '40px',
        borderRadius: '12px', border: '1px solid var(--border)',
        width: '360px', display: 'flex', flexDirection: 'column', gap: '14px',
      }}>
        <h2 style={{ color: 'var(--text)', margin: 0 }}>
          {mode === 'login' ? 'Sign In' : 'Create Account'}
        </h2>

        {mode === 'register' && (
          <input name="name" placeholder="Name" value={form.name}
            onChange={handle} style={inputStyle} autoComplete="name" />
        )}
        <input name="email" type="email" placeholder="Email" value={form.email}
          onChange={handle} style={inputStyle} autoComplete="email" />
        <input name="password" type="password"
          placeholder={mode === 'register' ? 'Password (min 8 characters)' : 'Password'}
          value={form.password} onChange={handle} style={inputStyle}
          autoComplete={mode === 'register' ? 'new-password' : 'current-password'} />

        {error && (
          <span style={{ fontSize: '13px', color: 'var(--danger)' }}>{error}</span>
        )}
        {success && (
          <span style={{ fontSize: '13px', color: 'var(--success)' }}>{success}</span>
        )}

        <button type="submit" disabled={loading} style={btnStyle}>
          {loading ? 'Please wait…' : mode === 'login' ? 'Login' : 'Register'}
        </button>

        <span style={{ fontSize: '13px', color: 'var(--text3)', textAlign: 'center' }}>
          {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
          <span onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
            style={{ color: 'var(--accent)', cursor: 'pointer' }}>
            {mode === 'login' ? 'Register' : 'Login'}
          </span>
        </span>
      </form>
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
