async def handle(info: dict):
    return (
        "Status:\n"
        f"Workspace: {info.get('selected_alias')}\n"
        f"Path: {info.get('selected_path')}\n"
        f"Uptime: {info.get('uptime_seconds')}s\n"
        f"Model: {info.get('model')} ({info.get('reasoning')})\n"
        f"Session: {info.get('session')}\n"
        f"System prompt: {info.get('system_prompt')}\n"
        f"Sandbox: {info.get('sandbox_mode')}\n"
        f"Approvals: {info.get('bypass_approvals')}\n"
        f"Busy: {info.get('lock_busy')}"
    )
