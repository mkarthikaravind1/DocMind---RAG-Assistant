// App.jsx
import React, { useState, useRef, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import Message, { TypingBubble } from './components/Message';
import WelcomeScreen from './components/WelcomeScreen';
import ChatInput from './components/ChatInput';
import AuthScreen from './components/AuthScreen';
import { API, errorMessage } from './config';
import { apiFetch, refreshSession, setAccessToken, signOut } from './api';

// Parses one Server-Sent Events frame ("event: x\ndata: {...}") into { event, data }
function parseSSE(frame) {
  let event = 'message';
  const dataLines = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) };
  } catch {
    return null;
  }
}

// localStorage can throw in private windows, so every access is guarded
const stored = (key) => {
  try { return localStorage.getItem(key); } catch { return null; }
};

export default function App() {
  const [docs, setDocs] = useState([]);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);            // a request is in flight
  const [awaitingFirstToken, setAwaitingFirstToken] = useState(false); // ...and nothing has arrived yet
  const abortRef = useRef(null);                              // cancels an in-flight answer
  const [backendOnline, setBackendOnline] = useState(null); // null=checking
  const messagesEndRef = useRef(null);
  // The access token is kept in memory only (see api.js). After a page reload
  // the session is restored from the httpOnly refresh cookie instead.
  const [token, setToken] = useState(null);
  const [restoring, setRestoring] = useState(true);
  const [role, setRole] = useState(() => stored('role'));
  // Conversation memory: the chat being continued (null = a new chat) and the saved list
  const [conversationId, setConversationId] = useState(() => {
    const id = Number(stored('conversationId'));
    return Number.isInteger(id) && id > 0 ? id : null;
  });
  const [conversations, setConversations] = useState([]);

  const rememberConversation = (id) => {
    setConversationId(id);
    try {
      if (id) localStorage.setItem('conversationId', String(id));
      else localStorage.removeItem('conversationId');
    } catch { /* ignore */ }
  };

  const handleLogout = useCallback(() => {
    abortRef.current?.abort();   // stop any answer still streaming
    signOut();                   // revokes the refresh token on the server
    try {
      localStorage.removeItem('token');
      localStorage.removeItem('role');
      localStorage.removeItem('conversationId');
    } catch { /* ignore */ }
    setToken(null);
    setRole(null);
    setConversationId(null);
    setConversations([]);
    setMessages([]);
    setDocs([]);
    setInputValue('');
    setBackendOnline(null);
  }, []);

  // On page load: exchange the refresh cookie for a new access token
  useEffect(() => {
    let cancelled = false;
    try { localStorage.removeItem('token'); } catch { /* ignore */ }   // from versions that stored it
    refreshSession().then(session => {
      if (cancelled) return;
      if (session) {
        setToken(session.access_token);
        setRole(session.role);
      }
      setRestoring(false);
    });
    return () => { cancelled = true; };
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
          apiFetch(`${API}/files`, { headers }),
          apiFetch(`${API}/auth/me`, { headers }),
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

  // ── Saved conversations ─────────────────────────────────────────
  const fetchConversations = useCallback(async () => {
    if (!token) return;
    try {
      const res = await apiFetch(`${API}/conversations`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data)) setConversations(data);
    } catch { /* the status indicator already shows when the backend is down */ }
  }, [token]);

  const loadConversation = useCallback(async (id) => {
    if (!token || !id) return;
    abortRef.current?.abort();   // stop an answer that is still streaming into another chat
    try {
      const res = await apiFetch(`${API}/conversations/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 401) { handleLogout(); return; }
      if (!res.ok) {
        // Deleted, or belongs to another account: fall back to a new chat
        setConversationId(null);
        try { localStorage.removeItem('conversationId'); } catch { /* ignore */ }
        setMessages([]);
        return;
      }
      const data = await res.json();
      setMessages((data.messages || []).map(m => ({
        role: m.role === 'user' ? 'user' : 'ai',
        text: m.text,
        sources: Array.isArray(m.sources) ? m.sources : [],
        id: m.id,
        feedback: m.feedback || null,
      })));
      setConversationId(id);
      try { localStorage.setItem('conversationId', String(id)); } catch { /* ignore */ }
    } catch { /* keep the current view */ }
  }, [token, handleLogout]);

  // Thumbs up / down on an answer. Shown at once, and put back if saving fails.
  const handleFeedback = async (messageId, rating, reason) => {
    const apply = (feedback) => setMessages(prev => prev.map(m => (m.id === messageId ? { ...m, feedback } : m)));
    const previous = messages.find(m => m.id === messageId)?.feedback || null;
    apply({ rating, reason });
    try {
      const res = await apiFetch(`${API}/messages/${messageId}/feedback`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ rating, reason }),
      });
      if (res.status === 401) { handleLogout(); return; }
      if (!res.ok) apply(previous);
    } catch {
      apply(previous);
    }
  };

  const handleNewChat = () => {
    abortRef.current?.abort();
    setMessages([]);
    setInputValue('');
    rememberConversation(null);
  };

  const handleDeleteConversation = async (id, title) => {
    if (!window.confirm(`Delete the chat "${title || 'Untitled chat'}"? This cannot be undone.`)) return;
    try {
      const res = await apiFetch(`${API}/conversations/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok || res.status === 404) {
        setConversations(prev => prev.filter(c => c.id !== id));
        if (id === conversationId) handleNewChat();
      }
    } catch { /* leave the list as it is */ }
  };

  // After login (or a page refresh): load the chat list and reopen the last chat
  useEffect(() => {
    if (!token) return;
    fetchConversations();
    const lastId = Number(stored('conversationId'));
    if (Number.isInteger(lastId) && lastId > 0) loadConversation(lastId);
  }, [token, fetchConversations, loadConversation]);

  const handleLogin = (token, role) => {
    setAccessToken(token);
    try { localStorage.setItem('role', role); } catch { /* ignore */ }
    setToken(token);
    setRole(role);
  };

  const handleSend = async () => {
    const question = inputValue.trim();
    if (!question || isTyping) return;

    setMessages(prev => [...prev, { role: 'user', text: question }]);
    setInputValue('');
    setIsTyping(true);
    setAwaitingFirstToken(true);

    const controller = new AbortController();
    abortRef.current = controller;

    // The answer bubble is created when the first piece arrives, then updated in place
    let started = false;
    let text = '';
    const showAnswer = (patch) => {
      setAwaitingFirstToken(false);
      if (!started) {
        started = true;
        setMessages(prev => [...prev, { role: 'ai', text: '', sources: [], ...patch }]);
      } else {
        setMessages(prev => {
          if (prev.length === 0) return prev;   // chat was cleared (logout) mid-stream
          const next = prev.slice();
          next[next.length - 1] = { ...next[next.length - 1], ...patch };
          return next;
        });
      }
    };

    try {
      const res = await apiFetch(`${API}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        // conversation_id lets the server use earlier turns to understand follow-ups
        body: JSON.stringify(conversationId ? { question, conversation_id: conversationId } : { question }),
        signal: controller.signal,
      });

      if (res.status === 401) {
        handleLogout();
        return;
      }

      // Guardrail blocks (400) and other errors arrive as normal JSON, not as a stream
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        showAnswer({ text: `⚠️ ${errorMessage(data, 'Something went wrong. Please try again.')}` });
        return;
      }

      // Read the Server-Sent Events stream: frames are separated by a blank line
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finished = false;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const frame = parseSSE(buffer.slice(0, sep));
          buffer = buffer.slice(sep + 2);
          if (!frame) continue;

          if (frame.event === 'token') {
            text += frame.data.text || '';
            showAnswer({ text, streaming: true });
          } else if (frame.event === 'done') {
            finished = true;
            // The final answer replaces the streamed text and brings the cited sources
            showAnswer({
              text: frame.data.answer || text || 'No answer was returned.',
              sources: Array.isArray(frame.data.sources) ? frame.data.sources : [],
              streaming: false,
              id: frame.data.message_id || null,   // lets this answer be rated
              feedback: null,
            });
            // The exchange is now saved: keep continuing this conversation
            if (frame.data.conversation_id) {
              rememberConversation(frame.data.conversation_id);
              fetchConversations();
            }
          } else if (frame.event === 'error') {
            finished = true;
            showAnswer({
              text: `${text ? text + '\n\n' : ''}⚠️ ${errorMessage(frame.data, 'Something went wrong. Please try again.')}`,
              streaming: false,
            });
          }
        }
      }

      if (!finished) {
        showAnswer({
          text: `${text ? text + '\n\n' : ''}⚠️ The connection was interrupted before the answer finished.`,
          streaming: false,
        });
      }

    } catch (err) {
      if (controller.signal.aborted) return;   // user logged out mid-answer
      showAnswer({
        text: `${text ? text + '\n\n' : ''}⚠️ Could not reach the backend. Make sure FastAPI is running:\n\nuvicorn app:app --reload`,
        streaming: false,
      });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setIsTyping(false);
      setAwaitingFirstToken(false);
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

  if (restoring) {
    return (
      <div style={{
        height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg)', color: 'var(--text3)', fontSize: '13px',
      }}>
        <i className="ti ti-loader-2" style={{ animation: 'spin 0.8s linear infinite', marginRight: '8px' }} />
        Restoring your session…
      </div>
    );
  }
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
        conversations={conversations}
        activeConversationId={conversationId}
        onSelectConversation={loadConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
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
            onClick={handleNewChat}
            title="Start a new chat"
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
              whiteSpace: 'nowrap',
            }}
          >
            <i className="ti ti-plus" />
            New chat
          </button>

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
                <Message
                  key={i} role={msg.role} text={msg.text} sources={msg.sources} streaming={msg.streaming}
                  messageId={msg.role === 'ai' ? msg.id : null} feedback={msg.feedback} onFeedback={handleFeedback}
                />
              ))}
              {isTyping && awaitingFirstToken && <TypingBubble />}
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
