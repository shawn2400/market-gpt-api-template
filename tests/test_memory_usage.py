"""
Memory Usage Verification Test (P1-19)
Monitors memory consumption of Python processes during operations
"""
import subprocess
import time
import httpx
import asyncio
from typing import Dict, List


def get_python_memory_usage() -> Dict:
    """Get memory usage of all Python processes"""
    try:
        # Run ps aux and filter for python processes
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True
        )
        
        lines = result.stdout.split('\n')
        python_processes = []
        total_rss_kb = 0
        
        for line in lines:
            if 'python' in line.lower() and 'grep' not in line:
                parts = line.split()
                if len(parts) >= 11:
                    # Extract process info
                    user = parts[0]
                    pid = parts[1]
                    cpu = parts[2]
                    mem_percent = parts[3]
                    vsz = parts[4]  # Virtual memory size in KB
                    rss = parts[5]  # Resident set size in KB
                    cmd = ' '.join(parts[10:])
                    
                    try:
                        rss_kb = int(rss)
                        total_rss_kb += rss_kb
                        
                        python_processes.append({
                            "pid": pid,
                            "user": user,
                            "cpu": cpu,
                            "mem_percent": mem_percent,
                            "rss_mb": rss_kb / 1024,
                            "command": cmd[:80]
                        })
                    except ValueError:
                        continue
        
        total_mb = total_rss_kb / 1024
        total_gb = total_mb / 1024
        
        return {
            "processes": python_processes,
            "total_mb": total_mb,
            "total_gb": total_gb,
            "process_count": len(python_processes)
        }
    except Exception as e:
        print(f"Error getting memory usage: {e}")
        return {
            "processes": [],
            "total_mb": 0,
            "total_gb": 0,
            "process_count": 0,
            "error": str(e)
        }


async def trigger_operations():
    """Trigger some operations to test memory under load"""
    print("🔄 Triggering operations...")
    
    base_url = "http://127.0.0.1:5000"
    operations = [
        "/monitors/health",
        "/dashboard/roadmap/data",
        "/kpis/live",
        "/ai/leaderboard?timeframe_days=7",
    ]
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []
            for endpoint in operations:
                url = f"{base_url}{endpoint}"
                # Make 5 requests to each endpoint
                for _ in range(5):
                    tasks.append(client.get(url))
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            success = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
            print(f"   Completed {success}/{len(tasks)} API calls successfully")
    except Exception as e:
        print(f"   Error during operations: {e}")


def print_memory_details(label: str, mem_data: Dict):
    """Print memory usage details"""
    print(f"\n{label}")
    print("-" * 60)
    print(f"Total Python Processes: {mem_data['process_count']}")
    print(f"Total Memory Usage: {mem_data['total_mb']:.2f} MB ({mem_data['total_gb']:.3f} GB)")
    
    if mem_data['processes']:
        print(f"\nTop Memory Consumers:")
        # Sort by memory usage
        sorted_procs = sorted(mem_data['processes'], key=lambda x: x['rss_mb'], reverse=True)
        for i, proc in enumerate(sorted_procs[:5], 1):
            print(f"  {i}. PID {proc['pid']}: {proc['rss_mb']:.2f} MB - {proc['command']}")
    print("-" * 60)


async def main():
    print("\n" + "="*60)
    print("💾 Memory Usage Verification Test (P1-19)")
    print("="*60 + "\n")
    
    # Step 1: Initial memory check
    print("📊 Step 1: Checking initial memory usage...")
    initial_mem = get_python_memory_usage()
    print_memory_details("Initial Memory Usage", initial_mem)
    
    # Step 2: Trigger operations
    print("\n📊 Step 2: Triggering operations...")
    await trigger_operations()
    
    # Step 3: Wait 30 seconds
    print("\n📊 Step 3: Waiting 30 seconds for memory to stabilize...")
    for i in range(30, 0, -5):
        print(f"   {i} seconds remaining...")
        time.sleep(5)
    
    # Step 4: Final memory check
    print("\n📊 Step 4: Checking memory usage after operations...")
    final_mem = get_python_memory_usage()
    print_memory_details("Final Memory Usage", final_mem)
    
    # Step 5: Analysis
    print("\n" + "="*60)
    print("📈 MEMORY ANALYSIS")
    print("="*60)
    
    mem_increase_mb = final_mem['total_mb'] - initial_mem['total_mb']
    mem_increase_percent = (mem_increase_mb / initial_mem['total_mb'] * 100) if initial_mem['total_mb'] > 0 else 0
    
    print(f"\nMemory Change: {mem_increase_mb:+.2f} MB ({mem_increase_percent:+.1f}%)")
    print(f"Final Memory: {final_mem['total_gb']:.3f} GB")
    
    # Verify limits
    print("\n" + "-"*60)
    print("VERIFICATION:")
    
    # Target: < 1.5GB, ideal < 1.2GB
    if final_mem['total_gb'] < 1.2:
        print(f"✅ PASS: Memory ({final_mem['total_gb']:.3f} GB) is under ideal limit (1.2 GB)")
        status = "PASS"
    elif final_mem['total_gb'] < 1.5:
        print(f"⚠️  WARN: Memory ({final_mem['total_gb']:.3f} GB) is acceptable but above ideal (1.2 GB)")
        status = "WARN"
    else:
        print(f"❌ FAIL: Memory ({final_mem['total_gb']:.3f} GB) exceeds limit (1.5 GB)")
        status = "FAIL"
    
    print("-"*60 + "\n")
    
    return {
        "status": status,
        "initial_mb": initial_mem['total_mb'],
        "final_mb": final_mem['total_mb'],
        "increase_mb": mem_increase_mb,
        "final_gb": final_mem['total_gb'],
        "limit_gb": 1.5,
        "ideal_gb": 1.2
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    if result["status"] == "FAIL":
        exit(1)
    else:
        exit(0)
