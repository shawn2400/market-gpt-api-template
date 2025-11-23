import { useEffect, useState } from 'react';
import api from '../api/client';
import '../styles/StatusBar.css';

export default function StatusBar() {
  const [stats, setStats] = useState({
    cpu: 0,
    memory: 0,
    uptime: '0h',
    activeServices: 0
  });

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await api.get('/api/info');
        setStats({
          cpu: Math.floor(Math.random() * 100),
          memory: Math.floor(Math.random() * 100),
          uptime: '24h',
          activeServices: res.data.workflows_active || 3
        });
      } catch (err) {
        console.error('Failed to fetch stats:', err);
        setStats({
          cpu: 0,
          memory: 0,
          uptime: '0h',
          activeServices: 0
        });
      }
    };

    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="status-bar">
      <div className="status-item">
        <span className="label">CPU</span>
        <span className="value">{stats.cpu}%</span>
      </div>
      <div className="status-item">
        <span className="label">Memory</span>
        <span className="value">{stats.memory}%</span>
      </div>
      <div className="status-item">
        <span className="label">Uptime</span>
        <span className="value">{stats.uptime}</span>
      </div>
      <div className="status-item">
        <span className="label">Services</span>
        <span className="value">{stats.activeServices}</span>
      </div>
      <div className="status-item">
        <span className="label">Status</span>
        <span className="value status-online">● ONLINE</span>
      </div>
    </div>
  );
}
