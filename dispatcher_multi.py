#!/usr/bin/env python3
"""
Multi-machine dispatcher: one bot token shared across all desktops.
Each machine has a prefix and only responds to its messages.

Workflow:
  proj                        → all machines show their project picker
  mac proj                    → only Mac responds
  mac claude: fix the bug     → only Mac runs Claude
  mac gh push                 → only Mac pushes (with Claude commit msg)
  all status                  → all machines respond

Commands (optional machine prefix: win/mac/linux/all):
  proj                            — pick active project directory
  claude: <prompt>                — run Claude Code in active project
  cursor: <prompt>                — run Cursor in active project
  gh pull / push / reset          — git operations (authenticated)
  gh init <url>                   — git init + set remote origin
  mkdir: <name> [--public|--private]
  status

.env (next to this script):
  GITHUB_TOKEN=ghp_...
  GITHUB_EMAIL=you@example.com
  GITHUB_NAME=Your Name

Config: add "machine_prefix": "mac" (or "win", "linux") to config.json
"""

import asyncio
import json
import logging
import os
import platform
import re
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
ENV_PATH    = Path(__file__).parent / ".env"


def load_config():
    if not CONFIG_PATH.exists():
        print(f"ERROR: {CONFIG_PATH} not found.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_env_file() -> dict:
    result = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip('"').strip("'")
    return result


CFG              = load_config()
TELEGRAM_TOKEN   = CFG["telegram_bot_token"]
ALLOWED_CHAT_IDS = set(CFG.get("allowed_chat_ids", []))
MACHINE_NAME     = CFG.get("machine_name", platform.node())
MACHINE_PREFIX   = CFG.get("machine_prefix", "").lower()
WORK_DIR         = Path(CFG.get("default_work_dir", str(Path.home())))
MAX_OUTPUT_LEN   = CFG.get("max_output_length", 3500)

_ENV             = load_env_file()
GITHUB_TOKEN     = _ENV.get("GITHUB_TOKEN", "")
GITHUB_EMAIL     = _ENV.get("GITHUB_EMAIL", "")
GITHUB_NAME      = _ENV.get("GITHUB_NAME", GITHUB_EMAIL.split("@")[0] if GITHUB_EMAIL else "bot")

logging.basicConfig(level=logging.INFO,
                    format=f"[{MACHINE_NAME}] %(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Per-chat state (isolated per machine process)
active_dirs: dict = {}
pending:     dict = {}

ALIASES  = {"cc": "claude", "cur": "cursor", "github": "gh", "p": "proj"}
PREFIXES = {"win", "windows", "mac", "macbook", "linux", "lnx", "all"}

# Prefix callback_data with machine name so each machine only handles its own buttons
_CB = f"{MACHINE_PREFIX}_" if MACHINE_PREFIX else ""

# ---------------------------------------------------------------------------
# Git auth via GIT_ASKPASS helper script
# ---------------------------------------------------------------------------

def _make_askpass():
    if not GITHUB_TOKEN:
        return None
    try:
        fd, path = tempfile.mkstemp(suffix=".sh", prefix="git_askpass_")
        with os.fdopen(fd, "w") as f:
            f.write('#!/bin/sh\n'
                    'case "$1" in\n'
                    '  *Username*) echo "$_GIT_USER" ;;\n'
                    '  *)          echo "$_GIT_PASS" ;;\n'
                    'esac\n')
        os.chmod(path, stat.S_IRWXU)
        return path
    except Exception as e:
        log.warning(f"Could not create askpass script: {e}")
        return None


ASKPASS = _make_askpass()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def list_subdirs() -> list:
    try:
        return sorted(d.name for d in WORK_DIR.iterdir()
                      if d.is_dir() and not d.name.startswith("."))
    except Exception:
        return []


def parse_message(text: str):
    """Returns (is_for_me, cmd, args). Strips machine prefix if present."""
    text = text.strip()
    if not text:
        return True, "", ""

    words = text.split(None, 1)
    first = words[0].lower().rstrip(":")
    rest  = words[1].strip() if len(words) > 1 else ""

    is_for_me = True
    if first in PREFIXES:
        is_for_me = (first == "all") or (
            bool(MACHINE_PREFIX) and first.startswith(MACHINE_PREFIX[:3]))
        if rest:
            w2    = rest.split(None, 1)
            first = w2[0].lower().rstrip(":")
            rest  = w2[1].strip() if len(w2) > 1 else ""
        else:
            return is_for_me, "", ""

    cmd = ALIASES.get(first, first)
    return is_for_me, cmd, rest


def truncate(text: str) -> str:
    return text[:MAX_OUTPUT_LEN] + "\n… (truncated)" if len(text) > MAX_OUTPUT_LEN else text


def git_id_flags() -> list:
    if GITHUB_EMAIL:
        return ["-c", f"user.email={GITHUB_EMAIL}", "-c", f"user.name={GITHUB_NAME}"]
    return []


async def _git(cmd: list, work_dir: str, timeout: int = 60, env=None) -> str:
    # GIT_CEILING_DIRECTORIES stops git traversing above work_dir to find a .git
    _env = {**(env if env is not None else os.environ),
            "GIT_CEILING_DIRECTORIES": str(Path(work_dir).parent)}
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=work_dir, env=_env)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            return (f"{out}\n{err}" if out else err) or f"[exit {proc.returncode}]"
        return out or "(done)"
    except asyncio.TimeoutError: return f"⏱ timed out ({timeout}s)"
    except FileNotFoundError:    return "❌ `git` not found"
    except Exception as e:       return f"❌ {e}"


async def _git_auth(cmd: list, work_dir: str, timeout: int = 60) -> str:
    if not ASKPASS or not GITHUB_TOKEN:
        return await _git(cmd, work_dir, timeout)
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS":         ASKPASS,
        "_GIT_USER":           GITHUB_EMAIL,
        "_GIT_PASS":           GITHUB_TOKEN,
    }
    return await _git(cmd, work_dir, timeout, env=env)


