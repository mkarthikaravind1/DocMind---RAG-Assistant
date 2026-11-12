// LogsPanel.jsx
import React, { useEffect, useState } from 'react';

import { API, errorMessage } from '../config';
import { apiFetch } from '../api';

const roleColors = {
  admin:    { bg: 'var(--danger-dim)',  color: 'var(--danger)' },
  manager:  { bg: 'var(--accent-dim)', color: 'var(--accent-light)' },
  employee: { bg: 'var(--surface3)',   color: 'var(--text3)' },
};

// Preset thumbs-down reasons (keys come from the backend's feedback.py)
const reasonLabels = {
  wrong_answer: 'Wrong answer',
  missing_info: 'Missing information',
  wrong_source: 'Wrong source',
  not_relevant: 'Not relevant',
};

// Answer quality scores are 0..1; shown as a percentage
const pct = v => (v === null || v === undefined ? '–' : `${Math.round(v * 100)}%`);

const sectionTitle = {
  fontSize: '10px', fontWeight: 600, color: 'var(--text3)',
  letterSpacing: '1px', textTransform: 'uppercase',
};

function StatCard({ icon, label, value, hint, alert }) {
  return (
    <div title={hint} style={{
      background: 'var(--surface2)', border: '1px solid var(--border)',
      borderRadius: '8px', padding: '10px 12px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
        <i className={`ti ${icon}`} style={{ fontSize: '13px', color: 'var(--accent-light)' }} />
        <span style={{ fontSize: '10px', color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: '20px', fontWeight: 700, color: alert ? 'var(--danger)' : 'var(--text)' }}>
        {value}
      </div>
    </div>
  );
}

function ScoreChip({ label, value, threshold }) {
  const low = value < threshold;
  return (
    <span style={{
      fontSize: '10px', padding: '1px 7px', borderRadius: '20px', fontWeight: 600,
      background: low ? 'var(--danger-dim)' : 'var(--success-dim)',
      color:      low ? 'var(--danger)'     : 'var(--success)',
    }}>
      {label} {pct(value)}
    </span>
  );
}

export default function LogsPanel({ token }) {
  const [logs,  setLogs]  = useState([]);
  const [stats, setStats] = useState(null);
  const [quality, setQuality] = useState(null);
  const [votes, setVotes] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const fetchAll = async () => {
      try {
        const [logsRes, statsRes, qualityRes, votesRes] = await Promise.all([
          apiFetch(`${API}/admin/logs`,           { headers: { Authorization: `Bearer ${token}` } }),
          apiFetch(`${API}/admin/logs/stats`,     { headers: { Authorization: `Bearer ${token}` } }),
          apiFetch(`${API}/admin/evals/stats`,    { headers: { Authorization: `Bearer ${token}` } }),
          apiFetch(`${API}/admin/feedback/stats`, { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        const logsData    = await logsRes.json().catch(() => ({}));
        const statsData   = await statsRes.json().catch(() => ({}));
        const qualityData = await qualityRes.json().catch(() => null);
        const votesData   = await votesRes.json().catch(() => null);
        if (cancelled) return;

        // Quality scores and feedback are extras: if they fail to load, the rest still shows
        setQuality(qualityRes.ok && qualityData ? qualityData : null);
        setVotes(votesRes.ok && votesData ? votesData : null);

        // On 401/403 the body is { detail }, not a list: never pass that to .map()
        if (!logsRes.ok || !statsRes.ok || !Array.isArray(logsData)) {
          setError(errorMessage(logsRes.ok ? statsData : logsData, 'Failed to load logs'));
        } else {
          setLogs(logsData);
          setStats(statsData);
          setError('');
        }
      } catch {
        if (!cancelled) setError('Cannot connect to backend');
      }
      if (!cancelled) setLoading(false);
    };

    fetchAll();
    // Refresh every 10 seconds
    const interval = setInterval(fetchAll, 10000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [token]);

  const statCards = stats ? [
    { label: 'Total Queries',       value: stats.total_queries,        icon: 'ti-message-dots' },
    { label: 'Avg Response Time',   value: `${stats.avg_response_time}s`, icon: 'ti-clock' },
    { label: 'Guardrail Violations',value: stats.guardrail_violations,  icon: 'ti-shield-x' },
    { label: 'Avg Chunks Used',     value: stats.avg_chunks,           icon: 'ti-packages' },
  ] : [];

  const threshold = quality?.low_score_threshold ?? 0.7;
  // Relevancy is an embedding similarity and runs lower, so it has its own line
  const relevancyThreshold = quality?.low_relevancy_threshold ?? 0.6;
  const isLow = (v, limit = threshold) => v !== null && v !== undefined && v < limit;
  const qualityCards = quality ? [
    { label: 'Faithfulness',     value: pct(quality.avg_faithfulness),     icon: 'ti-shield-check',
      alert: isLow(quality.avg_faithfulness),
      hint: 'How much of each answer is supported by the retrieved excerpts (average)' },
    { label: 'Answer Relevancy', value: pct(quality.avg_answer_relevancy), icon: 'ti-target-arrow',
      alert: isLow(quality.avg_answer_relevancy, relevancyThreshold),
      hint: 'How directly each answer addresses the question that was asked (average)' },
    { label: 'Low Faithfulness', value: quality.low_faithfulness,          icon: 'ti-alert-triangle',
      alert: quality.low_faithfulness > 0,
      hint: `Answers scoring below ${pct(threshold)} faithfulness` },
    { label: 'Not Answered',     value: pct(quality.not_answered_rate),    icon: 'ti-help-circle',
      hint: 'Share of evaluated questions the documents could not answer' },
  ] : [];

  const voteCards = votes ? [
    { label: 'Satisfaction', value: pct(votes.satisfaction), icon: 'ti-mood-smile',
      alert: votes.satisfaction !== null && votes.satisfaction < 0.5,
      hint: 'Thumbs up as a share of all rated answers' },
    { label: 'Answers Rated', value: pct(votes.rated_share), icon: 'ti-checkbox',
      hint: `${votes.rated} of ${votes.answers} answers were rated` },
    { label: 'Thumbs Up',   value: votes.up,   icon: 'ti-thumb-up' },
    { label: 'Thumbs Down', value: votes.down, icon: 'ti-thumb-down', alert: votes.down > votes.up },
  ] : [];
  const givenReasons = votes
    ? Object.entries(votes.reasons || {}).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1])
    : [];

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>

      {/* Header */}
      <div style={{ ...sectionTitle, marginBottom: '14px' }}>
        Monitoring Dashboard
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

      {/* Stat cards */}
      {stats && (
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr',
          gap: '8px', marginBottom: '16px',
        }}>
          {statCards.map((s, i) => <StatCard key={i} {...s} />)}
        </div>
      )}

      {/* Answer quality: faithfulness and answer relevancy */}
      {quality && (
        <>
          <div style={{ ...sectionTitle, marginBottom: '10px' }}>
            Answer Quality
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr',
            gap: '8px', marginBottom: '6px',
          }}>
            {qualityCards.map((s, i) => <StatCard key={i} {...s} />)}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text3)', marginBottom: '16px' }}>
            {quality.evaluated === 0
              ? (quality.sample_rate > 0 ? 'No answers scored yet.' : 'Evaluation is switched off.')
              : `${quality.evaluated} answers scored by ${quality.judge_model}`}
            {quality.failed > 0 && ` · ${quality.failed} could not be scored`}
          </div>
        </>
      )}

      {/* User feedback: thumbs up / down on answers */}
      {votes && (
        <>
          <div style={{ ...sectionTitle, marginBottom: '10px' }}>
            User Feedback
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr',
            gap: '8px', marginBottom: '6px',
          }}>
            {voteCards.map((s, i) => <StatCard key={i} {...s} />)}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text3)', marginBottom: '16px' }}>
            {votes.rated === 0
              ? 'No answers rated yet.'
              : givenReasons.length === 0
                ? 'No reasons given for thumbs down.'
                : `Thumbs down reasons: ${givenReasons.map(([key, count]) => `${reasonLabels[key] || key} ${count}`).join(' · ')}`}
          </div>
        </>
      )}

      {/* Log entries */}
      <div style={{ ...sectionTitle, marginBottom: '10px' }}>
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
                {log.timestamp ? new Date(log.timestamp).toLocaleString() : ''}
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

            {/* Bottom row — stats and quality scores */}
            {!log.guardrail_hit && (
              <div style={{ display: 'flex', gap: '14px', rowGap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
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
                {log.faithfulness !== null && log.faithfulness !== undefined && (
                  <ScoreChip label="Faithful" value={log.faithfulness} threshold={threshold} />
                )}
                {log.answer_relevancy !== null && log.answer_relevancy !== undefined && (
                  <ScoreChip label="Relevant" value={log.answer_relevancy} threshold={relevancyThreshold} />
                )}
                {log.feedback?.rating && (
                  <span
                    title={log.feedback.reason ? reasonLabels[log.feedback.reason] || log.feedback.reason : undefined}
                    style={{
                      fontSize: '10px', padding: '1px 7px', borderRadius: '20px', fontWeight: 600,
                      background: log.feedback.rating === 'up' ? 'var(--success-dim)' : 'var(--danger-dim)',
                      color:      log.feedback.rating === 'up' ? 'var(--success)'     : 'var(--danger)',
                    }}
                  >
                    <i className={`ti ti-thumb-${log.feedback.rating}`} style={{ marginRight: '3px' }} />
                    {log.feedback.rating === 'up'
                      ? 'Liked'
                      : (log.feedback.reason ? reasonLabels[log.feedback.reason] || 'Disliked' : 'Disliked')}
                  </span>
                )}
                {log.eval_status === 'not_answered' && (
                  <span style={{
                    fontSize: '10px', padding: '1px 7px', borderRadius: '20px', fontWeight: 600,
                    background: 'var(--surface3)', color: 'var(--text3)',
                  }}>
                    Not answered
                  </span>
                )}
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
