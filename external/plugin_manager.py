"""
Plugin Manager — Dynamic Loading & Lifecycle Management
"""
import importlib
import logging
from typing import Dict, Any, Optional
from external.plugin_registry import AVAILABLE_PLUGINS
from algo_core.capability_detector import detect_capabilities

logger = logging.getLogger("PluginManager")

class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, Any] = {}
        self.loaded = False
    
    def load_all(self):
        """Load all available plugins"""
        logger.info("Loading all plugins...")
        
        for name, cfg in AVAILABLE_PLUGINS.items():
            try:
                capabilities = detect_capabilities(name, cfg)
                self._load_plugin(name, cfg, capabilities)
                logger.info(f"✅ Loaded {name}")
            except Exception as e:
                logger.error(f"❌ Failed to load {name}: {e}")
        
        self.loaded = True
        logger.info(f"Total plugins loaded: {len(self.plugins)}")
    
    def _load_plugin(self, name: str, cfg: Dict[str, Any], capabilities: Dict[str, Any]):
        """Load a single plugin"""
        module_path, class_name = cfg["client"].rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        
        self.plugins[name] = cls(capabilities)
    
    def get(self, name: str) -> Optional[Any]:
        """Get plugin by name"""
        return self.plugins.get(name)
    
    def get_by_type(self, ptype: str) -> list:
        """Get all plugins of a type"""
        return [p for p in self.plugins.values() if p.ptype == ptype]
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all plugins"""
        return {
            name: client.get_status() 
            for name, client in self.plugins.items()
        }
    
    def set_mode(self, name: str, mode: str):
        """Set plugin mode (on, off, auto)"""
        plugin = self.get(name)
        if not plugin:
            return {"error": f"Plugin {name} not found"}
        
        if mode == "on":
            plugin.enable()
            return {"status": "enabled", "plugin": name}
        elif mode == "off":
            plugin.disable()
            return {"status": "disabled", "plugin": name}
        else:  # auto
            # Auto mode — plugin self-manages based on errors
            plugin.enable()
            return {"status": "auto", "plugin": name}
