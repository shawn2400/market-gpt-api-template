import React, { useState, useRef, useEffect } from 'react'

export default function AIChat({ api }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim()) return

    // Add user message
    setMessages([...messages, { role: 'user', content: input }])
    setInput('')

    try {
      // Call AI endpoint (placeholder)
      const res = await api.post('/ai/chat', {
        query: input,
        context: messages,
      })

      // Add AI response
      setMessages((prev) => [...prev, { role: 'assistant', content: res.data.message }])
    } catch (err) {
      console.error('Failed to get AI response:', err)
    }
  }

  return (
    <div className="flex flex-col h-full p-6">
      <h2 className="text-2xl font-bold mb-6">🤖 AI Assistant</h2>

      <div className="flex-1 bg-slate-800 rounded border border-slate-700 p-4 mb-4 overflow-y-auto">
        {messages.map((msg, idx) => (
          <div key={idx} className={`mb-4 ${msg.role === 'user' ? 'text-right' : 'text-left'}`}>
            <div
              className={`inline-block p-3 rounded ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-slate-100'
              } max-w-xs`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Ask AI..."
          className="flex-1 px-4 py-2 bg-slate-700 text-white rounded border border-slate-600"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
        />
        <button
          onClick={sendMessage}
          className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition"
        >
          Send
        </button>
      </div>
    </div>
  )
}
