# Phone → Desktop AI Agent Dispatcher

Send messages from your iPhone (via Telegram) to Claude Code or Cursor running on any of your desktops.

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

## Quick Start (10 minutes)

### Step 1: Create a Telegram Bot (once)

1. Open Telegram on your iPhone, search for **@BotFather**
2. Send `/newbot`, pick a name like "My Code Dispatch"
3. Copy the **bot token** (looks like `123456:ABCdef...`)
4. **Create 3 separate bots** — one per machine, e.g.:
   - `MyWindowsCodeBot`
   - `MyMacCodeBot`
   - `MyLinuxCodeBot`

   Or use **one bot** for all machines — see the Multi-Machine section below.

### Step 2: Install on Each Machine

**All machines — the bot dependency:**

```bash
pip install python-telegram-bot --break-system-packages
```

**All machines — Claude Code:**

```bash
# Requires Node.js 22+
npm install -g @anthropic-ai/claude-code
```

**All machines — Cursor CLI (optional):**

```bash
curl https://cursor.com/install -fsSL | bash
```

### Step 3: Configure Each Machine

Copy `config.example.json` → `config.json` and edit:

**Windows** (`config.json`):
```json
{
    "telegram_bot_token": "YOUR_WINDOWS_BOT_TOKEN",
    "allowed_chat_ids": [],
    "machine_name": "windows-pc",
    "default_work_dir": "C:\\Users\\YourName\\projects"
}
```

**MacBook** (`config.json`):
```json
{
    "telegram_bot_token": "YOUR_MAC_BOT_TOKEN",
    "allowed_chat_ids": [],
    "machine_name": "macbook-air",
    "default_work_dir": "/Users/yourname/projects"
}
```

**Linux** (`config.json`):
```json
{
    "telegram_bot_token": "YOUR_LINUX_BOT_TOKEN",
    "allowed_chat_ids": [],
    "machine_name": "linux-desktop",
    "default_work_dir": "/home/yourname/projects"
}
```

### Step 4: Get Your Chat ID

1. Start the bot: `python dispatcher.py`
2. Open Telegram on your iPhone, message the bot anything
3. It replies with "Unauthorized. Your chat ID is `XXXXXX`"
4. Add that number to `allowed_chat_ids` in config.json
5. Restart the bot

### Step 5: Run It

```bash
python dispatcher.py
```

To run in background:

**macOS / Linux:**
```bash
nohup python dispatcher.py > dispatch.log 2>&1 &
```

**Windows (PowerShell):**
```powershell
Start-Process python -ArgumentList "dispatcher.py" -WindowStyle Hidden
```

## Usage (from your iPhone)

Open Telegram and message your bot:

| Message | What happens |
|---------|-------------|
| `claude: fix the auth bug in login.py` | Runs Claude Code headless |
| `cursor: refactor the database module` | Runs Cursor Agent CLI |
| `cd ~/myproject && claude: run tests and fix failures` | Changes work dir first |
| `cc: quick code review` | Shorthand for Claude Code |
| `cur: explain the caching layer` | Shorthand for Cursor |
| `status` | Check if machine is alive |

If you skip the agent prefix, it defaults to Claude Code.

## Multi-Machine with One Bot

If you prefer **one bot for all machines**, use `dispatcher_multi.py` and add `"machine_prefix"` to each config:

**Windows config:** `"machine_prefix": "win"`
**Mac config:** `"machine_prefix": "mac"`
**Linux config:** `"machine_prefix": "linux"`

Then from Telegram:

| Message | Target |
|---------|--------|
| `win claude: fix the bug` | Windows only responds |
| `mac cursor: refactor auth` | Mac only responds |
| `linux claude: run tests` | Linux only responds |
| `all status` | All machines respond |
| `claude: fix the bug` | All machines respond (no prefix) |

## Run as a Service (auto-start on boot)

### Linux (systemd)

```bash
sudo tee /etc/systemd/system/code-dispatch.service << 'EOF'
[Unit]
Description=Phone Code Dispatcher
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/phone-dispatch
ExecStart=/usr/bin/python3 dispatcher.py
Restart=always
RestartSec=10
Environment=ANTHROPIC_API_KEY=sk-ant-YOUR-KEY

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable code-dispatch
sudo systemctl start code-dispatch
```

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
        <string>/Users/YOU/phone-dispatch/dispatcher.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/Users/YOU/phone-dispatch</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>sk-ant-YOUR-KEY</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/code-dispatch.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/code-dispatch-err.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.codedispatch.plist
```

### Windows (Task Scheduler)

```powershell
$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\Users\YOU\phone-dispatch\dispatcher.py" -WorkingDirectory "C:\Users\YOU\phone-dispatch"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "CodeDispatch" -Action $action -Trigger $trigger -Settings $settings
```

## Security Notes

- **Always set `allowed_chat_ids`** — without it, anyone who finds your bot can run commands on your machine.
- Claude Code's `--allowedTools` flag in the script restricts what tools it can use. Tighten this based on your needs.
- The Telegram bot token is a secret — don't commit config.json to git.
- Consider running in a project directory with a `.claude/settings.json` that restricts permissions.

## Troubleshooting

**"claude CLI not found"**: Make sure `npm install -g @anthropic-ai/claude-code` was run and the npm global bin is in your PATH.

**"agent CLI not found" (Cursor)**: Run `cursor` from the GUI first, then install the CLI via Command Palette → "Install cursor command" / "Install agent command".

**Bot doesn't respond**: Check that `allowed_chat_ids` contains your chat ID, and that the bot token is correct.

**Long-running tasks**: The default timeout is 5 minutes. Edit the `timeout=300` value in dispatcher.py if you need longer.
