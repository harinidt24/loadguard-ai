import { useState, useEffect } from 'react'

function App() {
  const [message, setMessage] = useState('Loading...')

  useEffect(() => {
    fetch('http://127.0.0.1:8000/')
      .then((response) => response.json())
      .then((data) => setMessage(data.message))
      .catch(() => setMessage('Could not reach backend'))
  }, [])

  return (
    <div style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
      <h1>LoadGuard AI</h1>
      <p>Backend says: {message}</p>
    </div>
  )
}

export default App