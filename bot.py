import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

import commands.ping as cmd_ping
import commands.help as cmd_help
import commands.ask as cmd_ask
import commands.status as cmd_status

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
STATE_PATH = BASE_DIR / "state.json"
WRAPPER_PATH = BASE_DIR / "wrappers" / "run_codex.sh"

ALIAS_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
MAX_TELEGRAM_LEN = 3500
MAX_ASK_LEN = 4000
MAX_GENERIC_LEN = 512
MAX_MODEL_LEN = 64
MAX_SYSTEM_PROMPT_LEN = 2000
DEFAULT_CMD_TIMEOUT = 30


@dataclass
class AppState:
    allowed_user_ids: set
    allowed_dirs: dict
    default_alias: str
    selected_alias: str
    model: str
    reasoning: str
    sessions: dict
    system_prompt: str
    system_prompt_enabled: bool
    sandbox_mode: str
    bypass_approvals: bool
    ask_on_text: bool
    ask_ack_message: str
    lock: asyncio.Lock
    start_time: float


# --- Utilities ---

def sanitize_text(text: str) -> str:
    return CONTROL_RE.sub("", text or "").strip()


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


def send_chunks(text: str):
    if not text:
        return ["(no output)"]
    chunks = []
    while text:
        chunks.append(text[:MAX_TELEGRAM_LEN])
        text = text[MAX_TELEGRAM_LEN:]
    # Hard cap to avoid spamming if Codex goes wild
    max_parts = 8
    if len(chunks) > max_parts:
        chunks = chunks[:max_parts]
        chunks[-1] = chunks[-1].rstrip() + "\n...[truncated]"
    return chunks


def load_allowed_dirs() -> dict:
    raw = os.environ.get("ALLOWED_DIRS_JSON", "")
    if not raw:
        raise ValueError("ALLOWED_DIRS_JSON is required")
    data = json.loads(raw)
    if not isinstance(data, dict) or not data:
        raise ValueError("ALLOWED_DIRS_JSON must be a non-empty JSON object")

    allowed = {}
    for alias, path in data.items():
        if not isinstance(alias, str) or not ALIAS_RE.match(alias):
            raise ValueError(f"Invalid alias: {alias}")
        if not isinstance(path, str) or not path:
            raise ValueError(f"Invalid path for alias {alias}")
        resolved = str(Path(path).expanduser().resolve())
        allowed[alias] = resolved
    return allowed


def read_state() -> dict:
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}
    return {}


def save_state(state: AppState):
    tmp = STATE_PATH.with_suffix(".tmp")
    payload = {
        "selected_alias": state.selected_alias,
        "model": state.model,
        "reasoning": state.reasoning,
        "sessions": state.sessions,
        "system_prompt": state.system_prompt,
        "system_prompt_enabled": state.system_prompt_enabled,
        "sandbox_mode": state.sandbox_mode,
        "bypass_approvals": state.bypass_approvals,
    }
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, STATE_PATH)


def resolve_alias(alias: str, allowed: dict) -> str:
    path = allowed.get(alias)
    if not path:
        raise ValueError("Unknown alias")
    resolved = str(Path(path).resolve())
    if resolved != path:
        raise ValueError("Resolved path mismatch")
    return resolved


def is_allowed_user(update: Update, allowed_user_ids: set) -> bool:
    user = update.effective_user
    return bool(user and user.id in allowed_user_ids)


def get_args_text(update: Update) -> str:
    raw = update.message.text if update.message else ""
    parts = raw.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


async def guarded_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState, fn, timeout: int, cmd_name: str):
    if not is_allowed_user(update, state.allowed_user_ids):
        logging.warning("Unauthorized access attempt from user_id=%s", getattr(update.effective_user, "id", None))
        if update.message:
            await update.message.reply_text("Unauthorized.")
        return

    logging.info("Command received: %s user_id=%s", cmd_name, getattr(update.effective_user, "id", None))

    if state.lock.locked():
        if update.message:
            await update.message.reply_text("Busy. Try again.")
        return

    async with state.lock:
        try:
            result = await asyncio.wait_for(fn(update, context, state), timeout=timeout)
            if update.message and result is not None:
                for chunk in send_chunks(result):
                    await update.message.reply_text(chunk)
        except asyncio.TimeoutError:
            if update.message:
                await update.message.reply_text("Timed out. Please try again later.")
        except Exception:
            logging.exception("Command failed")
            if update.message:
                await update.message.reply_text("Error while processing command.")


# --- Command Implementations ---

async def cmd_ping_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    return await cmd_ping.handle()


async def cmd_help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    return await cmd_help.handle()


