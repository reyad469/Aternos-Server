import os
import json
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from python_aternos import Client

# Load environment variables
load_dotenv()

# Get Discord token from .env
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Storage file for server credentials
CREDENTIALS_FILE = 'server_credentials.json'

# Create Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store Aternos clients per server
server_clients = {}
server_servers = {}

def load_credentials():
    """Load server credentials from JSON file"""
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_credentials(credentials):
    """Save server credentials to JSON file"""
    with open(CREDENTIALS_FILE, 'w') as f:
        json.dump(credentials, f, indent=2)

def get_server_credentials(guild_id):
    """Get credentials for a specific server"""
    credentials = load_credentials()
    return credentials.get(str(guild_id), {})

def set_server_credentials(guild_id, username, password):
    """Set credentials for a specific server"""
    credentials = load_credentials()
    credentials[str(guild_id)] = {
        'username': username,
        'password': password
    }
    save_credentials(credentials)

async def connect_to_aternos(guild_id):
    """Connect to Aternos for a specific server"""
    creds = get_server_credentials(guild_id)
    if not creds.get('username') or not creds.get('password'):
        return False
    
    try:
        client = Client()
        client.login(creds['username'], creds['password'])
        servers = client.account.list_servers()
        
        if servers:
            server = servers[0]
            server.fetch()
            server_clients[str(guild_id)] = client
            server_servers[str(guild_id)] = server
            return True
    except Exception as e:
        print(f'Error connecting to Aternos for server {guild_id}: {e}')
    return False

@bot.event
async def on_ready():
    print(f'{bot.user} has logged in!')
    print(f'Bot is in {len(bot.guilds)} server(s)')
    
    # List all servers the bot is in
    for guild in bot.guilds:
        print(f'  - {guild.name} (ID: {guild.id})')
    
    # Connect to Aternos for all servers with credentials
    for guild in bot.guilds:
        await connect_to_aternos(guild.id)

