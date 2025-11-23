"""
🔐 Plugin Manager v10.0 — Official 6 Integrations Only

Features:
- API validation for all plugins at startup
- Health checks with 2s timeout per plugin
- Strict error handling
- Only loads official (supported) plugins
"""

import importlib
import logging
import asyncio
import os
from typing import Dict, Any, Optional, List
from external.plugin_registry import (
    AVAILABLE_PLUGINS, 
    is_official_plugin,
    get_required_env,
    get_unsupported_error
)

logger = logging.getLogger("algogpt.plugin_manager")

class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, Any] = {}
        self.loaded = False
        self.health_status: Dict[str, Dict[str, Any]] = {}
    
    def load_all(self):
        """Load all OFFICIAL plugins with validation"""
        logger.info("🔐 Loading OFFICIAL plugins (v10.0)...")
        logger.info(f"📊 Found {len(AVAILABLE_PLUGINS)} official integrations")
        
        for name, cfg in AVAILABLE_PLUGINS.items():
            try:
                # ✅ 1. API Validation
                self._validate_api_config(name, cfg)
                
                # ✅ 2. Load plugin
                self._load_plugin(name, cfg)
                logger.info(f"✅ {name.upper()}: Loaded (api_type={cfg['api_type']})")
                
            except ValueError as e:
                logger.error(f"❌ {name.upper()}: {e}")
                self.health_status[name] = {"status": "failed", "error": str(e)}
            except Exception as e:
                logger.error(f"❌ {name.upper()}: Unexpected error: {e}")
                self.health_status[name] = {"status": "failed", "error": str(e)}
        
        self.loaded = True
        logger.info(f"✅ Total plugins loaded: {len(self.plugins)}")
        
        # ✅ 3. Run health checks
        asyncio.create_task(self._run_health_checks())
    
    def _validate_api_config(self, name: str, cfg: Dict[str, Any]):
        """✅ Validate API configuration"""
        # Check if official
        if not is_official_plugin(name):
            raise ValueError(f"❌ Not an official plugin: {name}")
        
        # Check required environment variables
        required_env = get_required_env(name)
        missing = [env for env in required_env if not os.getenv(env)]
        
        if missing:
            logger.warning(f"⚠️ {name}: Missing env vars: {', '.join(missing)}")
            if name not in ["tradingview"]:  # TV is optional
                raise ValueError(f"Missing required env: {', '.join(missing)}")
        
        logger.debug(f"✅ {name}: API config validated")
    
    def _load_plugin(self, name: str, cfg: Dict[str, Any]):
        """Load a single plugin"""
        module_path, class_name = cfg["client"].rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        
        # Initialize with config
        plugin_instance = cls(cfg)
        self.plugins[name] = plugin_instance
        self.health_status[name] = {"status": "loaded", "type": cfg["type"]}
    
    async def _run_health_checks(self):
        """🏥 Run health checks (2s timeout per plugin)"""
        logger.info("🏥 Running health checks on all plugins...")
        
        for name, plugin in self.plugins.items():
            try:
                cfg = AVAILABLE_PLUGINS.get(name, {})
                timeout_sec = cfg.get("timeout_sec", 2)
                
                # Get health check coroutine
                if hasattr(plugin, 'health_check'):
                    check_coro = plugin.health_check()
                    result = await asyncio.wait_for(check_coro, timeout=timeout_sec)
                    self.health_status[name]["health"] = result
                    logger.info(f"✅ {name}: Health OK")
                else:
                    logger.debug(f"⚠️ {name}: No health_check method")
                    
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ {name}: Health check TIMEOUT (>{timeout_sec}s)")
                self.health_status[name]["health"] = "timeout"
            except Exception as e:
                logger.error(f"❌ {name}: Health check failed: {e}")
                self.health_status[name]["health"] = f"error: {e}"
    
    def get(self, name: str) -> Optional[Any]:
        """Get plugin by name"""
        if name not in AVAILABLE_PLUGINS:
            logger.error(f"❌ Unsupported plugin: {name}")
            return None
        return self.plugins.get(name)
    
    def get_by_type(self, ptype: str) -> list:
        """Get all plugins of a type"""
        return [p for name, p in self.plugins.items() 
                if AVAILABLE_PLUGINS[name]["type"] == ptype]
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all plugins"""
        return {
            name: {
                "type": AVAILABLE_PLUGINS[name]["type"],
                "api_type": "official",
                "loaded": name in self.plugins,
                "health": self.health_status.get(name, {}),
                **({
                    "client_status": client.get_status()
                } if (client := self.plugins.get(name)) else {})
            }
            for name in AVAILABLE_PLUGINS.keys()
        }
    
    def set_mode(self, name: str, mode: str):
        """Set plugin mode (on, off, auto)"""
        # Validate plugin is official
        if not is_official_plugin(name):
            return {"error": f"Unsupported plugin: {name}"}
        
        plugin = self.get(name)
        if not plugin:
            return {"error": f"Plugin {name} not loaded"}
        
        if mode == "on":
            if hasattr(plugin, 'enable'):
                plugin.enable()
            return {"status": "enabled", "plugin": name}
        elif mode == "off":
            if hasattr(plugin, 'disable'):
                plugin.disable()
            return {"status": "disabled", "plugin": name}
        else:  # auto
            if hasattr(plugin, 'enable'):
                plugin.enable()
            return {"status": "auto", "plugin": name}
    
    def validate_plugin(self, name: str) -> bool:
        """Validate that a plugin is official and loaded"""
        if not is_official_plugin(name):
            logger.error(f"❌ Invalid plugin: {name}")
            return False
        
        if name not in self.plugins:
            logger.error(f"❌ Plugin not loaded: {name}")
            return False
        
        return True
