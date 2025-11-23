import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import FileExplorer from './components/FileExplorer'
import CodeEditor from './components/CodeEditor'
import Terminal from './components/Terminal'
import AIChat from './components/AIChat'
import ProjectManager from './components/ProjectManager'

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('admin_token') || '')
  const [authenticated, setAuthenticated] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [currentView, setCurrentView] = useState('dashboard')
  const [systemStatus, setSystemStatus] = useState(null)
  const [projects, setProjects] = useState([])

  const api = axios.create({
    baseURL: '/api',
    params: { token },
  })

  useEffect(() => {
    if (token) {
      validateToken()
    }
  }, [token])

  const validateToken = async () => {
    try {
      const res = await api.get('/status')
      setAuthenticated(true)
      localStorage.setItem('admin_token', token)
      loadSystemStatus()
      loadProjects()
    } catch (err) {
      setAuthenticated(false)
    }
  }

  const handleLogin = () => {
    setToken(token)
  }

  const loadSystemStatus = async () => {
    try {
      const res = await api.get('/health')
      setSystemStatus(res.data)
    } catch (err) {
      console.error('Failed to load system status:', err)
    }
  }

  const loadProjects = async () => {
    try {
      const res = await api.get('/projects')
      setProjects(res.data.projects)
    } catch (err) {
      console.error('Failed to load projects:', err)
    }
  }

  if (!authenticated) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900">
        <div className="bg-slate-800 p-8 rounded-lg shadow-lg border border-slate-700 w-96">
          <h1 className="text-2xl font-bold text-white mb-6">ALGO-REPLIT</h1>
          <input
            type="password"
            placeholder="Admin Token"
            className="w-full px-4 py-2 bg-slate-700 text-white rounded border border-slate-600 mb-4"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
          <button
            onClick={handleLogin}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2 rounded transition"
          >
            Login
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-slate-900 text-slate-100">
      {/* Header */}
      <header className="bg-slate-800 border-b border-slate-700 p-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">🚀 ALGO-REPLIT Control Center</h1>
        <div className="text-sm text-slate-400">
          {systemStatus && (
            <>
              CPU: {systemStatus.resources?.cpu_percent?.toFixed(1)}% | 
              Memory: {systemStatus.resources?.memory_percent?.toFixed(1)}%
            </>
          )}
        </div>
      </header>

      {/* Main Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <nav className="w-48 bg-slate-800 border-r border-slate-700 p-4 overflow-y-auto">
          <div className="space-y-2">
            <button
              onClick={() => setCurrentView('dashboard')}
              className={`w-full text-left px-4 py-2 rounded ${
                currentView === 'dashboard'
                  ? 'bg-blue-600'
                  : 'hover:bg-slate-700'
              }`}
            >
              📊 Dashboard
            </button>
            <button
              onClick={() => setCurrentView('projects')}
              className={`w-full text-left px-4 py-2 rounded ${
                currentView === 'projects'
                  ? 'bg-blue-600'
                  : 'hover:bg-slate-700'
              }`}
            >
              📁 Projects
            </button>
            <button
              onClick={() => setCurrentView('editor')}
              className={`w-full text-left px-4 py-2 rounded ${
                currentView === 'editor'
                  ? 'bg-blue-600'
                  : 'hover:bg-slate-700'
              }`}
            >
              ✏️ Editor
            </button>
            <button
              onClick={() => setCurrentView('terminal')}
              className={`w-full text-left px-4 py-2 rounded ${
                currentView === 'terminal'
                  ? 'bg-blue-600'
                  : 'hover:bg-slate-700'
              }`}
            >
              💻 Terminal
            </button>
            <button
              onClick={() => setCurrentView('ai')}
              className={`w-full text-left px-4 py-2 rounded ${
                currentView === 'ai'
                  ? 'bg-blue-600'
                  : 'hover:bg-slate-700'
              }`}
            >
              🤖 AI Chat
            </button>
            <hr className="border-slate-700 my-4" />
            <button
              onClick={() => setToken('')}
              className="w-full text-left px-4 py-2 rounded hover:bg-slate-700 text-red-400"
            >
              🚪 Logout
            </button>
          </div>
        </nav>

        {/* Content Area */}
        <div className="flex-1 overflow-hidden">
          {currentView === 'dashboard' && (
            <div className="p-6 overflow-auto">
              <h2 className="text-2xl font-bold mb-6">System Dashboard</h2>
              {systemStatus && (
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-800 p-4 rounded border border-slate-700">
                    <h3 className="font-semibold mb-2">📊 CPU Usage</h3>
                    <p className="text-2xl">{systemStatus.resources?.cpu_percent?.toFixed(1)}%</p>
                  </div>
                  <div className="bg-slate-800 p-4 rounded border border-slate-700">
                    <h3 className="font-semibold mb-2">🧠 Memory Usage</h3>
                    <p className="text-2xl">{systemStatus.resources?.memory_percent?.toFixed(1)}%</p>
                  </div>
                  <div className="bg-slate-800 p-4 rounded border border-slate-700">
                    <h3 className="font-semibold mb-2">💾 Available Memory</h3>
                    <p className="text-2xl">{systemStatus.resources?.memory_available_mb}MB</p>
                  </div>
                  <div className="bg-slate-800 p-4 rounded border border-slate-700">
                    <h3 className="font-semibold mb-2">🔄 Scale Mode</h3>
                    <p className={systemStatus.scale_mode_enabled ? 'text-green-400' : 'text-yellow-400'}>
                      {systemStatus.scale_mode_enabled ? 'ENABLED' : 'DORMANT'}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {currentView === 'projects' && (
            <ProjectManager api={api} projects={projects} onRefresh={loadProjects} />
          )}

          {currentView === 'editor' && (
            <CodeEditor api={api} />
          )}

          {currentView === 'terminal' && (
            <Terminal api={api} />
          )}

          {currentView === 'ai' && (
            <AIChat api={api} />
          )}
        </div>
      </div>
    </div>
  )
}
