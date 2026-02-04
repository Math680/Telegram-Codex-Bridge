# Telegram Codex Bridge

A secure, self‑hosted **Telegram → Codex CLI** bridge that runs locally on your VPS. It uses **long polling** (no webhooks, no inbound ports), enforces **user allowlists**, and restricts work to **approved directories only**.

If you want a private Codex assistant you can message from Telegram, this is it.

## Why this exists
- **Private**: runs on your machine, your files, your model choices.
- **Safe by default**: only allows whitelisted users and directories.
- **Reliable**: systemd service, logging, timeouts, and a global lock.

## Features
- Telegram long polling (no inbound ports)
- Allowlist by Telegram user ID(s)
- Directory allowlist by alias (no raw paths from Telegram)
- Global lock (one command at a time)
- Per‑command timeouts
- Session persistence (keeps context across messages)
- Optional system prompt
- Configurable Codex sandbox/approvals
- Structured logs with rotation

---

## Quick Start (A → Z)

### 1) Create a Telegram bot (phone)
1. Open Telegram and search **@BotFather**
2. Send `/newbot`, choose a name + username
3. Copy the **bot token**

### 2) Get your numeric user_id (phone)
Use either bot:
- **@userinfobot** → `/start`
- **@getmyid_bot** → `/start`

### 3) Install Codex CLI (server)
Make sure the Codex CLI is installed and works:
```bash
codex --version
codex login
```

### 4) Install the bridge (server)
```bash
git clone https://github.com/<you>/telegram-codex-bridge.git ~/telegram-codex-bridge
cd ~/telegram-codex-bridge
./install.sh
```

### 5) Configure environment (server)
Edit `~/telegram-codex-bridge/config.env`:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_USER_ID=123456789
CODEX_BIN=/usr/bin/codex
ALLOWED_DIRS_JSON={"app":"/home/you/projects/my-app"}
DEFAULT_DIR_ALIAS=app
```

Then restart:
```bash
systemctl --user restart telegram-codex-bridge
```

### 6) Start chatting (Telegram)
Open your bot and try:
- `/ping`
- `/ask hello`

---

## Configuration Reference

All configuration lives in `config.env`.

### Telegram
- `TELEGRAM_BOT_TOKEN` **(required)**
- `TELEGRAM_USER_ID` **(required)** single user
- `TELEGRAM_ALLOWED_USERS` optional comma‑separated list (overrides `TELEGRAM_USER_ID`)

### Workspace allowlist
- `ALLOWED_DIRS_JSON` **(required)**
  - Example: `{"app":"/home/you/projects/my-app","docs":"/home/you/docs"}`
- `DEFAULT_DIR_ALIAS` **(required)**

### Codex CLI
- `CODEX_BIN` (default: `/usr/bin/codex`)
- `CODEX_TIMEOUT` (seconds, default `120`)
- `DEFAULT_CODEX_MODEL` (default `gpt-5.2-codex`)
- `DEFAULT_CODEX_REASONING` (default `medium`)

### Permissions (important)
- `CODEX_SANDBOX`: `read-only` | `workspace-write` | `danger-full-access`
- `CODEX_BYPASS_APPROVALS`: `0` or `1`
  - If `1`, the CLI uses `--dangerously-bypass-approvals-and-sandbox`.
  - This **disables sandboxing**, so use only if you trust the environment.

### Behavior
- `ASK_ON_TEXT`: `1` to treat any normal message as `/ask`
- `ASK_ACK_MESSAGE`: optional message sent immediately after an `/ask`
- `SYSTEM_PROMPT`: default system prompt
- `SYSTEM_PROMPT_ENABLED`: `1` to enable by default

---

## Commands (Telegram)
- `/ping` → health check
- `/help` → list commands
- `/status` → bot status, model, session, permissions
- `/repos` → list allowed workspaces
- `/cd <alias>` → switch workspace
- `/ask <text>` → run Codex in active workspace
- `/model <name> [low|medium|high|extra-high]` → set model & reasoning
- `/system <text|on|off|clear>` → manage system prompt
- `/permissions` → show or set sandbox/approval behavior
- `/new` → reset session context

---

## Security Notes
- Only allowlisted users can use the bot.
- Only allowlisted directories are accessible.
- No raw filesystem paths are accepted.
- No shell commands are exposed via Telegram.

---

## Logs
- `~/telegram-codex-bridge/logs/telegram-codex.log`
- Log rotation is enabled.

---

## Troubleshooting
- Service status:
  ```bash
  systemctl --user status telegram-codex-bridge
  ```
- Logs:
  ```bash
  tail -f ~/telegram-codex-bridge/logs/telegram-codex.log
  ```

---

## License
MIT
