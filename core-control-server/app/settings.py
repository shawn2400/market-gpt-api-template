import os

class Settings:
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "CHANGE_ME")
    ROOT_WORKSPACE = "/home/runner/$REPL_SLUG/workspaces"
    AUDIT_LOG = "/home/runner/$REPL_SLUG/workspaces/_audit.log"

settings = Settings()
