import React, { useState } from 'react'

export default function ProjectManager({ api, projects, onRefresh }) {
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectTemplate, setNewProjectTemplate] = useState('python')

  const createProject = async () => {
    if (!newProjectName) return
    try {
      await api.post('/projects/create', {
        name: newProjectName,
        template: newProjectTemplate,
      })
      setNewProjectName('')
      onRefresh()
    } catch (err) {
      console.error('Failed to create project:', err)
    }
  }

  return (
    <div className="p-6 overflow-auto">
      <h2 className="text-2xl font-bold mb-6">📁 Projects</h2>

      <div className="bg-slate-800 p-6 rounded border border-slate-700 mb-6">
        <h3 className="font-semibold mb-4">Create New Project</h3>
        <div className="flex gap-4">
          <input
            type="text"
            placeholder="Project name"
            className="flex-1 px-4 py-2 bg-slate-700 text-white rounded border border-slate-600"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
          />
          <select
            className="px-4 py-2 bg-slate-700 text-white rounded border border-slate-600"
            value={newProjectTemplate}
            onChange={(e) => setNewProjectTemplate(e.target.value)}
          >
            <option>python</option>
            <option>node</option>
          </select>
          <button
            onClick={createProject}
            className="px-6 py-2 bg-green-600 hover:bg-green-700 text-white rounded transition"
          >
            Create
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {projects.map((project) => (
          <div key={project.name} className="bg-slate-800 p-4 rounded border border-slate-700">
            <h3 className="font-semibold text-lg">{project.name}</h3>
            <p className="text-slate-400 text-sm">{project.template}</p>
            <p className="text-slate-500 text-xs mt-2">Created: {new Date(project.created_at).toLocaleDateString()}</p>
            <div className="mt-4 flex gap-2">
              <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition text-sm">
                Open
              </button>
              <button className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white rounded transition text-sm">
                Run
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