@bot.event
async def on_guild_join(guild):
    """When bot joins a new server, create setup channel"""
    print(f'\n🎉 Bot joined server: {guild.name} (ID: {guild.id})')
    
    try:
        # Send welcome message to first available channel
        welcome_sent = False
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                try:
                    embed = discord.Embed(
                        title='🤖 Bot Successfully Added!',
                        description=f'Thanks for adding me to **{guild.name}**!',
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name='Next Steps',
                        value='I\'m setting up the configuration channel now...',
                        inline=False
                    )
                    await channel.send(embed=embed)
                    welcome_sent = True
                    print(f'  ✓ Sent welcome message to #{channel.name}')
                    break
                except:
                    continue
        
        # Check if bot has permission to create channels
        if not guild.me.guild_permissions.manage_channels:
            print(f'  ⚠️ Warning: Bot does not have "Manage Channels" permission')
            # Try to find a channel to send a message instead
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    await channel.send(
                        '⚠️ **Setup Required:**\n'
                        'I need "Manage Channels" permission to create the setup channel.\n'
                        'Please give me this permission and use `!create-setup-channel` in any channel, '
                        'or manually create a channel named `server-setup`.'
                    )
                    break
            return
        
        # Check if setup channel already exists
        setup_channel = discord.utils.get(guild.text_channels, name='server-setup')
        
        if not setup_channel:
            # Create the setup channel
            try:
                setup_channel = await guild.create_text_channel(
                    'server-setup',
                    topic='Enter your Aternos credentials here using !username and !password commands',
                    reason='Auto-created setup channel for Aternos bot configuration'
                )
                print(f'Successfully created setup channel in {guild.name}')
                
                # Wait a moment for channel to be ready
                await asyncio.sleep(1)
                
                # Send welcome message
                embed = discord.Embed(
                    title='🔧 Server Setup',
                    description='Welcome! Please set up your Aternos credentials.',
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name='Setup Instructions',
                    value=(
                        '1. Use `!username YourAternosUsername` to set your username\n'
                        '2. Use `!password YourPassword` to set your password\n'
                        '3. Use `!setup-test` to test your credentials\n\n'
                        '**Note:** Only enter credentials in this channel for security.'
                    ),
                    inline=False
                )
                await setup_channel.send(embed=embed)
                print(f'  ✓ Created setup channel: #{setup_channel.name}')
                
                # Send confirmation to first available channel
                if not welcome_sent:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages and channel.id != setup_channel.id:
                            try:
                                await channel.send(f'✅ **Setup channel created!** Please go to {setup_channel.mention} to configure your Aternos credentials.')
                                break
                            except:
                                continue
            except discord.Forbidden:
                print(f'Error: Forbidden - Cannot create channel in {guild.name}')
            except discord.HTTPException as e:
                print(f'Error: HTTP Exception when creating channel in {guild.name}: {e}')
        else:
            print(f'Setup channel already exists in {guild.name}')
            
    except Exception as e:
        print(f'Unexpected error in on_guild_join for {guild.name}: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()

# Setup commands (only work in server-setup channel)
@bot.command(name='username')
async def set_username(ctx, *, username: str):
    """Set Aternos username (only in server-setup channel)"""
    if ctx.channel.name != 'server-setup':
        await ctx.send('❌ This command can only be used in the `server-setup` channel.')
        return
    
    set_server_credentials(ctx.guild.id, username, get_server_credentials(ctx.guild.id).get('password', ''))
    await ctx.send(f'✅ Username set to: `{username}`\nNow use `!password YourPassword` to set your password.')

@bot.command(name='password')
async def set_password(ctx, *, password: str):
    """Set Aternos password (only in server-setup channel)"""
    if ctx.channel.name != 'server-setup':
        await ctx.send('❌ This command can only be used in the `server-setup` channel.')
        return
    
    set_server_credentials(ctx.guild.id, get_server_credentials(ctx.guild.id).get('username', ''), password)
    await ctx.send('✅ Password set!\nUse `!setup-test` to test your credentials.')

@bot.command(name='setup-test')
async def test_setup(ctx):
    """Test Aternos credentials"""
    if ctx.channel.name != 'server-setup':
        await ctx.send('❌ This command can only be used in the `server-setup` channel.')
        return
    
    creds = get_server_credentials(ctx.guild.id)
    if not creds.get('username') or not creds.get('password'):
        await ctx.send('❌ Please set both username and password first!')
        return
    
    test_msg = await ctx.send('🔄 Testing credentials...')
    
    if await connect_to_aternos(ctx.guild.id):
        server = server_servers.get(str(ctx.guild.id))
        if server:
            server_addr = getattr(server, 'address', 'Server')
            await test_msg.edit(content=f'✅ **Credentials valid!**\nConnected to server: `{server_addr}`\n\nYou can now use `!start`, `!stop`, and `!status` in other channels.')
        else:
            await test_msg.edit(content='✅ Credentials valid but no servers found.')
    else:
        await test_msg.edit(content='❌ Invalid credentials. Please check your username and password.')

@bot.command(name='create-setup-channel')
@commands.has_permissions(manage_channels=True)
async def create_setup_channel_cmd(ctx):
    """Manually create the server-setup channel"""
    # Check if channel already exists
    setup_channel = discord.utils.get(ctx.guild.text_channels, name='server-setup')
    
    if setup_channel:
        await ctx.send('✅ Setup channel already exists!')
        return
    
    try:
        # Create the setup channel
        setup_channel = await ctx.guild.create_text_channel(
            'server-setup',
            topic='Enter your Aternos credentials here using !username and !password commands'
        )
        
        # Send welcome message
        embed = discord.Embed(
            title='🔧 Server Setup',
            description='Welcome! Please set up your Aternos credentials.',
            color=discord.Color.blue()
        )
        embed.add_field(
            name='Setup Instructions',
            value=(
                '1. Use `!username YourAternosUsername` to set your username\n'
                '2. Use `!password YourPassword` to set your password\n'
                '3. Use `!setup-test` to test your credentials\n\n'
                '**Note:** Only enter credentials in this channel for security.'
            ),
            inline=False
        )
        await setup_channel.send(embed=embed)
        
        await ctx.send(f'✅ Created setup channel: {setup_channel.mention}')
    except Exception as e:
        await ctx.send(f'❌ Error creating channel: {e}')

@bot.command(name='start')
async def start_server(ctx):
    """Start the Aternos server"""
    # Get server-specific Aternos server
    aternos_server = server_servers.get(str(ctx.guild.id))
    
    if not aternos_server:
        await ctx.send('❌ Server not configured. Please set up your Aternos credentials in the `server-setup` channel using `!username` and `!password` commands.')
        return
    
    try:
        # Refresh server status
        aternos_server.fetch()
        status = aternos_server.status
        
        if status == 'online':
            await ctx.send('✅ **Server Status:** 🟢 **ONLINE**')
            return
        elif status == 'starting':
            await ctx.send('⏳ **Loading... Preparing server...**\n🟡 Status: STARTING')
            return
        
        # Send loading message
        loading_msg = await ctx.send('⏳ **Loading... Preparing server...**')
        
        # Start the server
        aternos_server.start()
        
        # Wait a moment for status to update
        await asyncio.sleep(3)
        
        # Keep checking status until online or timeout (max 5 minutes = 60 checks * 5 seconds)
        max_checks = 60
        check_count = 0
        
        while check_count < max_checks:
            # Refresh server status
            aternos_server.fetch()
            current_status = aternos_server.status
            
            status_emoji = {
                'online': '🟢',
                'offline': '🔴',
                'starting': '🟡',
                'stopping': '🟠'
            }.get(current_status, '⚪')
            
            # If server is online, update message and break
            if current_status == 'online':
                await loading_msg.edit(content=f'✅ **Server Started!**\n{status_emoji} **Status:** ONLINE\n\n_Server is ready to use!_')
                return
            
            # Update message with current status
            if current_status == 'starting':
                await loading_msg.edit(content=f'⏳ **Loading... Preparing server...**\n{status_emoji} **Status:** STARTING\n\n_Please wait, server is starting up..._')
            else:
                status_text = current_status.upper() if current_status else 'UNKNOWN'
                await loading_msg.edit(content=f'⏳ **Loading... Preparing server...**\n{status_emoji} **Status:** {status_text}\n\n_Waiting for server to start..._')
            
            # Wait 5 seconds before next check
            await asyncio.sleep(5)
            check_count += 1
        
        # If we reach here, server didn't come online in time
        aternos_server.fetch()
        final_status = aternos_server.status
        if final_status != 'online':
            await loading_msg.edit(content=f'⏳ **Server is still starting...**\n🟡 **Status:** {final_status.upper() if final_status else "STARTING"}\n\n_It may take a few more minutes. Use !status to check again._')
        
    except Exception as e:
        await ctx.send(f'❌ Error starting server: {str(e)}')

@bot.command(name='stop')
async def stop_server(ctx):
    """Stop the Aternos server"""
    # Get server-specific Aternos server
    aternos_server = server_servers.get(str(ctx.guild.id))
    
    if not aternos_server:
        await ctx.send('❌ Server not configured. Please set up your Aternos credentials in the `server-setup` channel using `!username` and `!password` commands.')
        return
    
    try:
        # Refresh server status
        aternos_server.fetch()
        status = aternos_server.status
        
        if status == 'offline':
            await ctx.send('✅ Server is already offline!')
            return
        elif status == 'stopping':
            await ctx.send('⏳ Server is already stopping...')
            return
        
        # Stop the server
        aternos_server.stop()
        await ctx.send('✅ **Server stopped!** 🛑\nThe server is now shutting down.')
    except Exception as e:
        await ctx.send(f'❌ Error stopping server: {str(e)}')

@bot.command(name='status')
async def server_status(ctx):
    """Check the Aternos server status"""
    # Get server-specific Aternos server
    aternos_server = server_servers.get(str(ctx.guild.id))
    
    if not aternos_server:
        await ctx.send('❌ Server not configured. Please set up your Aternos credentials in the `server-setup` channel using `!username` and `!password` commands.')
        return
    
    try:
        # Refresh server info
        aternos_server.fetch()
        status = aternos_server.status
        
        # Get player count if available
        players_count = getattr(aternos_server, 'players_count', None)
        players_list = getattr(aternos_server, 'players_list', None)
        
        # Calculate online players from players_list
        if players_list is not None:
            # players_list is usually a list of online players
            players_online = len(players_list) if isinstance(players_list, list) else 0
        else:
            players_online = 0
        
        # Get max players (players_count is usually max players)
        max_players = players_count if players_count is not None else 'N/A'
        
        # Format display
        if max_players == 'N/A':
            players_display = f'{players_online}' if players_online > 0 else '0'
        else:
            players_display = f'{players_online}/{max_players}'
        
        status_emoji = {
            'online': '🟢',
            'offline': '🔴',
            'starting': '🟡',
            'stopping': '🟠'
        }.get(status, '⚪')
        
        status_display = {
            'online': '**ONLINE**',
            'offline': '**OFFLINE**',
            'starting': '**LOADING... PREPARING...**',
            'stopping': '**STOPPING...**'
        }.get(status, status.upper() if status else 'UNKNOWN')
        
        await ctx.send(
            f'{status_emoji} **Server Status:** {status_display}\n'
            f'👥 **Players:** {players_display}'
        )
    except Exception as e:
        await ctx.send(f'❌ Error getting server status: {e}')

@bot.command(name='invite')
async def invite_link(ctx):
    """Get the bot invite link"""
    # Bot's application ID
    bot_id = bot.user.id
    # Permissions: Manage Channels, Send Messages, Read Message History, Embed Links
    permissions = 2147568640
    
    invite_url = f'https://discord.com/oauth2/authorize?client_id={bot_id}&permissions={permissions}&scope=bot'
    
    embed = discord.Embed(
        title='🔗 Add Bot to Your Server',
        description=f'Click the link below to add this bot to another server:',
        color=discord.Color.green()
    )
    embed.add_field(
        name='Invite Link',
        value=f'[Click Here to Add Bot]({invite_url})',
        inline=False
    )
    embed.add_field(
        name='Permissions Needed',
        value='• Manage Channels\n• Send Messages\n• Read Message History',
        inline=False
    )
    embed.set_footer(text='Make sure the bot is set as "Public Bot" in Developer Portal')
    
    await ctx.send(embed=embed)

# Run the bot
if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print('❌ DISCORD_TOKEN not found in .env file!')
    else:
        print('\n' + '='*50)
        print('🤖 Aternos Discord Bot Starting...')
        print('='*50)
        print(f'\n✅ Bot is ready!')
        print(f'\n📋 To make bot public:')
        print(f'   1. Go to: https://discord.com/developers/applications/1442827241892352073/bot')
        print(f'   2. Enable "Public Bot" toggle')
        print(f'\n🔗 Invite URL:')
        print(f'   https://discord.com/oauth2/authorize?client_id=1442827241892352073&permissions=2147568640&scope=bot')
        print(f'\n' + '='*50 + '\n')
        bot.run(DISCORD_TOKEN)

