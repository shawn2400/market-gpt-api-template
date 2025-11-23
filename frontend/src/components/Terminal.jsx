import { useEffect, useRef, useState } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import api from '../api/client';
import '../styles/Terminal.css';

export default function Terminal() {
  const termRef = useRef(null);
  const termRef2 = useRef(null);
  const [logs, setLogs] = useState([]);

  useEffect(() => {
    if (!termRef.current) return;

    const term = new XTerm({
      theme: {
        background: '#0B0F17',
        foreground: '#E1E8ED',
        cursor: '#00FF00'
      },
      fontFamily: 'Monaco, Courier New, monospace',
      fontSize: 12,
      lineHeight: 1.2
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(termRef.current);
    fit.fit();

    term.write('\r\n✅ \x1b[32mALGO-REPLIT Terminal Connected\x1b[0m\r\n');
    term.write('Type your command and press Enter\r\n');
    term.write('$ ');

    let commandBuffer = '';

    term.onData(async (data) => {
      if (data === '\r') {
        term.write('\r\n');
        
        if (commandBuffer.trim()) {
          try {
            const res = await api.post('/api/info', {});
            term.write(`\x1b[36m> AlgoGPT Status\x1b[0m\r\n`);
            term.write(`Version: ${res.data.version}\r\n`);
            term.write(`Status: ${res.data.ok ? '🟢 ONLINE' : '🔴 OFFLINE'}\r\n`);
            setLogs([...logs, { cmd: commandBuffer, out: JSON.stringify(res.data) }]);
          } catch (err) {
            term.write(`\x1b[31mError: ${err.message}\x1b[0m\r\n`);
          }
          commandBuffer = '';
        }
        
        term.write('$ ');
      } else if (data === '\u007F') {
        if (commandBuffer.length > 0) {
          commandBuffer = commandBuffer.slice(0, -1);
          term.write('\b \b');
        }
      } else if (data.charCodeAt(0) > 31) {
        commandBuffer += data;
        term.write(data);
      }
    });

    const handleResize = () => fit.fit();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div className="terminal-container">
      <div className="terminal-header">
        <h3>🖥️ Terminal</h3>
        <span className="terminal-status">● LIVE</span>
      </div>
      <div ref={termRef} className="terminal" style={{ height: '100%' }} />
    </div>
  );
}
