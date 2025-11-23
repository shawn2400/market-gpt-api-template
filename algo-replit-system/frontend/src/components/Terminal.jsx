import React, { useEffect, useRef } from 'react'

export default function Terminal({ api }) {
  const terminalRef = useRef(null)

  useEffect(() => {
    // Initialize terminal if available
    if (terminalRef.current) {
      terminalRef.current.innerHTML = '<div class="text-green-400 font-mono">Terminal ready...</div>'
    }
  }, [])

  return (
    <div className="flex flex-col h-full p-6">
      <h2 className="text-2xl font-bold mb-6">💻 Terminal</h2>
      <div
        ref={terminalRef}
        className="flex-1 bg-slate-950 p-4 rounded border border-slate-700 font-mono text-sm text-green-400 overflow-auto"
      />
    </div>
  )
}
