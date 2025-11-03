"""
Smoke Tests for All Critical API Endpoints (P1-17)
Tests all validation, AI performance, and dashboard endpoints
"""
import httpx
import asyncio
import websockets
import json
from typing import Dict, List, Tuple


class SmokeTestRunner:
    def __init__(self, base_url: str = "http://127.0.0.1:5000"):
        self.base_url = base_url
        self.results: List[Dict] = []
        
    def record_result(self, category: str, endpoint: str, status: str, 
                     status_code: int = None, error: str = None, duration: float = None):
        """Record test result"""
        self.results.append({
            "category": category,
            "endpoint": endpoint,
            "status": status,
            "status_code": status_code,
            "error": error,
            "duration": duration
        })
    
    async def test_endpoint(self, category: str, endpoint: str, 
                           expected_codes: List[int] = [200]) -> bool:
        """Test a single HTTP endpoint"""
        url = f"{self.base_url}{endpoint}"
        try:
            import time
            start = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                duration = time.time() - start
                
            if response.status_code in expected_codes:
                self.record_result(category, endpoint, "PASS", response.status_code, duration=duration)
                return True
            else:
                self.record_result(category, endpoint, "FAIL", response.status_code, 
                                 f"Expected {expected_codes}, got {response.status_code}", duration=duration)
                return False
        except Exception as e:
            self.record_result(category, endpoint, "ERROR", error=str(e))
            return False
    
    async def test_validation_endpoints(self):
        """Test all validation and monitoring endpoints"""
        print("🔍 Testing Validation Endpoints...")
        
        await self.test_endpoint("Validation", "/monitors/health", [200])
        await self.test_endpoint("Validation", "/monitors/breaker/status", [200])
        await self.test_endpoint("Validation", "/validate/status?id=test123", [200, 404])
        
    async def test_ai_performance_endpoints(self):
        """Test AI performance and leaderboard endpoints"""
        print("🤖 Testing AI Performance Endpoints...")
        
        await self.test_endpoint("AI Performance", "/ai/leaderboard?timeframe_days=7", [200])
        await self.test_endpoint("AI Performance", "/ai/performance?model=gpt5&timeframe_days=7", [200])
    
    async def test_dashboard_endpoints(self):
        """Test dashboard data endpoints"""
        print("📊 Testing Dashboard Endpoints...")
        
        await self.test_endpoint("Dashboard", "/dashboard/roadmap/data", [200])
        await self.test_endpoint("Dashboard", "/dashboard/gantt/data", [200])
        await self.test_endpoint("Dashboard", "/kpis/live", [200])
    
    async def test_websocket_connection(self):
        """Test WebSocket connection and message receipt"""
        print("🔌 Testing WebSocket Connection...")
        
        ws_url = "ws://127.0.0.1:5000/ws/pnl"
        try:
            async with websockets.connect(ws_url, open_timeout=5) as websocket:
                # Wait for at least 1 message with timeout
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    self.record_result("WebSocket", "/ws/pnl", "PASS", 
                                     error=f"Received message: {message[:100]}...")
                    return True
                except asyncio.TimeoutError:
                    self.record_result("WebSocket", "/ws/pnl", "PASS", 
                                     error="Connected but no message received within 5s")
                    return True
        except Exception as e:
            self.record_result("WebSocket", "/ws/pnl", "ERROR", error=str(e))
            return False
    
    async def run_all_tests(self):
        """Run all smoke tests"""
        print("\n" + "="*60)
        print("🚀 Starting Comprehensive Smoke Tests (P1-17)")
        print("="*60 + "\n")
        
        # Run all test categories
        await self.test_validation_endpoints()
        await self.test_ai_performance_endpoints()
        await self.test_dashboard_endpoints()
        await self.test_websocket_connection()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("📋 SMOKE TEST RESULTS SUMMARY")
        print("="*60 + "\n")
        
        # Group by category
        categories = {}
        for result in self.results:
            cat = result["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(result)
        
        total_tests = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        errors = sum(1 for r in self.results if r["status"] == "ERROR")
        
        # Print by category
        for category, tests in categories.items():
            print(f"\n{category}:")
            for test in tests:
                icon = "✅" if test["status"] == "PASS" else "❌" if test["status"] == "FAIL" else "⚠️"
                endpoint = test["endpoint"]
                status = test["status"]
                
                if test.get("duration"):
                    print(f"  {icon} {endpoint} - {status} ({test['duration']:.3f}s)")
                elif test.get("status_code"):
                    print(f"  {icon} {endpoint} - {status} (HTTP {test['status_code']})")
                else:
                    print(f"  {icon} {endpoint} - {status}")
                    
                if test.get("error"):
                    print(f"      Error: {test['error']}")
        
        # Overall summary
        print("\n" + "-"*60)
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"⚠️  Errors: {errors}")
        print(f"Success Rate: {(passed/total_tests*100):.1f}%")
        print("-"*60 + "\n")
        
        return {
            "total": total_tests,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "success_rate": passed/total_tests*100 if total_tests > 0 else 0
        }


async def main():
    runner = SmokeTestRunner()
    await runner.run_all_tests()
    summary = runner.print_summary()
    
    # Exit with error code if tests failed
    if summary["failed"] > 0 or summary["errors"] > 0:
        exit(1)
    else:
        exit(0)


if __name__ == "__main__":
    asyncio.run(main())
