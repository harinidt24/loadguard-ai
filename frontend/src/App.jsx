import { useState } from 'react'

function App() {
  const [selectedFile, setSelectedFile] = useState(null)
  const [status, setStatus] = useState('')
  const [events, setEvents] = useState([])

  async function handleUpload() {
    if (!selectedFile) return
    setStatus('Processing... this may take a minute')

    const formData = new FormData()
    formData.append('file', selectedFile)

    try {
      const res = await fetch('http://127.0.0.1:8000/videos/upload', {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      setStatus(`Found ${data.events_found} risk event(s)`)

      const eventsRes = await fetch('http://127.0.0.1:8000/events')
      setEvents(await eventsRes.json())
    } catch (err) {
      setStatus('Upload/processing failed - check backend terminal for errors')
    }
  }

  const riskColor = { low: '#4ADE80', medium: '#F5D023', high: '#F5821F', critical: '#EF4444' }

  return (
    <div style={{ padding: '2rem', fontFamily: 'sans-serif', background: '#111', color: '#eee', minHeight: '100vh' }}>
      <h1>LoadGuard AI</h1>

      <input type="file" accept="video/*" onChange={(e) => setSelectedFile(e.target.files[0])} />
      <button onClick={handleUpload} disabled={!selectedFile} style={{ marginLeft: '1rem' }}>
        Upload and analyze
      </button>
      <p>{status}</p>

      <h2>Incidents</h2>
      {events.length === 0 && <p>No events yet.</p>}
      {events.map((e) => (
        <div key={e.id} style={{ border: '1px solid #444', borderRadius: 8, padding: 12, marginBottom: 10, display: 'flex', gap: 12 }}>
          {e.evidence_path && (
            <img src={`http://127.0.0.1:8000${e.evidence_path}`} alt="evidence" width={140} />
          )}
          <div>
            <p style={{ color: riskColor[e.risk_level], fontWeight: 'bold', textTransform: 'uppercase' }}>
              {e.risk_level} - {e.behaviour_type} (t={e.timestamp_seconds.toFixed(1)}s, score {e.risk_score})
            </p>
            <p>{e.explanation}</p>
            <p><em>Recommended: {e.recommended_action}</em></p>
          </div>
        </div>
      ))}
    </div>
  )
}

export default App