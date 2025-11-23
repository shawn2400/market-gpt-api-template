import subprocess

def run_command(cmd: str):
    """Execute shell command"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "status": "ok" if result.returncode == 0 else "error"
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "message": "Command exceeded 30 second timeout"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
