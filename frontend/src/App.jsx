import { useState, useRef } from 'react'

const RISK_COLOR = { low: '#4ADE80', medium: '#F5D023', high: '#F5821F', critical: '#EF4444' }

function scoreColor(score) {
  if (score >= 85) return '#4ADE80'
  if (score >= 65) return '#F5D023'
  if (score >= 40) return '#F5821F'
  return '#EF4444'
}

function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function App() {
  const [selectedFile, setSelectedFile] = useState(null)
  const [status, setStatus] = useState('')
  const [processing, setProcessing] = useState(false)
  const [events, setEvents] = useState([])
  const [summary, setSummary] = useState(null)
  const [videos, setVideos] = useState([])
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [videoFilename, setVideoFilename] = useState(null)
  const videoRef = useRef(null)

  async function refreshVideos() {
    try {
      const res = await fetch('http://127.0.0.1:8000/videos')
      setVideos(await res.json())
    } catch {
      // non-fatal, scorecard just won't update
    }
  }

  async function handleUpload() {
    if (!selectedFile) return
    setProcessing(true)
    setStatus('Processing video — detecting objects, tracking, analyzing behaviour...')

    const formData = new FormData()
    formData.append('file', selectedFile)

    try {
      const res = await fetch('http://127.0.0.1:8000/videos/upload', { method: 'POST', body: formData })
      const data = await res.json()
      setVideoFilename(selectedFile.name)
      setStatus(`Analysis complete — ${data.events_found} risk event(s) identified · Safety score ${data.safety_score}`)

      const [eventsRes, summaryRes] = await Promise.all([
        fetch('http://127.0.0.1:8000/events'),
        fetch('http://127.0.0.1:8000/dashboard/summary'),
      ])
      setEvents(await eventsRes.json())
      setSummary(await summaryRes.json())
      await refreshVideos()
    } catch (err) {
      setStatus('Processing failed — check backend terminal')
    } finally {
      setProcessing(false)
    }
  }

  async function askAssistant(q) {
    if (!q.trim()) return
    setMessages((m) => [...m, { role: 'user', text: q }])
    setQuestion('')
    try {
      const res = await fetch('http://127.0.0.1:8000/assistant/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })
      const data = await res.json()
      setMessages((m) => [...m, { role: 'assistant', text: data.answer }])
    } catch {
      setMessages((m) => [...m, { role: 'assistant', text: 'Could not reach the assistant.' }])
    }
  }
  function jumpToIncident(timestampSeconds) {
    if (videoRef.current) {
      videoRef.current.currentTime = timestampSeconds
      videoRef.current.play()
    }
  }

  const suggested = [
    'Why was the top event high risk?',
    'What was the most common behaviour?',
    'Show me high risk events',
    'What corrective action should I take?',
  ]

  const latestScore = videos.length > 0 ? videos[0].safety_score : null

  return (
    <div style={{ minHeight: '100vh', background: '#0F1114', color: '#E4E6EA', fontFamily: 'Segoe UI, sans-serif' }}>
      <header style={{ padding: '20px 32px', borderBottom: '1px solid #272B33', display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#F5A623' }} />
        <h1 style={{ fontSize: 18, margin: 0 }}>LoadGuard AI</h1>
        <span style={{ color: '#8B909B', fontSize: 13 }}>Warehouse Field Intelligence</span>
      </header>

      <main style={{ padding: 32, display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 24 }}>
        <div>
          <section style={{ background: '#1D2026', border: '1px solid #272B33', borderRadius: 8, padding: 20, marginBottom: 20 }}>
            <h2 style={{ fontSize: 14, marginTop: 0 }}>Upload footage</h2>
            <input type="file" accept="video/*" onChange={(e) => setSelectedFile(e.target.files[0])} style={{ color: '#C7CBD1' }} />
            <button
              onClick={handleUpload}
              disabled={!selectedFile || processing}
              style={{
                marginLeft: 12, background: processing ? '#3A3F49' : '#F5A623', color: '#0F1114',
                border: 'none', borderRadius: 6, padding: '8px 16px', fontWeight: 600, cursor: processing ? 'default' : 'pointer',
              }}
            >
              {processing ? 'Analyzing...' : 'Upload and analyze'}
            </button>
            {status && <p style={{ color: '#8B909B', fontSize: 13, marginTop: 10 }}>{status}</p>}
          </section>

          {summary && summary.total_events > 0 && (
            <section style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
              {Object.entries(summary.by_risk_level).map(([level, count]) => (
                <div key={level} style={{ flex: 1, background: '#1D2026', border: '1px solid #272B33', borderRadius: 8, padding: 16, textAlign: 'center' }}>
                  <div style={{ fontSize: 24, fontWeight: 700, color: RISK_COLOR[level] }}>{count}</div>
                  <div style={{ fontSize: 11, textTransform: 'uppercase', color: '#8B909B' }}>{level}</div>
                </div>
              ))}
            </section>
          )}
          {videoFilename && (
            <section style={{ marginBottom: 20 }}>
              <video
                ref={videoRef}
                controls
                width="100%"
                style={{ borderRadius: 8, border: '1px solid #272B33' }}
                src={`http://127.0.0.1:8000/uploads/${videoFilename}`}
              />
            </section>
          )}

          {events.length > 0 && (
            <section style={{ background: '#1D2026', border: '1px solid #272B33', borderRadius: 8, padding: '16px 20px', marginBottom: 20 }}>
              <h2 style={{ fontSize: 14, marginTop: 0, marginBottom: 12 }}>Timeline</h2>
              <div style={{ position: 'relative', height: 40, background: '#0F1114', borderRadius: 4 }}>
                {events.map((e) => {
                  const maxTime = Math.max(...events.map((ev) => ev.timestamp_seconds), 1)
                  const leftPercent = (e.timestamp_seconds / maxTime) * 96 + 2
                  return (
                    <div key={e.id} title={`${e.behaviour_type} at ${e.timestamp_seconds.toFixed(1)}s`}
                    onClick={() => jumpToIncident(e.timestamp_seconds)}
                      style={{
                        position: 'absolute', left: `${leftPercent}%`, top: 8, width: 10, height: 24,
                        borderRadius: 3, background: RISK_COLOR[e.risk_level], cursor: 'pointer',
                      }} />
                  )
                })}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#8B909B', marginTop: 6 }}>
                <span>0:00</span>
                <span>Video timeline →</span>
              </div>
            </section>
          )}

          <section>
            <h2 style={{ fontSize: 14 }}>Incident timeline</h2>
            {events.length === 0 && <p style={{ color: '#8B909B', fontSize: 13 }}>No events yet — upload a video to begin.</p>}
            {events.map((e) => (
              <div key={e.id} style={{ background: '#1D2026', border: '1px solid #272B33', borderRadius: 8, padding: 14, marginBottom: 10, display: 'flex', gap: 14 }}>
                {e.evidence_path && (
                  <img src={`http://127.0.0.1:8000${e.evidence_path}`} alt="" width={120} height={75}
                       style={{ objectFit: 'cover', borderRadius: 6, border: '1px solid #272B33' }} />
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: RISK_COLOR[e.risk_level] }} />
                    <span style={{ fontSize: 12, fontWeight: 700, color: RISK_COLOR[e.risk_level], textTransform: 'uppercase' }}>{e.risk_level}</span>
                    <span style={{ color: '#8B909B', fontSize: 12 }}>· {e.timestamp_seconds.toFixed(1)}s · {e.behaviour_type} · score {e.risk_score}</span>
                  </div>
                  <p style={{ fontSize: 13, margin: '4px 0' }}>{e.explanation}</p>
                  <p style={{ fontSize: 12, color: '#8B909B', margin: 0 }}>Recommended: {e.recommended_action}</p>
                </div>
              </div>
            ))}
          </section>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <section style={{ background: '#1D2026', border: '1px solid #272B33', borderRadius: 8, padding: 16 }}>
            <h2 style={{ fontSize: 14, marginTop: 0, marginBottom: 12 }}>Safety scorecard</h2>
            {latestScore === null ? (
              <p style={{ color: '#8B909B', fontSize: 13 }}>Upload a video to generate a score.</p>
            ) : (
              <>
                <div style={{ textAlign: 'center', marginBottom: 14 }}>
                  <div style={{ fontSize: 36, fontWeight: 700, color: scoreColor(latestScore) }}>{latestScore}</div>
                  <div style={{ fontSize: 11, textTransform: 'uppercase', color: '#8B909B' }}>Current session score</div>
                </div>
                <div style={{ fontSize: 11, color: '#8B909B', marginBottom: 6, textTransform: 'uppercase' }}>History</div>
                <div style={{ maxHeight: 220, overflowY: 'auto' }}>
                  {videos.map((v) => (
                    <div key={v.id} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '6px 0', borderBottom: '1px solid #272B33', fontSize: 12,
                    }}>
                      <div style={{ overflow: 'hidden' }}>
                        <div style={{ color: '#E4E6EA', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden', maxWidth: 130 }}>
                          {v.filename}
                        </div>
                      </div>
                      <span style={{ fontWeight: 700, color: scoreColor(v.safety_score) }}>{v.safety_score}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>

          <section style={{ background: '#1D2026', border: '1px solid #272B33', borderRadius: 8, padding: 16, height: 'fit-content' }}>
            <h2 style={{ fontSize: 14, marginTop: 0 }}>Supervisor assistant</h2>
            <div style={{ minHeight: 100, maxHeight: 320, overflowY: 'auto', marginBottom: 12 }}>
              {messages.length === 0 && suggested.map((q) => (
                <button key={q} onClick={() => askAssistant(q)}
                  style={{ display: 'block', width: '100%', textAlign: 'left', background: 'transparent', color: '#8B909B',
                           border: '1px solid #272B33', borderRadius: 6, padding: '8px 10px', marginBottom: 6, fontSize: 12, cursor: 'pointer' }}>
                  {q}
                </button>
              ))}
              {messages.map((m, i) => (
                <div key={i} style={{ marginBottom: 8, textAlign: m.role === 'user' ? 'right' : 'left' }}>
                  <span style={{
                    display: 'inline-block', background: m.role === 'user' ? '#F5A623' : '#272B33',
                    color: m.role === 'user' ? '#0F1114' : '#E4E6EA', padding: '6px 10px', borderRadius: 6,
                    fontSize: 12, maxWidth: '90%', whiteSpace: 'pre-wrap',
                  }}>{m.text}</span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && askAssistant(question)}
                placeholder="Ask about incidents..."
                style={{ flex: 1, background: '#0F1114', border: '1px solid #272B33', borderRadius: 6, padding: '6px 8px', color: '#E4E6EA', fontSize: 12 }}
              />
              <button onClick={() => askAssistant(question)}
                style={{ background: '#F5A623', border: 'none', borderRadius: 6, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
                Ask
              </button>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

export default App