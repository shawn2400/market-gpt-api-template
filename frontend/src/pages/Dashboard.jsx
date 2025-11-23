import { useState } from 'react';
import SideMenu from '../components/SideMenu';
import Terminal from '../components/Terminal';
import AIChat from '../components/AIChat';
import StatusBar from '../components/StatusBar';
import '../styles/Dashboard.css';

export default function Dashboard() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="dashboard">
      <div className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
        {!collapsed && <SideMenu />}
        <button 
          className="collapse-btn"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? '→' : '←'}
        </button>
      </div>

      <div className="main-content">
        <header className="top-bar">
          <h1>🚀 AlgoGPT Control Center</h1>
          <div className="header-actions">
            <button className="btn btn-small btn-success">
              ▶️ Auto-Pilot ON
            </button>
            <button className="btn btn-small btn-danger">
              ⏹️ Freeze All
            </button>
            <button className="btn btn-small btn-primary">
              ⚙️ Settings
            </button>
          </div>
        </header>

        <div className="content-grid">
          <div className="panel terminal-panel">
            <Terminal />
          </div>
          <div className="panel chat-panel">
            <AIChat />
          </div>
        </div>

        <footer className="bottom-bar">
          <StatusBar />
        </footer>
      </div>
    </div>
  );
}
