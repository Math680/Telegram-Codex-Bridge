#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install "python-telegram-bot==20.7"

mkdir -p logs

if [[ ! -f config.env ]]; then
  cp .env.example config.env
  if [[ -n "${HOME:-}" ]]; then
    sed -i "s#/home/youruser#${HOME}#g" config.env
  fi
  echo "Created config.env from .env.example. Please edit it before starting the service."
fi

chmod 600 config.env
chmod 700 logs
chmod 700 wrappers
chmod 700 wrappers/run_codex.sh

mkdir -p "$HOME/.config/systemd/user"
cp systemd/telegram-codex-bridge.service "$HOME/.config/systemd/user/telegram-codex-bridge.service"

systemctl --user daemon-reload
systemctl --user enable --now telegram-codex-bridge.service

./.venv/bin/python bot.py --self-test

echo "Install complete. Edit config.env, then restart: systemctl --user restart telegram-codex-bridge"
