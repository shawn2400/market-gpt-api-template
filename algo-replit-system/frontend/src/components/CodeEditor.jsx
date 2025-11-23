import React, { useState } from 'react'

export default function CodeEditor({ api }) {
  const [filePath, setFilePath] = useState('')
  const [content, setContent] = useState('')

  const loadFile = async () => {
    if (!filePath) return
    try {
      const res = await api.post('/files/read', { path: filePath })
      setContent(res.data.content)
    } catch (err) {
      console.error('Failed to load file:', err)
    }
  }

  const saveFile = async () => {
    if (!filePath) return
    try {
      await api.post('/files/write', {
        path: filePath,
        content: content,
      })
      alert('File saved!')
    } catch (err) {
      console.error('Failed to save file:', err)
    }
  }

  return (
    <div className="flex flex-col h-full p-6 overflow-auto">
      <h2 className="text-2xl font-bold mb-6">✏️ Code Editor</h2>

      <div className="flex gap-2 mb-4">
        <input
          type="text"
          placeholder="File path..."
          className="flex-1 px-4 py-2 bg-slate-700 text-white rounded border border-slate-600"
          value={filePath}
          onChange={(e) => setFilePath(e.target.value)}
        />
        <button
          onClick={loadFile}
          className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition"
        >
          Load
        </button>
        <button
          onClick={saveFile}
          className="px-6 py-2 bg-green-600 hover:bg-green-700 text-white rounded transition"
        >
          Save
        </button>
      </div>

      <textarea
        className="flex-1 p-4 bg-slate-800 text-white rounded border border-slate-700 font-mono text-sm"
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
    </div>
  )
}
