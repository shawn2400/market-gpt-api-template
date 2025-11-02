#!/usr/bin/env python3
"""
בדיקת מערכת החתימות החכמה
"""
import os
import sys
sys.path.insert(0, os.getcwd())

from utils.smart_signature import smart_sig

def test_smart_signatures():
    """בודק את המערכת החכמה"""
    print("="*60)
    print("🔬 בדיקת מערכת חתימות חכמה")
    print("="*60 + "\n")
    
    # Test cases
    test_ids = [
        "TKT-123456",                # Short normal ID
        "g1762026723820",            # Long GRID ID
        "TKT-faed09942209fc43",      # Medium ID
        "g1762027686567890123456",   # Extra long GRID ID
    ]
    
    results = []
    
    for trade_id in test_ids:
        print(f"Testing: {trade_id}")
        print(f"Length: {len(trade_id)} chars")
        
        # Create callback
        callback = smart_sig.make_callback("APPROVE", trade_id)
        print(f"Callback: {callback}")
        status = "✅" if len(callback) <= 64 else "❌"
        print(f"Callback Length: {status} {len(callback)}/64 bytes")
        
        # Verify callback
        try:
            result = smart_sig.verify_callback(callback)
            print(f"✅ Verified! Original ID recovered: {result['trade_id']}")
            results.append(True)
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            results.append(False)
        
        print()
    
    # Show health report
    print("="*60)
    print("📊 System Health Report")
    print("="*60)
    
    health = smart_sig.get_health_report()
    print(f"Mood: {health['mood']}")
    print(f"Success Rate: {health['success_rate']}")
    print(f"Stats: {health['stats']}")
    print(f"Recommendation: {health['recommendation']}")
    
    # Overall result
    success_count = sum(results)
    total_count = len(results)
    print("\n" + "="*60)
    
    if success_count == total_count:
        print(f"🎉 ALL TESTS PASSED! ({success_count}/{total_count})")
        print("המערכת החכמה עובדת מצוין!")
    else:
        print(f"⚠️ Some tests failed ({success_count}/{total_count})")
        print("המערכת לומדת ומשתפרת...")

if __name__ == "__main__":
    test_smart_signatures()