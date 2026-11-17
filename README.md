# Telegram Codex Bridge

A self-hosted Python service that forwards Telegram requests to Codex CLI on a Linux machine. Telegram long polling avoids inbound webhooks. Telegram user IDs control who can use the bot, and workspace aliases select Codex's working directory.

**Request flow:** Telegram → [bot and command handlers](bot.py) → [Codex wrapper](wrappers/run_codex.sh) → reply to Telegram. The bot runs one command at a time and supports timeouts, session persistence, and rotating logs. A [systemd user service](systemd/telegram-codex-bridge.service) runs the bot in the background.

## Quick start

1. On Linux with systemd and Python 3 with `venv`, install Codex CLI and verify that `codex --version` and `codex login` work for the service user.
2. Create a Telegram bot through `@BotFather` and obtain the numeric Telegram user ID of each person you plan to authorize.
3. Clone the repository into the location expected by the bundled service:

   ```bash
   git clone https://github.com/Math680/Telegram-Codex-Bridge.git ~/telegram-codex-bridge
   cd ~/telegram-codex-bridge
   cp .env.example config.env
   chmod 600 config.env
   ```

4. Edit `config.env` before starting the service. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`, the absolute path to Codex in `CODEX_BIN`, and your workspace paths in `ALLOWED_DIRS_JSON`. Set `DEFAULT_DIR_ALIAS` to one of the configured aliases. Set `CODEX_SANDBOX=read-only` and `CODEX_BYPASS_APPROVALS=0` as standalone lines to start with the narrowest access.
5. Run `bash install.sh`, then try `/ping`, `/repos`, and `/ask List the top-level files` in Telegram.

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
- Grant Telegram access only to trusted users. Authorized users can send prompts to Codex and change its permission mode with `/permissions`.
- Workspace aliases restrict starting directories. The Codex sandbox controls actual filesystem access, and bypass mode disables that protection.
- Keep the bot token out of Git. Review the configured permissions before allowing write access.

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
[MIT](LICENSE).