async def cmd_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    selected_path = resolve_alias(state.selected_alias, state.allowed_dirs)
    uptime = int(time.time() - state.start_time)
    info = {
        "selected_alias": state.selected_alias,
        "selected_path": selected_path,
        "uptime_seconds": uptime,
        "lock_busy": state.lock.locked(),
        "model": state.model,
        "reasoning": state.reasoning,
        "session": state.sessions.get(state.selected_alias, "none"),
        "system_prompt": "on" if state.system_prompt_enabled else "off",
        "sandbox_mode": state.sandbox_mode,
        "bypass_approvals": "bypass" if state.bypass_approvals else "on-request",
    }
    return await cmd_status.handle(info)


async def cmd_repos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    lines = ["Allowed workspaces:"]
    for alias, path in sorted(state.allowed_dirs.items()):
        mark = "*" if alias == state.selected_alias else " "
        lines.append(f"{mark} {alias} -> {path}")
    lines.append("Use /cd <alias> to switch.")
    return "\n".join(lines)


async def cmd_cd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    raw = sanitize_text(get_args_text(update))
    if len(raw) > MAX_GENERIC_LEN:
        return "Alias too long."
    alias = raw
    if not alias:
        return "Usage: /cd <alias>"
    if not ALIAS_RE.match(alias):
        return "Invalid alias format. Use letters, numbers, _ or - (max 32)."
    if alias not in state.allowed_dirs:
        return "Unknown alias. Use /repos to list allowed workspaces."

    path = resolve_alias(alias, state.allowed_dirs)
    p = Path(path)
    if not p.exists():
        return f"Path does not exist: {path}"
    if not p.is_dir():
        return f"Path is not a directory: {path}"

    state.selected_alias = alias
    save_state(state)
    return f"Selected: {alias} -> {path}"


async def cmd_model_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    raw = sanitize_text(get_args_text(update))
    if not raw:
        return (
            "Current model: {m} (reasoning: {r})\n"
            "Usage: /model <name> [low|medium|high|extra-high]"
        ).format(m=state.model, r=state.reasoning)

    parts = raw.split()
    model = parts[0].strip()
    if len(model) > MAX_MODEL_LEN or not re.match(r"^[a-zA-Z0-9._:-]+$", model):
        return "Invalid model name."

    reasoning = state.reasoning
    if len(parts) >= 2:
        level = parts[1].strip().lower()
        allowed = {"low", "medium", "high", "extra-high"}
        if level not in allowed:
            return "Invalid reasoning level. Use: low|medium|high|extra-high"
        reasoning = level

    state.model = model
    state.reasoning = reasoning
    save_state(state)
    return f"Model set: {state.model} (reasoning: {state.reasoning})"


async def cmd_system_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    raw = sanitize_text(get_args_text(update))
    if not raw:
        status = "ON" if state.system_prompt_enabled else "OFF"
        return f"System prompt: {status}. Usage: /system <text> | /system on | /system off | /system clear"

    lowered = raw.lower()
    if lowered == "off":
        state.system_prompt_enabled = False
        save_state(state)
        return "System prompt disabled."
    if lowered == "on":
        if not state.system_prompt:
            return "No system prompt set. Use /system <text> first."
        state.system_prompt_enabled = True
        save_state(state)
        return "System prompt enabled."
    if lowered == "clear":
        state.system_prompt = ""
        state.system_prompt_enabled = False
        save_state(state)
        return "System prompt cleared."

    if len(raw) > MAX_SYSTEM_PROMPT_LEN:
        return f"System prompt too long (max {MAX_SYSTEM_PROMPT_LEN} chars)."

    state.system_prompt = raw
    state.system_prompt_enabled = True
    save_state(state)
    return "System prompt updated."


async def cmd_permissions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    raw = sanitize_text(get_args_text(update))
    if not raw:
        return (
            "Permissions:\n"
            f"sandbox: {state.sandbox_mode}\n"
            f"approvals: {'bypass' if state.bypass_approvals else 'on-request'}\n"
            "Usage: /permissions sandbox <read-only|workspace-write|danger-full-access>\n"
            "       /permissions approvals <on|off>"
        )

    parts = raw.split()
    if len(parts) != 2:
        return "Usage: /permissions sandbox <mode> | /permissions approvals <on|off>"

    category, value = parts[0].lower(), parts[1].lower()
    if category == "sandbox":
        allowed = {"read-only", "workspace-write", "danger-full-access"}
        if value not in allowed:
            return "Invalid sandbox. Use: read-only|workspace-write|danger-full-access"
        state.sandbox_mode = value
        save_state(state)
        return f"Sandbox set: {state.sandbox_mode}"

    if category == "approvals":
        if value not in {"on", "off"}:
            return "Invalid approvals value. Use: on|off"
        state.bypass_approvals = (value == "off")
        save_state(state)
        return f"Approvals: {'bypass' if state.bypass_approvals else 'on-request'}"

    return "Usage: /permissions sandbox <mode> | /permissions approvals <on|off>"


