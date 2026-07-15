{/*App.jsx*/ }
import React, { useState, useRef, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Message, { TypingBubble } from './components/Message';
import WelcomeScreen from './components/WelcomeScreen';
import ChatInput from './components/ChatInput';
import AuthScreen from './components/AuthScreen';

const API = 'http://localhost:8000';

export default function App() {
  const [docs, setDocs] = useState([]);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [backendOnline, setBackendOnline] = useState(null); // null=checking
  const messagesEndRef = useRef(null);
  const [token, setToken] = useState(null);
  const [role, setRole] = useState(null);

  // Scroll to bottom on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]); 

  // Check backend status on mount
  // useEffect(() => {
  //   if (!token) return;
  //   fetch(`${API}/docs`, {
  //     headers: {Authorization: `Bearer ${token}`},
  //   })
  //     .then(() => setBackendOnline(true))
  //     .catch(() => setBackendOnline(false));
  // }, [token]);

  // // Fetch existing docs from backend after login
  // useEffect(() => {
  //   if (!token) return;
  //   fetch(`${API}/docs`, {
  //     headers: { Authorization: `Bearer ${token}` },
  //   })
  //     .then(res => res.json())
  //     .then(data => setDocs(data.docs || []))
  //     .catch(() => {});
  // }, [token]);
    // Replace your two useEffects (backend check + doc fetch) with this single one:

  useEffect(() => {
    if (!token) return;

    const fetchDocs = () => {
      fetch(`${API}/files`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(res => {
          setBackendOnline(res.ok);
          return res.json();
        })
        .then(data => setDocs(data.docs || []))
        .catch(() => setBackendOnline(false));
    };

    // Fetch immediately on login
    fetchDocs();

    // Then poll every 5 seconds so all tabs stay in sync
    const interval = setInterval(fetchDocs, 5000);

    return () => clearInterval(interval); // cleanup on logout
  }, [token]);

  // const handleUploadSuccess = (filename) => {
  //   setDocs(prev => [...prev, filename]);
  // };

  const handleLogin = (token, role) => {
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

      const data = await res.json();

      setMessages(prev => [...prev, {
        role: 'ai',
        text: data.answer || 'No answer was returned.',
      }]);

    } catch {
      setMessages(prev => [...prev, {
        role: 'ai',
        text: '⚠️ Could not reach the backend. Make sure FastAPI is running:\n\nuvicorn app:app --reload',
      }]);
    }
    setIsTyping(false);
  };

  const handleSuggestion = (text) => {
    setInputValue(text);
  };

  const handleDocChange = (filename, action) => {
    if (action === 'delete') {
      setDocs(prev => prev.filter(d => d !== filename));
    } else {
      setDocs(prev => [...prev, filename]);
    }
  };

  const hasMessages = messages.length > 0;
  const hasDocs = docs.length > 0;

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
        onUploadSuccess={(name) => handleDocChange(name, 'add')}
        onDeleteSuccess={(name) => handleDocChange(name, 'delete')}
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
                ? `${docs.length} document${docs.length > 1 ? 's' : ''} indexed`
                : 'No documents indexed'}
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
