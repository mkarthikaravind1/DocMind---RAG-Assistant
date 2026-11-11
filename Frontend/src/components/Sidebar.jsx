// Sidebar.jsx
import React, { useRef, useState } from 'react';
import UserPanel from './UserPanel';
import LogsPanel from './LogsPanel';
import ChatsPanel from './ChatsPanel';
import { API, errorMessage } from '../config';

const styles = {
  sidebar: {
    width: 'var(--sidebar-w)',
    minWidth: 'var(--sidebar-w)',
    background: 'var(--surface)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    height: '100%',
  },
  header: {
    padding: '22px 20px 18px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: '11px',
  },
  logoIcon: {
    width: '36px',
    height: '36px',
    borderRadius: '10px',
    background: 'linear-gradient(135deg, var(--accent) 0%, #8b5cf6 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '17px',
    color: 'white',
    flexShrink: 0,
  },
  logoText: {
    fontFamily: 'var(--font-head)',
    fontSize: '20px',
    color: 'var(--text)',
    letterSpacing: '-0.3px',
    lineHeight: 1.1,
  },
  logoSub: {
    fontFamily: 'var(--font-body)',
    fontSize: '10px',
    fontWeight: 400,
    color: 'var(--text3)',
    letterSpacing: '1px',
    textTransform: 'uppercase',
    marginTop: '2px',
  },

  uploadSection: {
    padding: '18px 20px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  sectionLabel: {
    fontSize: '10px',
    fontWeight: 600,
    color: 'var(--text3)',
    letterSpacing: '1px',
    textTransform: 'uppercase',
    marginBottom: '11px',
  },

  docsSection: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px 20px',
  },
  emptyDocs: {
    textAlign: 'center',
    color: 'var(--text3)',
    fontSize: '12px',
    padding: '24px 0',
    lineHeight: 1.9,
  },
  docItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '9px',
    padding: '9px 11px',
    borderRadius: 'var(--radius-md)',
    background: 'var(--surface2)',
    marginBottom: '6px',
    border: '1px solid var(--border)',
    transition: 'border-color var(--transition)',
    cursor: 'default',
  },
  docName: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    fontSize: '12px',
    color: 'var(--text)',
  },
  docBadge: {
    fontSize: '10px',
    padding: '2px 8px',
    background: 'var(--success-dim)',
    color: 'var(--success)',
    borderRadius: '20px',
    flexShrink: 0,
    fontWeight: 500,
  },
};

// Who may read a document. Admins are always included.
const AUDIENCES = [
  { key: 'everyone', label: 'Everyone',          short: 'Everyone', icon: 'ti-users',  roles: ['employee', 'manager', 'admin'] },
  { key: 'managers', label: 'Managers & Admins', short: 'Managers', icon: 'ti-lock',   roles: ['manager', 'admin'] },
  { key: 'admins',   label: 'Admins only',       short: 'Admins',   icon: 'ti-shield-lock', roles: ['admin'] },
];

const audienceOf = (allowedRoles = []) => (
  allowedRoles.includes('employee') ? AUDIENCES[0]
    : allowedRoles.includes('manager') ? AUDIENCES[1]
    : AUDIENCES[2]
);

const audienceColors = {
  everyone: { bg: 'var(--success-dim)', color: 'var(--success)' },
  managers: { bg: 'var(--accent-dim)',  color: 'var(--accent-light)' },
  admins:   { bg: 'var(--danger-dim)',  color: 'var(--danger)' },
};

const TAB_ICONS = { docs: 'ti-files', chats: 'ti-messages', users: 'ti-users', logs: 'ti-chart-bar' };