async def fetch_recent_commits(work_dir: str, n: int = 8) -> list:
    out = await _git(["git", "log", "--pretty=format:%h|%s", f"-{n}"], work_dir)
    commits = []
    for line in out.splitlines():
        if "|" in line:
            h, msg = line.split("|", 1)
            commits.append({"hash": h.strip(), "msg": msg.strip()[:50]})
    return commits


async def generate_commit_message(diff: str) -> str:
    prompt = (
        "Write a concise git commit message (one line, max 72 chars) summarising "
        "these changes. Output ONLY the commit message — no quotes, no explanation.\n\n"
        + diff[:4000]
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt, "--output-format", "text",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        msg = stdout.decode(errors="replace").strip().strip('"').strip("'")
        return msg or f"Update {datetime.now():%Y-%m-%d %H:%M}"
    except Exception:
        return f"Update {datetime.now():%Y-%m-%d %H:%M}"

# ---------------------------------------------------------------------------
# Agent runners
# ---------------------------------------------------------------------------

async def run_claude(prompt: str, work_dir: str) -> str:
    cmd = ["claude", "-p", prompt, "--output-format", "text",
           "--allowedTools", "Bash", "Read", "Write", "Edit"]
    log.info(f"Claude in {work_dir}: {prompt[:60]}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=work_dir)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        out = stdout.decode(errors="replace").strip()
        return out or f"[exit {proc.returncode}] {stderr.decode(errors='replace').strip()}"
    except asyncio.TimeoutError: return "⏱ Claude timed out (5m)"
    except FileNotFoundError:    return "❌ `claude` not found"
    except Exception as e:       return f"❌ {e}"


async def run_cursor(prompt: str, work_dir: str) -> str:
    cmd = ["agent", "chat", "--yolo", prompt]
    log.info(f"Cursor in {work_dir}: {prompt[:60]}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=work_dir)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        out = stdout.decode(errors="replace").strip()
        return out or f"[exit {proc.returncode}] {stderr.decode(errors='replace').strip()}"
    except asyncio.TimeoutError: return "⏱ Cursor timed out (5m)"
    except FileNotFoundError:    return "❌ `agent` (Cursor CLI) not found"
    except Exception as e:       return f"❌ {e}"


async def run_gh(subcmd: str, work_dir: str) -> str:
    parts = subcmd.split(None, 1)
    op  = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    if op == "pull":
        return await _git_auth(["git", "pull"], work_dir)

    if op == "push":
        status = await _git(["git", "status", "--porcelain"], work_dir)
        if not status.strip():
            return "Nothing to commit — working tree clean."

        await _git(["git", "add", "-A"], work_dir)

        diff, stat = await asyncio.gather(
            _git(["git", "diff", "--staged"],           work_dir),
            _git(["git", "diff", "--staged", "--stat"], work_dir),
        )

        msg = await generate_commit_message(diff)
        await _git(["git"] + git_id_flags() + ["commit", "-m", msg], work_dir)
        push = await _git_auth(["git", "push", "-u", "origin", "HEAD"], work_dir)

        lines = [f"📝 _{msg}_", stat, push]
        return "\n\n".join(l for l in lines if l and l != "(done)")

    if op == "reset" and arg:
        return await _git(["git", "reset", "--hard", arg], work_dir)

    return f"❌ Unknown: `{op}`. Use: pull · push · reset · init <url>"


async def run_gh_init(url: str, work_dir: str) -> str:
    parts = []

    gitdir = await _git(["git", "rev-parse", "--git-dir"], work_dir)
    if gitdir.startswith("❌") or "fatal" in gitdir:
        await _git(["git", "init"], work_dir)
        parts.append("Initialised git repo")
    else:
        parts.append("Already a git repo")

    if GITHUB_EMAIL:
        await _git(["git", "config", "user.email", GITHUB_EMAIL], work_dir)
        await _git(["git", "config", "user.name",  GITHUB_NAME],  work_dir)
        parts.append(f"Identity: {GITHUB_EMAIL}")

    remotes = (await _git(["git", "remote"], work_dir)).splitlines()
    verb = "set-url" if "origin" in remotes else "add"
    await _git(["git", "remote", verb, "origin", url], work_dir)
    parts.append(f"Remote origin → {url}")

    return "✅ " + "\n".join(parts)


async def run_mkdir(args: str, work_dir: str) -> str:
    parts = args.strip().split()
    if not parts:
        return "❌ Usage: `mkdir: <name> [--public|--private]`"
    name  = parts[0]
    flags = parts[1:]
    if not re.match(r'^[\w.\-]+$', name):
        return f"❌ Invalid name: `{name}`"
    new_dir = Path(work_dir) / name
    try:
        new_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return f"❌ Already exists: `{new_dir}`"
    except Exception as e:
        return f"❌ {e}"

    visibility = ("--public"  if "--public"  in flags else
                  "--private" if "--private" in flags else None)
    if not visibility:
        return f"✅ Created `{new_dir}`"

    (new_dir / "README.md").write_text(f"# {name}\n")
    for cmd in (["git", "init"],
                ["git"] + git_id_flags() + ["add", "README.md"],
                ["git"] + git_id_flags() + ["commit", "-m", "Initial commit"]):
        await _git(cmd, str(new_dir))

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "repo", "create", name, visibility,
            "--source=.", "--remote=origin", "--push",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(new_dir))
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            return f"✅ Dir + git init done\n❌ `gh repo create` failed:\n{err or out}"
        return f"✅ `{name}` created + GitHub repo ({visibility[2:]})\n{out}"
    except asyncio.TimeoutError: return "✅ Dir created, `gh repo create` timed out"
    except FileNotFoundError:    return "✅ Dir + git init done (`gh` CLI not found)"
    except Exception as e:       return f"✅ Dir created, `gh repo create` failed: {e}"

# ---------------------------------------------------------------------------
# Telegram bot
# ---------------------------------------------------------------------------

async def main():
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (Application, MessageHandler, CallbackQueryHandler,
                               filters, ContextTypes)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    def authorized(update: Update) -> bool:
        return not ALLOWED_CHAT_IDS or update.effective_chat.id in ALLOWED_CHAT_IDS

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if not authorized(update):
            await update.message.reply_text(
                f"⛔ Unauthorized. Chat ID: `{chat_id}`", parse_mode="Markdown")
            return

        text = (update.message.text or "").strip()

        # ── Intercept pending "init" waiting for a URL ──────────────────────
        p = pending.get(chat_id, {})
        if p.get("type") == "init":
            url = text
            pending.pop(chat_id)
            if url.startswith("http"):
                ack = await update.message.reply_text(
                    f"⏳ *{MACHINE_NAME}* initialising…", parse_mode="Markdown")
                result = await run_gh_init(url, p["work_dir"])
                await ack.edit_text(result)
            else:
                await update.message.reply_text("❌ Doesn't look like a URL. Run `gh init` again.")
            return

        is_for_me, cmd, args = parse_message(text)
        if not is_for_me:
            return

        if cmd == "status":
            wd   = active_dirs.get(chat_id)
            proj = f"`{Path(wd).name}`" if wd else "_(none)_"
            auth = f"`{GITHUB_EMAIL}`" if GITHUB_EMAIL else "_(not configured)_"
            subdirs = list_subdirs()
            await update.message.reply_text(
                f"🖥 *{MACHINE_NAME}*  {platform.system()}\n"
                f"📂 `{WORK_DIR}`  ({len(subdirs)} projects)\n"
                f"📌 Active: {proj}\n"
                f"🔑 GitHub: {auth}\n"
                f"⏰ {datetime.now():%H:%M:%S}",
                parse_mode="Markdown")
            return

        if cmd == "proj":
            subdirs = list_subdirs()
            if not subdirs:
                await update.message.reply_text(
                    f"No subdirectories in `{WORK_DIR}`.", parse_mode="Markdown")
                return
            pending[chat_id] = {"type": "proj", "subdirs": subdirs}
            rows = ([[InlineKeyboardButton(
                         f"/ {WORK_DIR.name}/ (root)", callback_data=f"{_CB}proj:0")]] +
                    [[InlineKeyboardButton(f"📁 {d}", callback_data=f"{_CB}proj:{i+1}")]
                     for i, d in enumerate(subdirs)])
            await update.message.reply_text(
                f"📂 *{MACHINE_NAME}* — select project:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows))
            return

        wd = active_dirs.get(chat_id)
        if cmd in ("claude", "cursor", "gh") and not wd:
            await update.message.reply_text(
                "📂 No active project. Send `proj` to pick one.", parse_mode="Markdown")
            return

        if cmd == "claude":
            if not args:
                await update.message.reply_text("Usage: `claude: <prompt>`", parse_mode="Markdown")
                return
            ack = await update.message.reply_text(
                f"⏳ *{MACHINE_NAME}* — Claude in `{Path(wd).name}`…", parse_mode="Markdown")
            result = truncate(await run_claude(args, wd))
            try:
                await ack.edit_text(
                    f"✅ *{MACHINE_NAME}* — Claude (`{Path(wd).name}`)\n\n{result}",
                    parse_mode="Markdown")
            except Exception:
                await ack.edit_text(f"✅ {MACHINE_NAME} — Claude\n\n{result}")
            return

        if cmd == "cursor":
            if not args:
                await update.message.reply_text("Usage: `cursor: <prompt>`", parse_mode="Markdown")
                return
            ack = await update.message.reply_text(
                f"⏳ *{MACHINE_NAME}* — Cursor in `{Path(wd).name}`…", parse_mode="Markdown")
            result = truncate(await run_cursor(args, wd))
            try:
                await ack.edit_text(
                    f"✅ *{MACHINE_NAME}* — Cursor (`{Path(wd).name}`)\n\n{result}",
                    parse_mode="Markdown")
            except Exception:
                await ack.edit_text(f"✅ {MACHINE_NAME} — Cursor\n\n{result}")
            return

        if cmd == "gh":
            op = args.split()[0].lower() if args.split() else ""

            if op == "init":
                url = args.split(None, 1)[1].strip() if len(args.split(None, 1)) > 1 else ""
                if url:
                    ack = await update.message.reply_text(
                        f"⏳ *{MACHINE_NAME}* initialising…", parse_mode="Markdown")
                    result = await run_gh_init(url, wd)
                    await ack.edit_text(result)
                else:
                    pending[chat_id] = {"type": "init", "work_dir": wd}
                    await update.message.reply_text(
                        f"🔗 *{MACHINE_NAME}* — paste your GitHub repo URL:\n"
                        "_(e.g. `https://github.com/you/repo.git`)_",
                        parse_mode="Markdown")
                return

            if op == "reset" and not args.split()[1:]:
                commits = await fetch_recent_commits(wd)
                if not commits:
                    await update.message.reply_text("No commits found in this repo.")
                    return
                pending[chat_id] = {"type": "reset", "work_dir": wd, "commits": commits}
                rows = [[InlineKeyboardButton(
                            f"{c['hash']} — {c['msg']}", callback_data=f"{_CB}reset:{i}")]
                        for i, c in enumerate(commits)]
                await update.message.reply_text(
                    f"↩️ *{MACHINE_NAME}* — reset to which commit?",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(rows))
                return

            label = f"gh {op}" if op else "gh"
            ack = await update.message.reply_text(
                f"⏳ *{MACHINE_NAME}* — {label} in `{Path(wd).name}`…", parse_mode="Markdown")
            result = truncate(await run_gh(args, wd))
            try:
                await ack.edit_text(
                    f"✅ *{MACHINE_NAME}* — {label} (`{Path(wd).name}`)\n\n{result}",
                    parse_mode="Markdown")
            except Exception:
                await ack.edit_text(f"✅ {MACHINE_NAME} — {label}\n\n{result}")
            return

        if cmd == "mkdir":
            ack = await update.message.reply_text(
                f"⏳ *{MACHINE_NAME}* creating…", parse_mode="Markdown")
            result = await run_mkdir(args, str(WORK_DIR))
            await ack.edit_text(result)
            return

        if cmd:
            await update.message.reply_text(
                f"Unknown: `{cmd}`. Use proj / claude / cursor / gh / mkdir / status.",
                parse_mode="Markdown")

    async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not authorized(update):
            return

        chat_id      = update.effective_chat.id
        data         = query.data or ""
        proj_prefix  = f"{_CB}proj:"
        reset_prefix = f"{_CB}reset:"

        if data.startswith(proj_prefix):
            p       = pending.pop(chat_id, {})
            subdirs = p.get("subdirs", [])
            idx     = int(data[len(proj_prefix):])
            if idx == 0:
                active_dirs[chat_id] = str(WORK_DIR)
                name = f"{WORK_DIR.name}/ (root)"
            else:
                name = subdirs[idx - 1]
                active_dirs[chat_id] = str(WORK_DIR / name)
            await query.edit_message_text(
                f"📌 *{MACHINE_NAME}* — active: *{name}*", parse_mode="Markdown")

        elif data.startswith(reset_prefix):
            p = pending.pop(chat_id, None)
            if not p:
                await query.edit_message_text("⚠️ Session expired. Run `gh reset` again.")
                return
            idx    = int(data[len(reset_prefix):])
            commit = p["commits"][idx]
            result = await _git(["git", "reset", "--hard", commit["hash"]], p["work_dir"])
            await query.edit_message_text(
                f"↩️ *{MACHINE_NAME}* reset to `{commit['hash']}` — {commit['msg']}\n\n{result}",
                parse_mode="Markdown")

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    auth_status = f"GitHub: {GITHUB_EMAIL}" if GITHUB_EMAIL else "GitHub: not configured"
    log.info(f"🚀 {MACHINE_NAME} (prefix: '{MACHINE_PREFIX}'), work dir: {WORK_DIR}")
    log.info(f"🔒 Allowed: {ALLOWED_CHAT_IDS or 'ALL'}  |  {auth_status}")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        if ASKPASS:
            try:
                os.unlink(ASKPASS)
            except Exception:
                pass
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
