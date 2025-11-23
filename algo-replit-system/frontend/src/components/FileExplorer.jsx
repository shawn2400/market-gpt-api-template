import React, { useState } from 'react'

export default function FileExplorer({ onSelectFile }) {
  const [expandedFolders, setExpandedFolders] = useState(new Set())

  const toggleFolder = (path) => {
    const newExpanded = new Set(expandedFolders)
    if (newExpanded.has(path)) {
      newExpanded.delete(path)
    } else {
      newExpanded.add(path)
    }
    setExpandedFolders(newExpanded)
  }

  return (
    <div className="w-48 bg-slate-800 border-r border-slate-700 p-4 overflow-y-auto">
      <h3 className="font-semibold mb-4">Files</h3>
      {/* File tree will be populated here */}
    </div>
  )
}
