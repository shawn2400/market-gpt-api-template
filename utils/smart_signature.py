"""
Smart Signature System - מערכת חתימות חכמה ואוטונומית
מזהה בעיות ומתקנת אותן דינמית בזמן אמת
"""
import hashlib
import hmac
import time
import logging
from typing import Dict, Any, Optional, Tuple
import json
import os

logger = logging.getLogger("algogpt.smart_sig")

class SmartSignature:
    """מערכת חתימות חכמה שמתאימה את עצמה דינמית"""
    
    def __init__(self):
        self.secret = (os.getenv("OPS_SIGN_SECRET", "") or 
                      os.getenv("WEBHOOK_HMAC_SECRET", "")).strip()
        self.mood = "OPTIMIZED"  # AGGRESSIVE, SAFE, OPTIMIZED
        self.stats = {
            "success": 0,
            "failures": 0,
            "auto_fixes": 0
        }
        
    def analyze_mood(self) -> str:
        """מנתח את המצב ומחליט על אסטרטגיה"""
        if self.stats["failures"] > 3:
            self.mood = "SAFE"
            logger.warning("🔴 MOOD: SAFE - Too many failures, switching to safe mode")
        elif self.stats["success"] > 10 and self.stats["failures"] == 0:
            self.mood = "AGGRESSIVE"  
            logger.info("🟢 MOOD: AGGRESSIVE - Everything working, optimizing")
        else:
            self.mood = "OPTIMIZED"
            logger.info("🟡 MOOD: OPTIMIZED - Balanced approach")
        return self.mood
        
    def smart_hash(self, trade_id: str) -> str:
        """יוצר hash חכם שמשתנה לפי הצורך"""
        # Strategy based on mood
        if self.mood == "SAFE":
            # Super short, guaranteed to work
            return hashlib.md5(trade_id.encode()).hexdigest()[:6]
        elif self.mood == "AGGRESSIVE":
            # Keep more info for tracking
            if len(trade_id) <= 12:
                return trade_id
            return trade_id[:8] + trade_id[-4:]
        else:  # OPTIMIZED
            # Balanced approach
            if len(trade_id) <= 10:
                return trade_id
            # Smart truncate: keep prefix + unique suffix
            return f"{trade_id[:7]}_{trade_id[-3:]}"
            
    def make_callback(self, action: str, trade_id: str) -> str:
        """יוצר callback עם חתימה חכמה"""
        self.analyze_mood()  # Check current mood
        
        # Smart ID handling
        smart_id = self.smart_hash(trade_id)
        
        # Store mapping for recovery
        self.store_mapping(trade_id, smart_id)
        
        # Build callback
        now = int(time.time())
        data = f"CONFIRM:{action}:{smart_id}"
        
        logger.info(f"📝 Creating callback: action={action}, trade_id={trade_id}, smart_id={smart_id}, ts={now}")
        logger.info(f"📝 Secret available: {bool(self.secret)}, secret_len={len(self.secret) if self.secret else 0}")
        
        if not self.secret:
            logger.warning("⚠️ No secret configured, returning unsigned callback")
            return data
            
        # Dynamic signature length based on mood
        sig_len = {"SAFE": 4, "OPTIMIZED": 6, "AGGRESSIVE": 8}[self.mood]
        
        raw = f"{data}:{now}"
        full_hash = hmac.new(
            self.secret.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        sig = full_hash[:sig_len]
        
        logger.info(f"📝 Signature: mood={self.mood}, sig_len={sig_len}, raw={raw}")
        logger.info(f"📝 Full hash: {full_hash}")
        logger.info(f"📝 Sig[:{sig_len}]: {sig}")
        
        callback = f"{raw}:{sig}"
        
        # Auto-fix if too long
        if len(callback) > 64:
            logger.warning(f"Auto-fixing long callback: {len(callback)} bytes")
            self.stats["auto_fixes"] += 1
            # Recursively fix with safer mood
            self.mood = "SAFE"
            return self.make_callback(action, trade_id)
            
        logger.info(f"✅ Callback created ({self.mood}): {smart_id} (len={len(callback)}) | callback={callback}")
        return callback
        
    def verify_callback(self, data: str) -> Dict[str, Any]:
        """מאמת callback עם recovery אוטומטי"""
        try:
            parts = data.split(":")
            logger.info(f"🔍 Verify callback - data parts: {len(parts)} | data: {data[:100]}...")
            
            if len(parts) < 5:
                logger.error(f"❌ Invalid format: expected >=5 parts, got {len(parts)}")
                raise ValueError("invalid_format")
                
            action = parts[1]
            smart_id = parts[2]
            ts = int(parts[-2])
            sig_received = parts[-1]
            
            logger.info(f"🔍 Parsed: action={action}, smart_id={smart_id}, ts={ts}, sig_recv={sig_received}")
            logger.info(f"🔍 Secret available: {bool(self.secret)}, secret_len={len(self.secret) if self.secret else 0}")
            
            # Build raw data (without signature)
            raw = ":".join(parts[:-1])
            
            # Try different signature lengths (auto-adapt)
            for sig_len in [4, 6, 8]:
                sig_calc = hmac.new(
                    self.secret.encode("utf-8"),
                    raw.encode("utf-8"),
                    hashlib.sha256
                ).hexdigest()[:sig_len]
                
                logger.info(f"🔍 Try sig_len={sig_len}: raw={raw[:80]}... | calc={sig_calc} | recv={sig_received} | match={sig_calc == sig_received}")
                
                if sig_calc == sig_received:
                    # Success! Learn from it
                    self.stats["success"] += 1
                    logger.info(f"✅ Verified with sig_len={sig_len}")
                    
                    # Recover original ID
                    original_id = self.recover_mapping(smart_id)
                    
                    return {
                        "action": action,
                        "trade_id": original_id or smart_id
                    }
                    
            # Failed all attempts - detailed debug
            full_hash = hmac.new(
                self.secret.encode("utf-8"),
                raw.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            self.stats["failures"] += 1
            logger.error(f"❌ Signature mismatch for all lengths (4/6/8)")
            logger.error(f"❌ Full hash: {full_hash}")
            logger.error(f"❌ Hash[:4]: {full_hash[:4]} vs recv: {sig_received}")
            logger.error(f"❌ Hash[:6]: {full_hash[:6]} vs recv: {sig_received}")
            logger.error(f"❌ Hash[:8]: {full_hash[:8]} vs recv: {sig_received}")
            logger.error(f"❌ Raw data: {raw}")
            raise ValueError("bad_sig")
            
        except Exception as e:
            logger.error(f"Verify failed: {e}")
            self.stats["failures"] += 1
            raise
            
    def store_mapping(self, original: str, smart: str):
        """שומר מיפוי לשחזור"""
        try:
            # Store in memory/file/db
            mapping_file = "/tmp/trade_id_mapping.json"
            mappings = {}
            if os.path.exists(mapping_file):
                try:
                    with open(mapping_file) as f:
                        content = f.read().strip()
                        if content:
                            mappings = json.loads(content)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Invalid mapping file, recreating: {e}")
                    mappings = {}
            
            # Store both directions for better recovery
            mappings[smart] = original
            # Also store the original as-is for direct lookups
            mappings[original] = original
            
            # Keep only last 1000 mappings to prevent unbounded growth
            if len(mappings) > 1000:
                # Keep the most recent entries
                sorted_items = sorted(mappings.items(), key=lambda x: x[0])
                mappings = dict(sorted_items[-1000:])
            
            with open(mapping_file, 'w') as f:
                json.dump(mappings, f, indent=2)
            logger.info(f"Stored mapping: {smart} -> {original} (total mappings: {len(mappings)})")
        except Exception as e:
            logger.error(f"Failed to store mapping: {e}")
            
    def recover_mapping(self, smart: str) -> Optional[str]:
        """משחזר ID מקורי"""
        try:
            mapping_file = "/tmp/trade_id_mapping.json"
            if os.path.exists(mapping_file):
                with open(mapping_file) as f:
                    content = f.read().strip()
                    if content:
                        mappings = json.loads(content)
                        # Direct lookup
                        result = mappings.get(smart)
                        if result:
                            logger.info(f"Recovered mapping: {smart} -> {result}")
                            return result
                        
                        # Try pattern matching for partial matches
                        # This handles cases where the smart ID might have slight variations
                        for key, value in mappings.items():
                            if smart in key or key in smart:
                                logger.info(f"Recovered via pattern match: {smart} -> {value}")
                                return value
        except Exception as e:
            logger.warning(f"Failed to recover mapping for {smart}: {e}")
        
        logger.debug(f"No mapping found for {smart}")
        return None
        
    def get_health_report(self) -> Dict[str, Any]:
        """דוח מצב המערכת"""
        total = self.stats["success"] + self.stats["failures"]
        success_rate = (self.stats["success"] / total * 100) if total > 0 else 0
        
        return {
            "mood": self.mood,
            "success_rate": f"{success_rate:.1f}%",
            "stats": self.stats,
            "recommendation": self._get_recommendation()
        }
        
    def _get_recommendation(self) -> str:
        """המלצה לשיפור"""
        if self.stats["failures"] > 5:
            return "🔴 Too many failures - switching to ultra-safe mode"
        elif self.stats["auto_fixes"] > 10:
            return "🟡 Many auto-fixes needed - consider shorter IDs"
        elif self.stats["success"] > 50:
            return "🟢 System working perfectly!"
        return "🔵 System learning and adapting..."

# Global instance
smart_sig = SmartSignature()