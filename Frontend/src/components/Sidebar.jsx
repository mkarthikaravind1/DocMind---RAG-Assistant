{/*Sidebar.jsx*/ }
import React, { useRef, useState } from 'react';
import UserPanel from './UserPanel';
import LogsPanel from './LogsPanel';

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

export default function Sidebar({ docs, onUploadSuccess,onDeleteSuccess, token , role}) {
  const fileRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [status, setStatus] = useState(null); // { type: 'loading'|'success'|'error', msg }
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activeTab, setActiveTab] = useState('docs'); 

  const handleFile = (f) => {
    if (!f) return;
    if (f.type !== 'application/pdf') {
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

    try {
      const res = await fetch('http://localhost:8000/upload', { method: 'POST', headers: {Authorization: `Bearer ${token}` }, body: form });
      const data = await res.json();
      if (res.ok) {
        setStatus({ type: 'success', msg: `"${data.filename}" ready` });
        onUploadSuccess(data.filename);
        setSelectedFile(null);
        if (fileRef.current) fileRef.current.value = '';
      } else {
        setStatus({ type: 'error', msg: data.error || 'Upload failed' });
      }
    } catch {
      setStatus({ type: 'error', msg: 'Cannot connect to backend' });
    }
    setUploading(false);
  };

  const handleDelete = async (filename) => {
  try {
    const res = await fetch(`http://localhost:8000/delete/${filename}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) { onDeleteSuccess(filename); setStatus(null); }
    else setStatus({ type: 'error', msg: 'Delete failed' });
  } catch {
    setStatus({ type: 'error', msg: 'Delete failed' });
  }
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

      {/* In Sidebar.jsx — update the tab bar section (admin only)*/}
      {role === 'admin' && (
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          {['docs', 'users', 'logs'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                flex: 1, padding: '10px', background: 'none', border: 'none',
                borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                color: activeTab === tab ? 'var(--accent)' : 'var(--text3)',
                fontSize: '11px', fontWeight: 600, cursor: 'pointer',
                textTransform: 'capitalize', transition: 'all 0.15s',
              }}
            >
              <i className={`ti ${tab === 'docs' ? 'ti-files' : tab === 'users' ? 'ti-users' : 'ti-chart-bar'}`}
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
            No documents yet.<br />Upload a PDF to begin.
          </div>
        ) : (
          docs.map((name, i) => (
            <div key={i} style={styles.docItem}>
              <i className="ti ti-file-type-pdf" style={{ color: 'var(--danger)', fontSize: '16px', flexShrink: 0 }} />
              <span style={styles.docName}>{name}</span>
              <span style={styles.docBadge}>Ready</span>
              {/* Show delete button on each doc item (Admin only)*/}
              {role === 'admin' && (
                <button
                  onClick={() => handleDelete(name)}
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
          ))
        )}
        </div>
      </>) : activeTab === 'users'? (
          <UserPanel token={token} />
      ):(
          <LogsPanel token={token} />
        )}
    </div>
  );
}