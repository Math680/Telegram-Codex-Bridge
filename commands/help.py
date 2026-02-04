async def handle():
    return (
        "Commands:\n"
        "/ping - health check\n"
        "/help - this message\n"
        "/status - bot status\n"
        "/repos - list allowed workspaces\n"
        "/cd <alias> - switch workspace\n"
        "/ask <text> - ask Codex (runs in active workspace)\n"
        "/model [name] [low|medium|high|extra-high] - set model & reasoning\n"
        "/system [text|on|off|clear] - manage system prompt\n"
        "/permissions - show or set Codex permissions\n"
        "/new - reset session context"
    )
