# Phone → Desktop AI Agent Dispatcher

Send messages from your iPhone (via Telegram) to Claude Code or Cursor running on any of your desktops. Includes GitHub integration, persistent sessions, vision/image analysis, and Telegram-based permission approval.

```
┌──────────┐    Telegram     ┌─────────────────────────────┐
│  iPhone   │───────API──────▶│  Windows  (dispatcher.py)   │
│ Telegram  │                 │  → Claude Code / Cursor     │
│   App     │                 └─────────────────────────────┘
│           │                 ┌─────────────────────────────┐
│           │────────────────▶│  MacBook  (dispatcher.py)   │
│           │                 │  → Claude Code / Cursor     │
│           │                 └─────────────────────────────┘
│           │                 ┌─────────────────────────────┐
│           │────────────────▶│  Linux    (dispatcher.py)   │
│           │                 │  → Claude Code / Cursor     │
└──────────┘                 └─────────────────────────────┘
```

## Features

- **Claude Code & Cursor agents** — run AI coding assistants remotely, with persistent conversation context per project across restarts
- **GitHub integration** — pull, commit+push (Claude auto-generates the commit message), reset to any commit, and `git init` with remote origin — all authenticated via a token in `.env`
- **Project directory picker** — one `proj` command shows an inline button menu; all subsequent commands run in the selected directory
- **`mkdir` command** — create a new project directory and optionally create a matching GitHub repo
- **Vision / image analysis** — send a photo or video from Telegram; Claude reads it using its vision capability
- **Permission forwarding** — any tool Claude Code wants to use that isn't pre-approved appears in Telegram as Allow/Deny buttons instead of blocking the terminal
- **Multi-machine support** — share one bot across multiple machines using `dispatcher_multi.py` with machine prefixes

---

## Quick Start

### Step 1: Create a Telegram Bot (once)

1. Open Telegram, search **@BotFather**
2. Send `/newbot`, pick a name, copy the **bot token** (`123456:ABCdef…`)
3. For one bot per machine use `dispatcher.py`; for one shared bot across machines use `dispatcher_multi.py`

### Step 2: Install Dependencies

```bash
# Python Telegram library
pip install python-telegram-bot --break-system-packages

# Claude Code (requires Node.js 22+)
npm install -g @anthropic-ai/claude-code

# Cursor CLI (optional)
curl https://cursor.com/install -fsSL | bash

# ffmpeg — only needed for video frame extraction (optional)
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Linux
```

### Step 3: Configure Each Machine

Copy and edit `config.json`:

```json
{
    "telegram_bot_token": "YOUR_BOT_TOKEN",
    "allowed_chat_ids": [],
    "machine_name": "macbook-air",
    "default_work_dir": "/Users/yourname/projects",
    "max_output_length": 3500
}
```

For the multi-machine dispatcher, also add:
```json
    "machine_prefix": "mac"
```
Use `"win"`, `"mac"`, or `"linux"` as the prefix on each machine.

### Step 4: Set Up GitHub Authentication

Create a `.env` file next to the dispatcher script:

```env
GITHUB_TOKEN=ghp_your_token_here
GITHUB_EMAIL=you@example.com
GITHUB_NAME=Your Name
```

**Getting a GitHub token:**
1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click **Generate new token (classic)**
3. Select scopes: `repo` (full), `workflow` (if needed)
4. Copy the token starting with `ghp_`

This token is used to authenticate `git push` and `git pull` without password prompts. It is never committed to git (add `.env` to your `.gitignore`).

### Step 5: Get Your Chat ID

1. Start the bot: `python dispatcher.py`
2. Message the bot anything from Telegram
3. It replies: "Unauthorized. Chat ID: `XXXXXX`"
4. Add that number to `allowed_chat_ids` in `config.json`
5. Restart the bot

### Step 6: Run It

```bash
python dispatcher.py
```

To keep it running in the background:

**macOS / Linux:**
```bash
nohup python dispatcher.py > dispatch.log 2>&1 &
```

**Windows (PowerShell):**
```powershell
Start-Process python -ArgumentList "dispatcher.py" -WindowStyle Hidden
```

---

## Workflow

All agent and git commands run inside your **active project directory**. Switch projects at any time without interrupting running agents.

### 1. Pick a project

```
proj
```

An inline button menu appears listing all subdirectories of `default_work_dir`. Tap one to set it as active. All subsequent commands run there.

### 2. Run AI agents

```
claude: fix the login bug in auth.py
cursor: refactor the database module
```

Sessions persist across messages and across dispatcher restarts — Claude remembers the full conversation history per project. To start a fresh session:

```
claude: new
```

### 3. Git / GitHub operations

```
gh pull              — git pull (authenticated with your token)
gh push              — git add -A, Claude generates a commit message, git push
gh reset             — shows a commit picker; tap to reset --hard
gh init <url>        — git init + set remote origin (paste your GitHub repo URL)
```

`gh push` automatically:
- Detects changes with `git status --porcelain`
- Stages everything with `git add -A`
- Asks Claude to write a concise commit message from the diff
- Runs `git push -u origin HEAD` (works on first push too)

### 4. Create a new project