export default function Sidebar({
  docs, onUploadSuccess, onDeleteSuccess, onAccessChange, token, role,
  conversations = [], activeConversationId, onSelectConversation, onNewChat, onDeleteConversation,
}) {
  const fileRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [status, setStatus] = useState(null); // { type: 'loading'|'success'|'error', msg }
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [audience, setAudience] = useState('everyone');   // who can read the next upload
  const [savingAccess, setSavingAccess] = useState(null); // filename being updated
  // A manager cannot publish a document their own role would be locked out of
  const audienceOptions = AUDIENCES.filter(a => role === 'admin' || a.roles.includes(role));
  const [selectedTab, setActiveTab] = useState('docs');
  // Everyone gets Docs and Chats; Users and Logs are admin-only
  const tabs = role === 'admin' ? ['docs', 'chats', 'users', 'logs'] : ['docs', 'chats'];
  // If an admin is demoted while on the Users/Logs tab, fall back to Docs
  const activeTab = tabs.includes(selectedTab) ? selectedTab : 'docs';

  const handleFile = (f) => {
    if (!f) return;
    // Some browsers/OSes report an empty type for PDFs, so also accept the extension
    if (f.type !== 'application/pdf' && !f.name.toLowerCase().endsWith('.pdf')) {
      setStatus({ type: 'error', msg: 'Only PDF files are supported' });
      return;
    }
    setSelectedFile(f);
    setStatus({ type: 'info', msg: f.name });
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    setStatus({ type: 'loading', msg: 'Uploading & indexing…' });

    const form = new FormData();
    form.append('file', selectedFile);
    const chosen = audienceOptions.find(a => a.key === audience) || AUDIENCES[0];
    form.append('allowed_roles', chosen.roles.join(','));

    try {
      const res = await fetch(`${API}/upload`, { method: 'POST', headers: {Authorization: `Bearer ${token}` }, body: form });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setStatus({ type: 'success', msg: `"${data.filename}" ready` });
        onUploadSuccess({ filename: data.filename, allowed_roles: data.allowed_roles, indexed: true });
        setSelectedFile(null);
        if (fileRef.current) fileRef.current.value = '';
      } else {
        setStatus({ type: 'error', msg: errorMessage(data, 'Upload failed') });
      }
    } catch {
      setStatus({ type: 'error', msg: 'Cannot connect to backend' });
    }
    setUploading(false);
  };

  const handleDelete = async (filename) => {
    if (!window.confirm(`Delete "${filename}"? Its content will no longer be used in answers.`)) return;
    try {
      // encodeURIComponent keeps names containing # ? % or spaces intact
      const res = await fetch(`${API}/delete/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) { onDeleteSuccess(filename); setStatus(null); }
      else {
        const data = await res.json().catch(() => ({}));
        setStatus({ type: 'error', msg: errorMessage(data, 'Delete failed') });
      }
    } catch {
      setStatus({ type: 'error', msg: 'Cannot connect to backend' });
    }
  };

  const handleAccessChange = async (filename, audienceKey) => {
    const chosen = AUDIENCES.find(a => a.key === audienceKey);
    if (!chosen) return;
    setSavingAccess(filename);
    try {
      const res = await fetch(`${API}/documents/${encodeURIComponent(filename)}/access`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ allowed_roles: chosen.roles }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        onAccessChange({ filename, allowed_roles: data.allowed_roles });
        setStatus({ type: 'success', msg: `"${filename}" is now: ${chosen.label}` });
      } else {
        setStatus({ type: 'error', msg: errorMessage(data, 'Could not change access') });
      }
    } catch {
      setStatus({ type: 'error', msg: 'Cannot connect to backend' });
    }
    setSavingAccess(null);
  };

  const statusColors = {
    loading: { bg: 'var(--accent-dim)', color: 'var(--accent-light)' },
    success: { bg: 'var(--success-dim)', color: 'var(--success)' },
    error:   { bg: 'var(--danger-dim)', color: 'var(--danger)' },
    info:    { bg: 'var(--surface3)', color: 'var(--text2)' },
  };

  const statusIcons = {
    loading: 'ti-loader-2',
    success: 'ti-circle-check',
    error:   'ti-alert-circle',
    info:    'ti-file-text',
  };

  return (
    <div style={styles.sidebar}>
      {/* Logo */}
      <div style={styles.header}>
        <div style={styles.logo}>
          <div style={styles.logoIcon}>
            <i className="ti ti-brain" />
          </div>
          <div>
            <div style={styles.logoText}>DocMind</div>
            <div style={styles.logoSub}>RAG Assistant</div>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      {(
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          {tabs.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                flex: 1, padding: '10px 4px', background: 'none', border: 'none', whiteSpace: 'nowrap',
                borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                color: activeTab === tab ? 'var(--accent)' : 'var(--text3)',
                fontSize: '11px', fontWeight: 600, cursor: 'pointer',
                textTransform: 'capitalize', transition: 'all 0.15s',
              }}
            >
              <i className={`ti ${TAB_ICONS[tab]}`}
                style={{ marginRight: '4px' }} />
              {tab}
            </button>
          ))}
        </div>
      )}
      {/* Upload */}

      {activeTab === 'docs' ? (<>
      {role !== 'employee' && (
      <div style={styles.uploadSection}>
        <div style={styles.sectionLabel}>Upload Document</div>

        {/* Drop zone */}
        <div
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => {
            e.preventDefault();
            setDragOver(false);
            handleFile(e.dataTransfer.files[0]);
          }}
          onClick={() => fileRef.current?.click()}
          style={{
            border: `1.5px dashed ${dragOver ? 'var(--accent)' : 'var(--border2)'}`,
            borderRadius: 'var(--radius-md)',
            padding: '22px 16px',
            textAlign: 'center',
            cursor: 'pointer',
            background: dragOver ? 'var(--accent-glow)' : 'transparent',
            transition: 'all var(--transition)',
            marginBottom: '10px',
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf"
            style={{ display: 'none' }}
            onChange={e => handleFile(e.target.files[0])}
          />
          <i className="ti ti-cloud-upload" style={{
            fontSize: '28px',
            color: dragOver ? 'var(--accent)' : 'var(--text3)',
            display: 'block',
            marginBottom: '8px',
            transition: 'color var(--transition)',
          }} />
          <div style={{ fontSize: '13px', color: dragOver ? 'var(--accent)' : 'var(--text2)', fontWeight: 500 }}>
            Drop PDF here
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text3)', marginTop: '3px' }}>
            or click to browse
          </div>
        </div>

        {/* Audience picker: who can read this document */}
        <div style={{ ...styles.sectionLabel, marginBottom: '7px' }}>Who can access it</div>
        <div style={{ display: 'flex', gap: '5px', marginBottom: '10px', flexWrap: 'wrap' }}>
          {audienceOptions.map(a => {
            const active = audience === a.key;
            return (
              <button
                key={a.key}
                onClick={() => setAudience(a.key)}
                title={a.label}
                style={{
                  flex: 1,
                  padding: '6px 6px',
                  borderRadius: 'var(--radius-sm)',
                  border: `1px solid ${active ? audienceColors[a.key].color : 'var(--border2)'}`,
                  background: active ? audienceColors[a.key].bg : 'transparent',
                  color: active ? audienceColors[a.key].color : 'var(--text3)',
                  fontFamily: 'var(--font-body)',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  transition: 'all var(--transition)',
                }}
              >
                <i className={`ti ${a.icon}`} style={{ marginRight: '4px' }} />
                {a.short}
              </button>
            );
          })}
        </div>

        {/* Status */}
        {status && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '7px',
            padding: '8px 11px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            marginBottom: '10px',
            background: statusColors[status.type]?.bg,
            color: statusColors[status.type]?.color,
            overflow: 'hidden',
          }}>
            <i className={`ti ${statusIcons[status.type]}`} style={{
              flexShrink: 0,
              animation: status.type === 'loading' ? 'spin 0.8s linear infinite' : 'none',
            }} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {status.msg}
            </span>
          </div>
        )}

        {/* Upload button */}
        <button
          onClick={handleUpload}
          disabled={!selectedFile || uploading}
          style={{
            width: '100%',
            padding: '9px 14px',
            background: selectedFile && !uploading ? 'var(--accent)' : 'var(--surface3)',
            color: selectedFile && !uploading ? 'white' : 'var(--text3)',
            border: 'none',
            borderRadius: 'var(--radius-md)',
            fontFamily: 'var(--font-body)',
            fontSize: '13px',
            fontWeight: 500,
            cursor: selectedFile && !uploading ? 'pointer' : 'not-allowed',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '7px',
            transition: 'all var(--transition)',
          }}
        >
          {uploading
            ? <><i className="ti ti-loader-2" style={{ animation: 'spin 0.8s linear infinite' }} /> Uploading…</>
            : <><i className="ti ti-upload" /> Upload PDF</>
          }
        </button>
        </div>
      )}

      {/* Document list */}
      <div style={styles.docsSection}>
        <div style={styles.sectionLabel}>Indexed Documents</div>
        {docs.length === 0 ? (
          <div style={styles.emptyDocs}>
            <i className="ti ti-files" style={{ fontSize: '30px', display: 'block', marginBottom: '8px', opacity: 0.25 }} />
            {role === 'employee'
              ? <>No documents are available<br />to your role yet.</>
              : <>No documents yet.<br />Upload a PDF to begin.</>}
          </div>
        ) : (
          docs.map((doc) => {
            const name = doc.filename;
            const aud = audienceOf(doc.allowed_roles);
            const unindexed = doc.indexed === false;
            return (
            <div key={name} style={styles.docItem}>
              <i className="ti ti-file-type-pdf" style={{ color: 'var(--danger)', fontSize: '16px', flexShrink: 0 }} />
              <span style={styles.docName} title={name}>{name}</span>
              {unindexed ? (
                // On disk but never given an access record: not searchable
                <span
                  style={{ ...styles.docBadge, background: 'var(--danger-dim)', color: 'var(--danger)' }}
                  title="This file was uploaded before access control existed. Upload it again to make it searchable."
                >
                  Re-upload
                </span>
              ) : role === 'admin' ? (
                // Admins can change the audience without re-uploading
                <select
                  value={aud.key}
                  disabled={savingAccess === name}
                  onChange={e => handleAccessChange(name, e.target.value)}
                  title="Who can access this document"
                  style={{
                    fontSize: '10px',
                    fontWeight: 600,
                    fontFamily: 'var(--font-body)',
                    padding: '2px 4px',
                    borderRadius: '20px',
                    border: 'none',
                    outline: 'none',
                    cursor: 'pointer',
                    flexShrink: 0,
                    maxWidth: '82px',
                    background: audienceColors[aud.key].bg,
                    color: audienceColors[aud.key].color,
                  }}
                >
                  {AUDIENCES.map(a => <option key={a.key} value={a.key}>{a.short}</option>)}
                </select>
              ) : role === 'manager' ? (
                <span
                  style={{ ...styles.docBadge, background: audienceColors[aud.key].bg, color: audienceColors[aud.key].color }}
                  title={`Access: ${aud.label}`}
                >
                  <i className={`ti ${aud.icon}`} style={{ marginRight: '3px' }} />
                  {aud.short}
                </span>
              ) : (
                <span style={styles.docBadge}>Ready</span>
              )}
              {/* Show delete button on each doc item (Admin only)*/}
              {role === 'admin' && (
                <button
                  onClick={() => handleDelete(name)}
                  title="Delete document"
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--danger)',
                    padding: '2px 4px',
                  }}
                >
                  <i className="ti ti-trash" style={{ fontSize: '14px' }} />
                </button>
              )}
            </div>
            );
          })
        )}
        </div>
      </>) : activeTab === 'chats' ? (
          <ChatsPanel
            conversations={conversations}
            activeId={activeConversationId}
            onSelect={onSelectConversation}
            onNew={onNewChat}
            onDelete={onDeleteConversation}
          />
      ) : activeTab === 'users'? (
          <UserPanel token={token} />
      ):(
          <LogsPanel token={token} />
        )}
    </div>
  );
}