async def cmd_ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    raw = sanitize_text(get_args_text(update))
    if not raw:
        return "Usage: /ask <text>"
    if len(raw) > MAX_ASK_LEN:
        return f"Text too long (max {MAX_ASK_LEN} chars)."

    if state.system_prompt_enabled and state.system_prompt:
        text = f"{state.system_prompt}\n\nUser request:\n{raw}"
    else:
        text = raw

    selected_path = resolve_alias(state.selected_alias, state.allowed_dirs)
    p = Path(selected_path)
    if not p.exists() or not p.is_dir():
        return f"Invalid workspace path: {selected_path}"

    codex_timeout = int(os.environ.get("CODEX_TIMEOUT", "120"))

    env = os.environ.copy()
    env["CODEX_CWD"] = selected_path
    env["CODEX_MODEL"] = state.model
    env["CODEX_REASONING"] = state.reasoning
    env["CODEX_SANDBOX"] = state.sandbox_mode
    env["CODEX_BYPASS_APPROVALS"] = "1" if state.bypass_approvals else "0"
    if state.sessions.get(state.selected_alias):
        env["CODEX_SESSION_ID"] = state.sessions[state.selected_alias]
    # Avoid leaking secrets in logs
    logging.info("/ask invoked (len=%d) cwd=%s", len(text), selected_path)

    if state.ask_ack_message and update.message:
        await update.message.reply_text(state.ask_ack_message)

    if not WRAPPER_PATH.exists() or not os.access(WRAPPER_PATH, os.X_OK):
        return f"Wrapper not executable: {WRAPPER_PATH}"

    session_file = tempfile.NamedTemporaryFile(delete=False)
    session_file.close()
    env["CODEX_SESSION_FILE"] = session_file.name
    try:
        proc = cmd_ask.run(
            prompt=text,
            wrapper_path=str(WRAPPER_PATH),
            cwd=selected_path,
            timeout=codex_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Codex timed out after {codex_timeout}s."
    finally:
        try:
            if os.path.exists(session_file.name):
                with open(session_file.name, "r") as f:
                    new_session = f.read().strip()
                if new_session:
                    state.sessions[state.selected_alias] = new_session
                    save_state(state)
                os.unlink(session_file.name)
        except OSError:
            pass

    output = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if not output and err:
        output = err
    if proc.returncode != 0:
        output = (output or "") + f"\n(Exited with code {proc.returncode})"

    return output or "(no output)"


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    return "Unknown command. Use /help."


async def cmd_new_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, state: AppState):
    if state.selected_alias in state.sessions:
        del state.sessions[state.selected_alias]
        save_state(state)
        return "Session reset."
    return "No session to reset."


async def handler_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_ping_handler, DEFAULT_CMD_TIMEOUT, "ping")


async def handler_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_help_handler, DEFAULT_CMD_TIMEOUT, "help")


async def handler_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_status_handler, DEFAULT_CMD_TIMEOUT, "status")


async def handler_repos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_repos_handler, DEFAULT_CMD_TIMEOUT, "repos")


async def handler_cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_cd_handler, DEFAULT_CMD_TIMEOUT, "cd")


async def handler_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_model_handler, DEFAULT_CMD_TIMEOUT, "model")


async def handler_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_new_handler, DEFAULT_CMD_TIMEOUT, "new")


async def handler_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_system_handler, DEFAULT_CMD_TIMEOUT, "system")


async def handler_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_permissions_handler, DEFAULT_CMD_TIMEOUT, "permissions")


async def handler_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_ask_handler, int(os.environ.get("CODEX_TIMEOUT", "120")), "ask")


async def handler_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_unknown, DEFAULT_CMD_TIMEOUT, "unknown")