```
mkdir: myproject
mkdir: myproject --public    — also creates a GitHub repo (public)
mkdir: myproject --private   — also creates a GitHub repo (private)
```

When `--public` or `--private` is given, the dispatcher runs `git init`, makes an initial commit, and calls `gh repo create` automatically.

### 5. Send images / video

Just send a photo or video directly in Telegram chat. Optionally add a caption as your question:

```
[send photo]
"what does this error message say?"

[send video]
"describe what's happening on screen"
```

Photos are saved to your active project directory and passed to Claude for analysis. Videos are saved and (if ffmpeg is installed) 1 frame/second is extracted for Claude to view. No special Telegram configuration is needed.

### 6. Permission approvals

When Claude Code wants to use a tool that isn't pre-approved (e.g., an unusual shell command), a message appears in Telegram with **Allow** and **Deny** buttons. Tap to respond — no need to look at your desktop.

Pre-approved tools (no prompt): `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `NotebookRead`, `NotebookEdit`, `TodoRead`, `TodoWrite`.

---

## Command Reference

| Message | What it does |
|---------|-------------|
| `proj` | Show project directory picker |
| `claude: <prompt>` | Run Claude Code in active project (persistent session) |
| `claude: new` | Clear Claude session for current project |
| `cursor: <prompt>` | Run Cursor agent in active project |
| `gh pull` | `git pull` with token auth |
| `gh push` | Stage all, Claude commit msg, `git push` |
| `gh reset` | Commit picker → `git reset --hard` |
| `gh init <url>` | `git init` + set remote origin |
| `mkdir: <name>` | Create project subdirectory |
| `mkdir: <name> --public` | Create dir + GitHub public repo |
| `mkdir: <name> --private` | Create dir + GitHub private repo |
| `status` | Show machine info and active project |
| `cc: ...` | Alias for `claude:` |
| `cur: ...` | Alias for `cursor:` |
| `p` | Alias for `proj` |
| _(send a photo or video)_ | Vision analysis via Claude |

---

## Multi-Machine with One Bot

Use `dispatcher_multi.py` on each machine with a unique `machine_prefix` in `config.json`. All machines share one bot token.

| Message | Who responds |
|---------|-------------|
| `mac claude: fix the bug` | Mac only |
| `win cursor: refactor auth` | Windows only |
| `linux gh push` | Linux only |
| `all status` | All machines |
| `claude: fix the bug` | All machines (no prefix) |

Callback buttons (project picker, commit picker, permission prompts) are prefixed per machine so tapping a button on one machine doesn't accidentally trigger another.

---

## Run as a Service (auto-start on boot)

### macOS (launchd)

```bash
cat > ~/Library/LaunchAgents/com.codedispatch.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.codedispatch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/YOU/telegram/dispatcher.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/Users/YOU/telegram</string>
    <key>StandardOutPath</key>
    <string>/tmp/code-dispatch.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/code-dispatch-err.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.codedispatch.plist
```

### Linux (systemd)

```bash
sudo tee /etc/systemd/system/code-dispatch.service << 'EOF'
[Unit]
Description=Phone Code Dispatcher
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/telegram
ExecStart=/usr/bin/python3 dispatcher.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable code-dispatch
sudo systemctl start code-dispatch
```

### Windows (Task Scheduler)

```powershell
$action = New-ScheduledTaskAction -Execute "python" `
    -Argument "C:\Users\YOU\telegram\dispatcher.py" `
    -WorkingDirectory "C:\Users\YOU\telegram"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "CodeDispatch" -Action $action -Trigger $trigger -Settings $settings
```

---

## Security Notes

- **Always set `allowed_chat_ids`** — without it, anyone who finds your bot can run commands on your machine.
- **Never commit `.env` or `config.json`** — they contain your bot token and GitHub token. Add both to `.gitignore`.
- The `sessions.json` file stores Claude conversation IDs (not message content) — safe to keep locally.
- Claude Code runs with `--dangerously-skip-permissions` so it never blocks waiting for terminal input; the Telegram permission hook acts as the sole gatekeeper.

---

## Troubleshooting

**"claude CLI not found"** — Run `npm install -g @anthropic-ai/claude-code` and make sure the npm global bin is in your `PATH`.

**"agent CLI not found" (Cursor)** — Open the Cursor GUI first, then install CLI via Command Palette → "Install cursor command" / "Install agent command".

**`gh push` says "nothing to commit"** — The dispatcher checks `git status --porcelain` before staging. If the working tree is already clean, there's genuinely nothing to push.

**git commands touching the wrong repo** — The dispatcher sets `GIT_CEILING_DIRECTORIES` on every git call so git cannot traverse above the active project directory.

**Bot doesn't respond** — Check that `allowed_chat_ids` contains your chat ID, and the bot token is correct.

**Permission prompts appear in terminal** — The `--dangerously-skip-permissions` flag is set on all `claude` invocations; all permissions go through the Telegram hook. If you see a terminal prompt, it means the hook isn't registered — restart the dispatcher once to re-register it.

**Video analysis not working** — Install `ffmpeg` (`brew install ffmpeg` / `sudo apt install ffmpeg`). Without it, only the raw video file path is passed to Claude.
