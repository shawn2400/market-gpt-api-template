"""
Comprehensive Testing Suite Runner
Executes all tests (P1-17, P1-18, P1-19) and generates a summary report
"""
import asyncio
import subprocess
import sys
import json
from datetime import datetime
from pathlib import Path


class ComprehensiveTestRunner:
    def __init__(self):
        self.results = {
            "smoke_tests": None,
            "load_tests": None,
            "memory_tests": None,
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "PENDING"
        }
    
    async def run_smoke_tests(self):
        """Run smoke tests (P1-17)"""
        print("\n" + "="*70)
        print("🔥 PART 1: SMOKE TESTS (P1-17)")
        print("="*70)
        
        try:
            result = subprocess.run(
                [sys.executable, "tests/test_smoke_endpoints.py"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            self.results["smoke_tests"] = {
                "status": "PASS" if result.returncode == 0 else "FAIL",
                "return_code": result.returncode,
                "output": result.stdout
            }
            
            return result.returncode == 0
        except Exception as e:
            print(f"❌ Error running smoke tests: {e}")
            self.results["smoke_tests"] = {
                "status": "ERROR",
                "error": str(e)
            }
            return False
    
    async def run_load_tests(self):
        """Run load tests (P1-18)"""
        print("\n" + "="*70)
        print("⚡ PART 2: LOAD TESTS (P1-18)")
        print("="*70)
        
        try:
            import time
            start = time.time()
            
            result = subprocess.run(
                [sys.executable, "test_load.py"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            duration = time.time() - start
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            # Parse output to extract success count
            output = result.stdout
            success_count = 0
            if "100 requests succeeded" in output or "requests succeeded" in output:
                try:
                    # Extract number from "✅ XX/100 requests succeeded"
                    parts = output.split("/100 requests")
                    if parts:
                        success_count = int(parts[0].split()[-1])
                except:
                    pass
            
            success_rate = success_count / 100 * 100 if success_count > 0 else 0
            passed = success_rate >= 95 and duration < 10
            
            self.results["load_tests"] = {
                "status": "PASS" if passed else "FAIL",
                "success_count": success_count,
                "total_requests": 100,
                "success_rate": success_rate,
                "duration": duration,
                "target_success_rate": 95,
                "target_duration": 10,
                "output": result.stdout
            }
            
            print(f"\n📊 Load Test Results:")
            print(f"   Success Rate: {success_rate:.1f}% (target: >95%)")
            print(f"   Duration: {duration:.2f}s (target: <10s)")
            print(f"   Status: {'✅ PASS' if passed else '❌ FAIL'}")
            
            return passed
        except Exception as e:
            print(f"❌ Error running load tests: {e}")
            self.results["load_tests"] = {
                "status": "ERROR",
                "error": str(e)
            }
            return False
    
    async def run_memory_tests(self):
        """Run memory verification tests (P1-19)"""
        print("\n" + "="*70)
        print("💾 PART 3: MEMORY VERIFICATION (P1-19)")
        print("="*70)
        
        try:
            result = subprocess.run(
                [sys.executable, "tests/test_memory_usage.py"],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            self.results["memory_tests"] = {
                "status": "PASS" if result.returncode == 0 else "FAIL",
                "return_code": result.returncode,
                "output": result.stdout
            }
            
            return result.returncode == 0
        except Exception as e:
            print(f"❌ Error running memory tests: {e}")
            self.results["memory_tests"] = {
                "status": "ERROR",
                "error": str(e)
            }
            return False
    
    def generate_summary_report(self):
        """Generate final summary report"""
        print("\n" + "="*70)
        print("📋 COMPREHENSIVE TEST SUMMARY REPORT")
        print("="*70)
        print(f"\nTest Execution Time: {self.results['timestamp']}")
        print("\n" + "-"*70)
        
        # Part 1: Smoke Tests
        smoke = self.results.get("smoke_tests", {})
        print(f"\n✅ Part 1: Smoke Tests (P1-17)")
        print(f"   Status: {smoke.get('status', 'NOT RUN')}")
        if smoke.get('status') == 'PASS':
            print("   All critical endpoints responding correctly")
        
        # Part 2: Load Tests
        load = self.results.get("load_tests", {})
        print(f"\n⚡ Part 2: Load Tests (P1-18)")
        print(f"   Status: {load.get('status', 'NOT RUN')}")
        if load.get('success_rate'):
            print(f"   Success Rate: {load['success_rate']:.1f}% (target: >95%)")
            print(f"   Duration: {load['duration']:.2f}s (target: <10s)")
        
        # Part 3: Memory Tests
        memory = self.results.get("memory_tests", {})
        print(f"\n💾 Part 3: Memory Verification (P1-19)")
        print(f"   Status: {memory.get('status', 'NOT RUN')}")
        
        # Overall Status
        print("\n" + "-"*70)
        all_passed = all(
            r.get('status') in ['PASS', 'WARN'] 
            for r in [smoke, load, memory] 
            if r
        )
        
        if all_passed:
            self.results["overall_status"] = "PASS"
            print("🎉 Overall Status: ✅ ALL TESTS PASSED")
        else:
            self.results["overall_status"] = "FAIL"
            print("⚠️  Overall Status: ❌ SOME TESTS FAILED")
        
        print("="*70 + "\n")
        
        # Save report to file
        report_file = "test_results_summary.json"
        with open(report_file, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"📄 Detailed report saved to: {report_file}\n")
        
        return all_passed
    
    async def run_all(self):
        """Run all test suites"""
        print("\n" + "🚀"*35)
        print("COMPREHENSIVE TESTING SUITE - AlgoGPT")
        print("Tasks: P1-17 (Smoke), P1-18 (Load), P1-19 (Memory)")
        print("🚀"*35)
        
        # Run all test suites
        smoke_passed = await self.run_smoke_tests()
        load_passed = await self.run_load_tests()
        memory_passed = await self.run_memory_tests()
        
        # Generate final report
        all_passed = self.generate_summary_report()
        
        return all_passed


async def main():
    runner = ComprehensiveTestRunner()
    success = await runner.run_all()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
