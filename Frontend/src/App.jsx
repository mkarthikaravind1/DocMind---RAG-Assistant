// App.jsx
import React, { useState, useRef, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import Message, { TypingBubble } from './components/Message';
import WelcomeScreen from './components/WelcomeScreen';
import ChatInput from './components/ChatInput';
import AuthScreen from './components/AuthScreen';
import { API, errorMessage } from './config';

// localStorage can throw in private windows, so every access is guarded
const stored = (key) => {
  try { return localStorage.getItem(key); } catch { return null; }
};

export default function App() {
  const [docs, setDocs] = useState([]);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [backendOnline, setBackendOnline] = useState(null); // null=checking
  const messagesEndRef = useRef(null);
  // Restored from localStorage so a page refresh does not log the user out
  const [token, setToken] = useState(() => stored('token'));
  const [role, setRole] = useState(() => stored('role'));

  const handleLogout = useCallback(() => {
    try {
      localStorage.removeItem('token');
      localStorage.removeItem('role');
    } catch { /* ignore */ }
    setToken(null);
    setRole(null);
    setMessages([]);
    setDocs([]);
    setInputValue('');
    setBackendOnline(null);
  }, []);

  // Scroll to bottom on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]); 

  useEffect(() => {
    if (!token) return;
    const headers = { Authorization: `Bearer ${token}` };

    const sync = async () => {
      try {
        const [filesRes, meRes] = await Promise.all([
          fetch(`${API}/files`, { headers }),
          fetch(`${API}/auth/me`, { headers }),
        ]);

        // Token expired or user removed: go back to the login screen
        if (filesRes.status === 401 || meRes.status === 401) {
          handleLogout();
          return;
        }

        setBackendOnline(filesRes.ok);

        if (filesRes.ok) {
          const data = await filesRes.json();
          // Already filtered by the server to what this role may see
          setDocs(Array.isArray(data.documents) ? data.documents : []);
        }
        if (meRes.ok) {
          // Live role from the server, so an admin's role change shows up without re-login
          const me = await meRes.json();
          if (me.role) {
            setRole(me.role);
            try { localStorage.setItem('role', me.role); } catch { /* ignore */ }
          }
        }
      } catch {
        setBackendOnline(false);
      }
    };

    // Fetch immediately on login
    sync();

    // Then poll every 5 seconds so all tabs stay in sync
    const interval = setInterval(sync, 5000);

    return () => clearInterval(interval); // cleanup on logout
  }, [token, handleLogout]);

  const handleLogin = (token, role) => {
    try {
      localStorage.setItem('token', token);
      localStorage.setItem('role', role);
    } catch { /* ignore */ }
    setToken(token);
    setRole(role);
  };

  const handleSend = async () => {
    const question = inputValue.trim();
    if (!question || isTyping) return;

    setMessages(prev => [...prev, { role: 'user', text: question }]);
    setInputValue('');
    setIsTyping(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question }),
      });

      if (res.status === 401) {
        handleLogout();
        return;
      }

      const data = await res.json().catch(() => ({}));

      setMessages(prev => [...prev, {
        role: 'ai',
        // Guardrail blocks (400) and server errors carry their reason in `detail`
        text: res.ok
          ? (data.answer || 'No answer was returned.')
          : `⚠️ ${errorMessage(data, 'Something went wrong. Please try again.')}`,
      }]);

    } catch {
      setMessages(prev => [...prev, {
        role: 'ai',
        text: '⚠️ Could not reach the backend. Make sure FastAPI is running:\n\nuvicorn app:app --reload',
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleSuggestion = (text) => {
    setInputValue(text);
  };

  // doc = { filename, allowed_roles, indexed }
  const handleDocChange = (doc, action) => {
    if (action === 'delete') {
      setDocs(prev => prev.filter(d => d.filename !== doc.filename));
    } else {
      // Add, or replace in place (re-upload / access change): never list a file twice
      setDocs(prev => (
        prev.some(d => d.filename === doc.filename)
          ? prev.map(d => (d.filename === doc.filename ? { ...d, ...doc } : d))
          : [...prev, doc]
      ));
    }
  };

  const hasMessages = messages.length > 0;
  // Files without an access record are listed for admins but are not searchable
  const indexedCount = docs.filter(d => d.indexed !== false).length;
  const hasDocs = indexedCount > 0;

  // Backend status indicator config
  const statusConfig = {
    null:  { color: 'var(--text3)', icon: 'ti-circle-dashed', label: 'Checking…' },
    true:  { color: 'var(--success)', icon: 'ti-circle-check', label: 'Backend online' },
    false: { color: 'var(--danger)',  icon: 'ti-circle-x',     label: 'Backend offline' },
  };

  const sc = statusConfig[backendOnline];

  if (!token) return <AuthScreen onLogin={handleLogin} />;
  
  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Sidebar */}
      <Sidebar
        docs={docs}
        onUploadSuccess={(doc) => handleDocChange(doc, 'add')}
        onAccessChange={(doc) => handleDocChange(doc, 'update')}
        onDeleteSuccess={(filename) => handleDocChange({ filename }, 'delete')}
        token={token}
        role={role}
      />

      {/* Main panel */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
        background: 'var(--bg)',
      }}>
      
        {/* Top bar */}
        <div style={{
          padding: '15px 28px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: hasDocs ? 'var(--success)' : 'var(--text3)',
              animation: hasDocs ? 'pulse-dot 2s ease infinite' : 'none',
              flexShrink: 0,
            }} />
            <span style={{ fontSize: '14px', fontWeight: 500, color: 'var(--text)' }}>
              {hasDocs
                ? `${indexedCount} document${indexedCount > 1 ? 's' : ''} available to you`
                : 'No documents available'}
            </span>
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '12px',
            color: sc.color,
          }}>
            <i className={`ti ${sc.icon}`} style={{ fontSize: '14px' }} />
            {sc.label}
          </div>

          {/* Role badge */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '12px',
            padding: '4px 10px',
            borderRadius: '20px',
            background: role === 'admin'
              ? 'var(--danger-dim)'
              : role === 'manager'
              ? 'var(--accent-dim)'
              : 'var(--surface3)',
            color: role === 'admin'
              ? 'var(--danger)'
              : role === 'manager'
              ? 'var(--accent-light)'
              : 'var(--text3)',
            fontWeight: 600,
            textTransform: 'capitalize',
          }}>
            <i className="ti ti-shield-check" />
            {role}
          </div>

          <button
            onClick={handleLogout}
            title="Log out"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '12px',
              padding: '5px 10px',
              borderRadius: '20px',
              background: 'transparent',
              border: '1px solid var(--border2)',
              color: 'var(--text2)',
              cursor: 'pointer',
              fontFamily: 'var(--font-body)',
            }}
          >
            <i className="ti ti-logout" />
            Logout
          </button>
        </div>

        {/* Messages area */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: hasMessages ? '28px' : '0',
          display: 'flex',
          flexDirection: 'column',
          gap: '20px',
        }}>
          {!hasMessages ? (
            <WelcomeScreen onSuggestion={handleSuggestion} hasDoc={hasDocs} />
          ) : (
            <>
              {messages.map((msg, i) => (
                <Message key={i} role={msg.role} text={msg.text} />
              ))}
              {isTyping && <TypingBubble />}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input */}
        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          disabled={isTyping || !hasDocs}
        />
      </div>
    </div>
  );
  
}
