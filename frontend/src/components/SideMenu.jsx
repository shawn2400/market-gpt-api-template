import { useState } from 'react';
import '../styles/SideMenu.css';

export default function SideMenu() {
  const [activeTab, setActiveTab] = useState('projects');

  const projects = [
    { id: 1, name: 'AlgoGPT-Main', status: 'running' },
    { id: 2, name: 'ALGO-REPLIT', status: 'ready' },
  ];

  return (
    <div className="side-menu">
      <div className="menu-header">
        <h2>🤖 ALGO-REPLIT</h2>
        <span className="version">v0.1.0</span>
      </div>

      <nav className="menu-nav">
        <button 
          className={`nav-btn ${activeTab === 'projects' ? 'active' : ''}`}
          onClick={() => setActiveTab('projects')}
        >
          📁 Projects
        </button>
        <button 
          className={`nav-btn ${activeTab === 'status' ? 'active' : ''}`}
          onClick={() => setActiveTab('status')}
        >
          ⚡ Status
        </button>
        <button 
          className={`nav-btn ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => setActiveTab('settings')}
        >
          ⚙️ Settings
        </button>
      </nav>

      <div className="menu-content">
        {activeTab === 'projects' && (
          <div className="projects-list">
            <h3>Projects</h3>
            {projects.map(p => (
              <div key={p.id} className="project-item">
                <span className={`status-dot ${p.status}`}></span>
                <span>{p.name}</span>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'status' && (
          <div className="status-list">
            <h3>System Status</h3>
            <div className="status-item">
              <span>AlgoGPT Server</span>
              <span className="badge running">🟢 RUNNING</span>
            </div>
            <div className="status-item">
              <span>ALGO-REPLIT</span>
              <span className="badge ready">🟡 READY</span>
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div className="settings-panel">
            <h3>Settings</h3>
            <div className="setting-item">
              <label>API URL</label>
              <input type="text" defaultValue="http://127.0.0.1:8000" />
            </div>
            <div className="setting-item">
              <label>Auto-Refresh (ms)</label>
              <input type="number" defaultValue="2000" />
            </div>
          </div>
        )}
      </div>

      <div className="menu-footer">
        <button className="btn-logout">Logout</button>
      </div>
    </div>
  );
}
