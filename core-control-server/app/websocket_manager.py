from fastapi import WebSocket
import subprocess
import asyncio

async def terminal_session(ws: WebSocket):
    """Interactive terminal over WebSocket"""
    await ws.accept()
    
    try:
        # Start bash process
        process = await asyncio.create_subprocess_shell(
            "/bin/bash",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Task to read output
        async def read_output():
            try:
                while True:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=1.0
                    )
                    if not line:
                        break
                    await ws.send_text(line.decode('utf-8', errors='replace'))
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                await ws.send_text(f"Error: {str(e)}\n")
        
        # Start reading output
        read_task = asyncio.create_task(read_output())
        
        # Handle incoming commands
        try:
            while True:
                data = await ws.receive_text()
                if data:
                    process.stdin.write((data + "\n").encode())
                    await process.stdin.drain()
        except Exception:
            pass
        
        # Cleanup
        process.terminate()
        read_task.cancel()
        
    except Exception as e:
        await ws.send_text(f"WebSocket error: {str(e)}\n")