async def handler_text_as_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.application.bot_data["state"]
    await guarded_handler(update, context, state, cmd_ask_handler, int(os.environ.get("CODEX_TIMEOUT", "120")), "ask_text")


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "telegram-codex.log"
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main():
    setup_logging()

    if "--self-test" in sys.argv:
        try:
            allowed_dirs = load_allowed_dirs()
        except Exception as exc:
            print(f"Self-test failed: invalid ALLOWED_DIRS_JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        default_alias = os.environ.get("DEFAULT_DIR_ALIAS", "").strip()
        if default_alias not in allowed_dirs:
            print("Self-test failed: DEFAULT_DIR_ALIAS must exist in ALLOWED_DIRS_JSON", file=sys.stderr)
            sys.exit(1)
        if not os.environ.get("TELEGRAM_BOT_TOKEN"):
            print("Self-test warning: TELEGRAM_BOT_TOKEN missing (set later).")
        print("Self-test OK.")
        sys.exit(0)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Missing TELEGRAM_BOT_TOKEN in environment.", file=sys.stderr)
        sys.exit(1)

    allowed_ids = set()
    raw_allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
    if raw_allowed:
        for part in raw_allowed.split(","):
            part = part.strip()
            if part:
                try:
                    allowed_ids.add(int(part))
                except ValueError:
                    print("TELEGRAM_ALLOWED_USERS must be comma-separated integers", file=sys.stderr)
                    sys.exit(1)
    else:
        raw_user = os.environ.get("TELEGRAM_USER_ID", "").strip()
        if not raw_user:
            print("Missing TELEGRAM_USER_ID (or TELEGRAM_ALLOWED_USERS)", file=sys.stderr)
            sys.exit(1)
        try:
            allowed_ids.add(int(raw_user))
        except ValueError:
            print("TELEGRAM_USER_ID must be an integer", file=sys.stderr)
            sys.exit(1)

    try:
        allowed_dirs = load_allowed_dirs()
    except Exception as exc:
        print(f"Invalid ALLOWED_DIRS_JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    default_alias = os.environ.get("DEFAULT_DIR_ALIAS", "").strip()
    if default_alias not in allowed_dirs:
        print("DEFAULT_DIR_ALIAS must exist in ALLOWED_DIRS_JSON", file=sys.stderr)
        sys.exit(1)

    state_data = read_state()
    selected_alias = state_data.get("selected_alias", default_alias)
    if selected_alias not in allowed_dirs:
        selected_alias = default_alias

    default_model = os.environ.get("DEFAULT_CODEX_MODEL", "gpt-5.2-codex").strip()
    default_reasoning = os.environ.get("DEFAULT_CODEX_REASONING", "medium").strip().lower()
    model = state_data.get("model", default_model)
    reasoning = state_data.get("reasoning", default_reasoning)

    sessions = state_data.get("sessions", {}) if isinstance(state_data.get("sessions"), dict) else {}

    system_prompt = state_data.get("system_prompt", os.environ.get("SYSTEM_PROMPT", "").strip())
    system_prompt_enabled = state_data.get("system_prompt_enabled")
    if system_prompt_enabled is None:
        system_prompt_enabled = parse_bool(os.environ.get("SYSTEM_PROMPT_ENABLED", "0"), False)
    if not system_prompt:
        system_prompt_enabled = False

    sandbox_mode = state_data.get("sandbox_mode", os.environ.get("CODEX_SANDBOX", "workspace-write"))
    if sandbox_mode not in {"read-only", "workspace-write", "danger-full-access"}:
        sandbox_mode = "workspace-write"

    bypass_approvals = state_data.get("bypass_approvals")
    if bypass_approvals is None:
        bypass_approvals = parse_bool(os.environ.get("CODEX_BYPASS_APPROVALS", "0"), False)

    ask_on_text = parse_bool(os.environ.get("ASK_ON_TEXT", "0"), False)
    ask_ack_message = os.environ.get("ASK_ACK_MESSAGE", "").strip()

    state = AppState(
        allowed_user_ids=allowed_ids,
        allowed_dirs=allowed_dirs,
        default_alias=default_alias,
        selected_alias=selected_alias,
        model=model,
        reasoning=reasoning,
        sessions=sessions,
        system_prompt=system_prompt,
        system_prompt_enabled=system_prompt_enabled,
        sandbox_mode=sandbox_mode,
        bypass_approvals=bypass_approvals,
        ask_on_text=ask_on_text,
        ask_ack_message=ask_ack_message,
        lock=asyncio.Lock(),
        start_time=time.time(),
    )

    app = ApplicationBuilder().token(token).build()
    app.bot_data["state"] = state

    app.add_handler(CommandHandler("ping", handler_ping))
    app.add_handler(CommandHandler("help", handler_help))
    app.add_handler(CommandHandler("status", handler_status))
    app.add_handler(CommandHandler("repos", handler_repos))
    app.add_handler(CommandHandler("cd", handler_cd))
    app.add_handler(CommandHandler("ask", handler_ask))
    app.add_handler(CommandHandler("model", handler_model))
    app.add_handler(CommandHandler("new", handler_new))
    app.add_handler(CommandHandler("system", handler_system))
    app.add_handler(CommandHandler("permissions", handler_permissions))

    if state.ask_on_text:
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler_text_as_ask))

    app.add_handler(MessageHandler(filters.COMMAND, handler_unknown))

    logging.info("Bot starting")
    app.run_polling()


if __name__ == "__main__":
    main()
