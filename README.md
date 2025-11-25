# Aternos Discord Bot

A Discord bot to control your Aternos Minecraft server.

## Setup Instructions

### 1. Install Libraries

```bash
pip install -r requirements.txt
```

### 2. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to "Bot" section → Click "Add Bot"
4. Copy the bot token
5. Go to "OAuth2" → "URL Generator"
   - Select scope: `bot`
   - Select permissions: `Send Messages`, `Read Message History`, `Manage Channels`
6. Copy the generated URL and open it to invite the bot to your server

### 3. Configure Secrets

Create a `.env` file in the project root and add your Discord bot token:

```
DISCORD_TOKEN=your_actual_discord_bot_token
```

**Note:** Aternos credentials are now configured per Discord server (see step 4).

### 4. Configure Aternos Credentials (Per Server)

After adding the bot to a Discord server:

1. The bot will automatically create a `server-setup` channel
2. Go to the `server-setup` channel
3. Use these commands to set your Aternos credentials:
   - `!username YourAternosUsername` - Set your Aternos username
   - `!password YourPassword` - Set your Aternos password
   - `!setup-test` - Test your credentials

**Important:** Only enter credentials in the `server-setup` channel for security.

If the setup channel wasn't created automatically, use `!create-setup-channel` (requires Manage Channels permission).

### 5. Run the Bot

```bash
python bot.py
```

## Commands

### Server Control Commands (use in any channel)
- `!start` - Start the Aternos server
- `!stop` - Stop the Aternos server
- `!status` - Check server status

### Setup Commands (only in `server-setup` channel)
- `!username YourUsername` - Set your Aternos username
- `!password YourPassword` - Set your Aternos password
- `!setup-test` - Test your credentials
- `!create-setup-channel` - Manually create the setup channel (requires Manage Channels permission)

## Notes

- Each Discord server can have its own Aternos credentials
- Credentials are stored securely in `server_credentials.json`
- The bot automatically creates a `server-setup` channel when joining a new server
- Setup commands only work in the `server-setup` channel for security
- The bot will automatically select the first server from your Aternos account
- Server operations may take a few minutes to complete

