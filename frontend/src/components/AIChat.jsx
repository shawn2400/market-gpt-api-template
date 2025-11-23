import { useState, useRef, useEffect } from 'react';
import api from '../api/client';
import '../styles/AIChat.css';

export default function AIChat() {
  const [messages, setMessages] = useState([
    { role: 'system', text: '🤖 AI Assistant Ready. Type your question...' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMsg = input;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', text: userMsg }]);
    setLoading(true);

    try {
      // Simulate AI response from system status
      const res = await api.get('/api/info');
      const response = `AlgoGPT Status: Version ${res.data.version}, ${res.data.ok ? 'Online' : 'Offline'}. ${res.data.workflows_active} workflows active.`;
      setMessages(prev => [...prev, { role: 'assistant', text: response }]);
    } catch (err) {
      const response = `אני קשור ל-AlgoGPT backend. שם יכול לעזור עם ניהול סחר, ניתוח שוק, והתאמות סיסטם. נסה: "מה סטטוס המערכת?"`;
      setMessages(prev => [...prev, { role: 'assistant', text: response }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ai-chat-container">
      <div className="chat-header">
        <h3>💬 AI Chat</h3>
      </div>
      
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message message-${msg.role}`}>
            <span className="role-badge">{msg.role === 'user' ? '👤' : '🤖'}</span>
            <p>{msg.text}</p>
          </div>
        ))}
        <div ref={scrollRef} />
      </div>

      <div className="chat-input-box">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Ask me anything..."
          disabled={loading}
        />
        <button onClick={handleSend} disabled={loading}>
          {loading ? '⏳' : '📤'}
        </button>
      </div>
    </div>
  );
}
