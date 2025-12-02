import os 
import json 
import asyncio 
import discord
from discord.ext import commands
from discord.ui import Button, View
from dotenv import load_dotenv
import time 
import re
from bs4 import BeautifulSoup
import cloudscraper
import requests

# IMPORTANT: Patch requests.Session BEFORE importing python-aternos
# This ensures python-aternos will use our Cloudflare-bypassing session

# Store original Session class
_OriginalSession = requests.Session

# Create a proper subclass that uses cloudscraper
class CloudflareSession(_OriginalSession):
    """A Session class that uses cloudscraper to bypass Cloudflare"""
    def __init__(self, *args, **kwargs):
        # Don't call super().__init__ - we'll replace everything with cloudscraper
        # Create a cloudscraper session with improved settings
        # Try multiple browser configurations for better bypass
        browser_configs = [
            {
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            {
                'browser': 'firefox',
                'platform': 'windows',
                'desktop': True
            },
            {
                'browser': 'chrome',
                'platform': 'linux',
                'desktop': True
            }
        ]
        
        scraper = None
        last_error = None
        
        # Try different browser configs
        for browser_config in browser_configs:
            try:
                scraper = cloudscraper.create_scraper(
                    browser=browser_config,
                    delay=20,  # Increased delay for better bypass
                    debug=False,
                    captcha={'provider': '2captcha', 'api_key': ''}  # Disable captcha solving
                )
                # Test if scraper works
                test_response = scraper.get('https://www.cloudflare.com', timeout=10)
                if test_response.status_code == 200:
                    print(f"✅ Cloudflare bypass successful with {browser_config['browser']} on {browser_config['platform']}")
                    break
            except Exception as e:
                last_error = e
                continue
        
        # If all configs failed, use default chrome
        if scraper is None:
            print(f"⚠️ All browser configs failed, using default Chrome config")
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                },
                delay=25,  # Even longer delay
                debug=False
            )
        
        self._scraper = scraper
        
        # Set realistic headers with updated Chrome version
        self._scraper.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"'
        })
        
        # Copy all public attributes and methods from scraper to self
        # This ensures compatibility with requests.Session interface
        for attr_name in dir(self._scraper):
            if not attr_name.startswith('__') or attr_name in ['__class__', '__dict__', '__module__']:
                try:
                    attr_value = getattr(self._scraper, attr_name)
                    # Skip if it's a method we've already handled or if it's a descriptor
                    if not callable(attr_value) or attr_name in ['get', 'post', 'put', 'delete', 'patch', 'request', 'head', 'options']:
                        try:
                            setattr(self, attr_name, attr_value)
                        except (AttributeError, TypeError):
                            pass
                except:
                    pass
        
        # Ensure essential methods are bound correctly
        self.get = self._scraper.get
        self.post = self._scraper.post
        self.put = self._scraper.put
        self.delete = self._scraper.delete
        self.patch = self._scraper.patch
        self.request = self._scraper.request
        self.head = self._scraper.head
        self.options = self._scraper.options
        
        # Copy important attributes
        self.headers = self._scraper.headers
        self.cookies = self._scraper.cookies
        self.auth = getattr(self._scraper, 'auth', None)
        self.proxies = getattr(self._scraper, 'proxies', {})
        self.stream = getattr(self._scraper, 'stream', False)
        self.verify = getattr(self._scraper, 'verify', True)
        self.cert = getattr(self._scraper, 'cert', None)
        self.timeout = getattr(self._scraper, 'timeout', None)
        self.max_redirects = getattr(self._scraper, 'max_redirects', 30)
    
    def __getattr__(self, name):
        # Delegate any missing attributes to the scraper
        try:
            return getattr(self._scraper, name)
        except AttributeError:
            # Fall back to original Session if scraper doesn't have it
            return getattr(super(), name)

# Replace requests.Session with our CloudflareSession
# This MUST happen before python-aternos imports requests
requests.Session = CloudflareSession

# NOW import python-aternos - it will use our patched requests.Session
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

# Store queue monitoring tasks
queue_monitoring_tasks = {}

# Store auto-start monitoring tasks
auto_start_tasks = {}

# Auto-start settings file
AUTO_START_FILE = 'auto_start_settings.json'

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

def load_auto_start_settings():
    """Load auto-start settings from JSON file"""
    if os.path.exists(AUTO_START_FILE):
        with open(AUTO_START_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_auto_start_settings(settings):
    """Save auto-start settings to JSON file"""
    with open(AUTO_START_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def get_auto_start_enabled(guild_id):
    """Check if auto-start is enabled for a server"""
    settings = load_auto_start_settings()
    return settings.get(str(guild_id), False)

def set_auto_start_enabled(guild_id, enabled):
    """Enable or disable auto-start for a server"""
    settings = load_auto_start_settings()
    settings[str(guild_id)] = enabled
    save_auto_start_settings(settings)

async def connect_to_aternos(guild_id):
    """Connect to Aternos for a specific server"""
    creds = get_server_credentials(guild_id)
    if not creds.get('username') or not creds.get('password'):
        print(f'No credentials found for guild {guild_id}')
        return False
    
    try:
        print(f'Attempting to connect to Aternos for guild {guild_id}...')
        print(f'Username: {creds["username"]}')
        print(f'Password length: {len(creds["password"])} characters')
        
        # Create cloudscraper session with retry logic
        print('🔧 Creating cloudscraper session for Cloudflare bypass...')
        scraper = None
        max_scraper_retries = 3
        
        for scraper_retry in range(max_scraper_retries):
            try:
                # Try different browser configs
                browser_configs = [
                    {'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                    {'browser': 'firefox', 'platform': 'windows', 'desktop': True},
                    {'browser': 'chrome', 'platform': 'linux', 'desktop': True}
                ]
                
                browser_config = browser_configs[scraper_retry % len(browser_configs)]
                print(f"   Attempt {scraper_retry + 1}/{max_scraper_retries}: Using {browser_config['browser']} on {browser_config['platform']}...")
                
                scraper = cloudscraper.create_scraper(
                    browser=browser_config,
                    delay=20 + (scraper_retry * 5),  # Increasing delay: 20, 25, 30
                    debug=False
                )
                
                # Set realistic headers with updated Chrome version
                scraper.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br, zstd',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0',
                    'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"'
                })
                
                # Test the scraper (but don't fail if test site is blocked)
                try:
                    print(f"   Testing Cloudflare bypass...")
                    test_response = scraper.get('https://www.cloudflare.com', timeout=15)
                    if test_response.status_code == 200:
                        print(f"   ✅ Cloudflare bypass test successful!")
                        break
                    else:
                        print(f"   ⚠️ Test returned status {test_response.status_code}, but continuing anyway...")
                        # Still use this scraper - test site might be blocked but Aternos might work
                        break
                except Exception as test_err:
                    print(f"   ⚠️ Test failed: {test_err}, but continuing anyway...")
                    # Still use this scraper - test site might be blocked but Aternos might work
                    break
            except Exception as scraper_error:
                print(f"   ⚠️ Scraper creation/test failed: {scraper_error}")
                if scraper_retry < max_scraper_retries - 1:
                    print(f"   Waiting 5 seconds before retry...")
                    await asyncio.sleep(5)
                else:
                    # Use default as last resort (even if test failed)
                    print(f"   Using default Chrome config as fallback...")
                    try:
                        scraper = cloudscraper.create_scraper(
                            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                            delay=30,
                            debug=False
                        )
                        scraper.headers.update({
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.9',
                        })
                        print(f"   ✅ Fallback scraper created")
                    except Exception as fallback_err:
                        print(f"   ❌ Fallback scraper creation also failed: {fallback_err}")
                        # Continue anyway - might still work
        
        # Ensure scraper is set
        if scraper is None:
            print(f"   ⚠️ All scraper attempts failed, creating basic scraper...")
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                delay=30,
                debug=False
            )
        
        # Create client - it should use CloudflareSession due to our patch
        print('🔧 Creating Aternos client...')
        client = Client()
        
        # After client creation, try to inject cloudscraper into the connection's session
        # This is a fallback in case the patch didn't work
        if hasattr(client, 'atconn'):
            atconn = client.atconn
            if hasattr(atconn, 'session'):
                original_session = atconn.session
                # Only replace if it's not already a CloudflareSession
                if not hasattr(original_session, '_scraper'):
                    print('   Injecting cloudscraper into connection session...')
                    try:
                        # Replace the session with our cloudscraper
                        atconn.session = scraper
                        print('   ✓ Successfully injected cloudscraper session')
                    except Exception as inject_error:
                        print(f'   ⚠️ Could not inject session: {inject_error}')
        
        # Wait a moment before login to let Cloudflare settle
        print('⏳ Waiting 3 seconds before login to let Cloudflare settle...')
        await asyncio.sleep(3)
        
        # Attempt login with retry logic
        print('🔐 Attempting login with Cloudflare bypass...')
        login_success = False
        max_login_retries = 5  # Increased retries
        
        for login_retry in range(max_login_retries):
            try:
                print(f"   Login attempt {login_retry + 1}/{max_login_retries}...")
                
                # Make a warm-up request first to establish session
                if login_retry == 0 and hasattr(client, 'atconn') and hasattr(client.atconn, 'session'):
                    try:
                        print(f"   🔥 Warming up session with test request...")
                        warmup_response = client.atconn.session.get('https://aternos.org/', timeout=20)
                        if warmup_response.status_code == 200:
                            print(f"   ✅ Warm-up successful")
                            await asyncio.sleep(2)  # Wait a bit after warm-up
                    except Exception as warmup_err:
                        print(f"   ⚠️ Warm-up failed: {warmup_err}")
                
                client.login(creds['username'], creds['password'])
                login_success = True
                break
            except Exception as login_error:
                error_str = str(login_error)
                error_type = type(login_error).__name__
                
                # If it's a Cloudflare error and not the last retry, wait and retry
                if ('Cloudflare' in error_str or 'cloudflare' in error_str.lower() or 'CloudflareError' in error_type):
                    if login_retry < max_login_retries - 1:
                        wait_time = (login_retry + 1) * 15  # Wait 15s, 30s, 45s, 60s
                        print(f"   ⚠️ Cloudflare error on attempt {login_retry + 1}, waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                        
                        # Try to refresh the scraper with different config
                        try:
                            print(f"   🔄 Refreshing Cloudflare bypass session...")
                            browser_configs = [
                                {'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                                {'browser': 'firefox', 'platform': 'windows', 'desktop': True},
                                {'browser': 'chrome', 'platform': 'linux', 'desktop': True}
                            ]
                            browser_config = browser_configs[login_retry % len(browser_configs)]
                            new_scraper = cloudscraper.create_scraper(
                                browser=browser_config,
                                delay=30 + (login_retry * 5),
                                debug=False
                            )
                            # Update headers
                            new_scraper.headers.update({
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                                'Accept-Language': 'en-US,en;q=0.9',
                                'Accept-Encoding': 'gzip, deflate, br',
                                'Connection': 'keep-alive',
                                'Upgrade-Insecure-Requests': '1',
                            })
                            if hasattr(client, 'atconn') and hasattr(client.atconn, 'session'):
                                client.atconn.session = new_scraper
                                print(f"   ✅ Session refreshed with {browser_config['browser']}")
                        except Exception as refresh_err:
                            print(f"   ⚠️ Could not refresh session: {refresh_err}")
                        continue
                    else:
                        # Last retry failed
                        print(f'   Login error type: {error_type}')
                        print(f'   Login error: {error_str}')
                        raise Exception(
                            f"Unable to bypass Cloudflare protection after {max_login_retries} attempts.\n\n"
                            f"This may be due to:\n"
                            f"• Cloudflare detecting automated requests\n"
                            f"• IP address being flagged by Cloudflare\n"
                            f"• Aternos security measures\n"
                            f"• Network/VPN restrictions\n\n"
                            f"Original error: {error_str}\n\n"
                            f"Troubleshooting:\n"
                            f"• Wait a few minutes and try again\n"
                            f"• Verify credentials manually at https://aternos.org\n"
                            f"• Try from a different network/VPN\n"
                            f"• Check if your IP is blocked"
                        )
                else:
                    # Non-Cloudflare error, raise immediately
                    raise
            error_str = str(login_error)
            error_type = type(login_error).__name__
            print(f'   Login error type: {error_type}')
            print(f'   Login error: {error_str}')
            
            # If it's a Cloudflare error, provide helpful message
            if 'Cloudflare' in error_str or 'cloudflare' in error_str.lower() or 'CloudflareError' in error_type:
                raise Exception(
                    f"Unable to bypass Cloudflare protection.\n\n"
                    f"This may be due to:\n"
                    f"• Cloudflare detecting automated requests\n"
                    f"• IP address being flagged by Cloudflare\n"
                    f"• Aternos security measures\n"
                    f"• Network/VPN restrictions\n\n"
                    f"Original error: {error_str}\n\n"
                    f"Troubleshooting:\n"
                    f"• Wait a few minutes and try again\n"
                    f"• Verify credentials manually at https://aternos.org\n"
                    f"• Try from a different network/VPN\n"
                    f"• Check if your IP is blocked"
                )
            else:
                raise
        
        if login_success:
            print(f'✅ Login successful for guild {guild_id}')
        else:
            raise Exception("Login failed after all retry attempts")
        
        servers = client.account.list_servers()
        print(f'Found {len(servers)} server(s) for guild {guild_id}')
        
        if servers:
            server = servers[0]
            server.fetch()
            server_clients[str(guild_id)] = client
            server_servers[str(guild_id)] = server
            
            # Start auto-start monitoring if enabled
            if get_auto_start_enabled(guild_id):
                if str(guild_id) not in auto_start_tasks:
                    task = asyncio.create_task(monitor_auto_start(guild_id))
                    auto_start_tasks[str(guild_id)] = task
                    print(f'✅ Auto-start monitoring started for guild {guild_id}')
            
            return True
        else:
            print(f'⚠️ No servers found for guild {guild_id}')
            return False
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f'❌ Error connecting to Aternos for server {guild_id}:')
        print(f'   Error type: {error_type}')
        print(f'   Error message: {error_msg}')
        
        # If it's a Cloudflare error, provide more helpful message
        if 'cloudflare' in error_msg.lower() or 'cf-' in error_msg.lower() or 'challenge' in error_msg.lower():
            error_msg = f"Unable to bypass Cloudflare protection. This may be due to:\n" \
                       f"• Cloudflare detecting automated requests\n" \
                       f"• IP address being flagged\n" \
                       f"• Aternos security measures\n\n" \
                       f"Try:\n" \
                       f"• Waiting a few minutes and trying again\n" \
                       f"• Using a different network/VPN\n" \
                       f"• Verifying credentials manually at https://aternos.org"
        
        import traceback
        traceback.print_exc()
        return error_msg  # Return error message instead of False

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
        
        # Start auto-start monitoring if enabled
        if get_auto_start_enabled(guild.id):
            if str(guild.id) not in auto_start_tasks:
                task = asyncio.create_task(monitor_auto_start(guild.id))
                auto_start_tasks[str(guild.id)] = task
                print(f'✅ Auto-start monitoring enabled for {guild.name}')

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
    
    result = await connect_to_aternos(ctx.guild.id)
    if result is True:
        server = server_servers.get(str(ctx.guild.id))
        if server:
            server_addr = getattr(server, 'address', 'Server')
            await test_msg.edit(content=f'✅ **Credentials valid!**\nConnected to server: `{server_addr}`\n\nYou can now use `!start`, `!stop`, and `!status` in other channels.')
        else:
            await test_msg.edit(content='✅ Credentials valid but no servers found.')
    elif isinstance(result, str):
        # result is an error message
        await test_msg.edit(content=f'❌ **Authentication failed:**\n```{result}```\n\n**Troubleshooting:**\n• Verify your username and password are correct\n• Try logging into https://aternos.org manually\n• Check if your account is locked or needs verification\n• Make sure there are no extra spaces in the password')
    else:
        await test_msg.edit(content='❌ Invalid credentials. Please check your username and password.\n\n**Make sure:**\n• Username and password are set correctly\n• No extra spaces before/after\n• Account is not locked')

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

class ConfirmButton(View):
    """View with confirm and stop buttons for queue confirmation"""
    def __init__(self, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.guild_id = guild_id
        self.confirmed = False
    
    @discord.ui.button(label="✅ Confirm Start", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        """Handle confirmation button click"""
        # CRITICAL: Defer immediately to prevent timeout
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except Exception as defer_error:
            print(f'Error deferring interaction: {defer_error}')
            try:
                await interaction.response.send_message('⏳ Processing...', ephemeral=True)
            except:
                pass
            return
        
        try:
            aternos_server = server_servers.get(str(self.guild_id))
            if not aternos_server:
                await interaction.followup.send('❌ Server not found!', ephemeral=True)
                return
            
            # Try to confirm the start
            try:
                # ============================================================
                # EXTENSIVE DEBUGGING BEFORE CONFIRMATION
                # ============================================================
                print("=" * 60)
                print("🔍 CONFIRM BUTTON CLICKED - DEBUGGING")
                print("=" * 60)
                
                # Refresh server status first
                print("1. Refreshing server status...")
                aternos_server.fetch()
                current_status = aternos_server.status
                print(f"   Status after fetch: {current_status}")
                
                # Check _info for confirmation status
                print("2. Checking _info for confirmation requirements...")
                needs_confirm = False
                if hasattr(aternos_server, '_info'):
                    info_data = getattr(aternos_server, '_info')
                    if isinstance(info_data, dict):
                        print(f"   _info keys: {list(info_data.keys())}")
                        if 'queue' in info_data:
                            queue_info = info_data.get('queue', {})
                            if isinstance(queue_info, dict):
                                pending = queue_info.get('pending', '')
                                position = queue_info.get('position', None)
                                print(f"   Queue pending: '{pending}', position: {position}")
                                if pending and str(pending).lower() == 'pending':
                                    needs_confirm = True
                                    print("   ✅ Confirmation needed (pending='pending')")
                
                # Check css_class
                print("3. Checking css_class...")
                css_class = getattr(aternos_server, 'css_class', 'N/A')
                print(f"   css_class: '{css_class}'")
                if css_class and 'pending' in str(css_class).lower():
                    if 'queueing' not in str(css_class).lower():
                        needs_confirm = True
                        print("   ✅ Confirmation needed (css_class contains 'pending')")
                
                # Check if confirm method exists
                print("4. Checking confirm() method...")
                has_confirm = hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm)
                print(f"   Has confirm method: {has_confirm}")
                
                # Check connection
                print("5. Checking connection...")
                if hasattr(aternos_server, 'atconn'):
                    atconn = aternos_server.atconn
                    print(f"   Has atconn: True")
                    if hasattr(atconn, 'session'):
                        print(f"   Has session: True")
                
                print("6. Server attributes before confirm:")
                print(f"   status: {current_status}")
                print(f"   css_class: {css_class}")
                print(f"   needs_confirm (from checks): {needs_confirm}")
                print("=" * 60)
                
                # Only confirm if we actually need to
                if not needs_confirm and current_status == 'waiting':
                    await interaction.followup.send(
                        '⚠️ **Server is still in queue.**\n'
                        'Confirmation is only needed when the queue finishes.\n'
                        f'Current status: `{current_status}`'
                    )
                    return
                
                # Try to refresh connection/token if possible
                print("7. Attempting to refresh connection...")
                try:
                    # Re-fetch to get fresh token
                    aternos_server.fetch()
                    print("   ✅ Server status refreshed")
                except Exception as refresh_error:
                    print(f"   ⚠️ Could not refresh: {refresh_error}")
                
                # FORCE RE-AUTHENTICATION before confirming to get fresh token
                print("8. Force re-authenticating with Aternos to get fresh token...")
                try:
                    if await connect_to_aternos(self.guild_id):
                        aternos_server = server_servers.get(str(self.guild_id))
                        if aternos_server:
                            aternos_server.fetch()
                            print("   ✅ Re-authenticated and refreshed server")
                        else:
                            print("   ⚠️ Re-authenticated but server not found")
                    else:
                        print("   ⚠️ Re-authentication failed, continuing with existing connection")
                except Exception as reauth_error:
                    print(f"   ⚠️ Re-authentication error (non-critical): {reauth_error}")
                
                # Small delay to ensure server is ready for confirmation
                print("8.5. Waiting 1 second before confirming (ensuring server is ready)...")
                await asyncio.sleep(1)
                
                # Final status check right before confirming
                print("8.6. Final status check before confirming...")
                aternos_server.fetch()
                final_status = aternos_server.status
                print(f"   Final status: {final_status}")
                
                # Send confirmation to Aternos - Try multiple methods
                print("9. Attempting to confirm server start...")
                confirm_success = False
                last_error = None
                
                try:
                    # Get the connection
                    if hasattr(aternos_server, 'atconn'):
                        atconn = aternos_server.atconn
                        server_id = aternos_server.servid
                        
                        # Method 1: Use request_cloudflare (most reliable for Aternos)
                        if hasattr(atconn, 'request_cloudflare'):
                            try:
                                print("   Trying request_cloudflare method...")
                                confirm_url = 'https://aternos.org/ajax/server/confirm'
                                
                                # Debug: Check session cookies/headers if possible
                                if hasattr(atconn, 'session'):
                                    session = atconn.session
                                    print("   Session available, checking cookies...")
                                    try:
                                        if hasattr(session, 'cookies'):
                                            cookies = dict(session.cookies)
                                            print(f"   Session cookies keys: {list(cookies.keys())[:5]}...")  # First 5 keys
                                    except:
                                        pass
                                
                                # Try GET first (website might use GET)
                                try:
                                    print("   Attempting GET request...")
                                    response = atconn.request_cloudflare(confirm_url, 'GET')
                                    print(f"   ✅ GET response received: {response}")
                                    print(f"   Response type: {type(response)}")
                                    
                                    # Any response means the request was accepted
                                    if response is not None:
                                        confirm_success = True
                                        print("   ✅✅✅ CONFIRMATION SUCCESSFUL via GET!")
                                    else:
                                        raise Exception("Got None response")
                                        
                                except Exception as get_error:
                                    error_str = str(get_error)
                                    print(f"   ⚠️ GET failed: {error_str}")
                                    
                                    # If it's a 400, the request format might be wrong - try POST
                                    # But also check if server actually needs confirmation
                                    if '400' in error_str or 'Bad Request' in error_str:
                                        print("   Got 400 error - server might not be ready for confirmation")
                                        print("   Will try POST as alternative...")
                                    
                                    # Try POST as alternative
                                    try:
                                        print("   Attempting POST request...")
                                        response = atconn.request_cloudflare(confirm_url, 'POST')
                                        print(f"   ✅ POST response received: {response}")
                                        
                                        if response is not None:
                                            confirm_success = True
                                            print("   ✅✅✅ CONFIRMATION SUCCESSFUL via POST!")
                                        else:
                                            raise Exception("Got None response from POST")
                                    except Exception as post_error:
                                        post_error_str = str(post_error)
                                        print(f"   ⚠️ POST also failed: {post_error_str}")
                                        
                                        # If both fail with 400, the server might not be ready
                                        if '400' in post_error_str or 'Bad Request' in post_error_str:
                                            raise Exception(f"Server returned 400 Bad Request. This usually means:\n"
                                                          f"1. Server doesn't need confirmation right now\n"
                                                          f"2. Token/SEC expired (try restarting bot)\n"
                                                          f"3. Server status changed\n"
                                                          f"Error: {post_error_str}")
                                        raise post_error
                                        
                            except Exception as cf_error:
                                error_str = str(cf_error)
                                print(f"   ❌ request_cloudflare completely failed: {cf_error}")
                                print(f"   Error details: {type(cf_error).__name__}")
                                last_error = cf_error
                        
                        # Method 2: Direct session call if request_cloudflare didn't work
                        if not confirm_success and hasattr(atconn, 'session'):
                            try:
                                print("   Trying direct session call...")
                                session = atconn.session
                                import aiohttp
                                import requests
                                
                                confirm_url = 'https://aternos.org/ajax/server/confirm'
                                
                                if isinstance(session, aiohttp.ClientSession):
                                    async with session.get(confirm_url) as response:
                                        if response.status == 200:
                                            result = await response.text()
                                            print(f"   ✅ Direct session GET successful: {result}")
                                            confirm_success = True
                                elif isinstance(session, requests.Session):
                                    loop = asyncio.get_event_loop()
                                    response = await loop.run_in_executor(None, session.get, confirm_url)
                                    if response.status_code == 200:
                                        print(f"   ✅ Direct session GET successful: {response.text}")
                                        confirm_success = True
                            except Exception as session_error:
                                print(f"   ⚠️ Direct session call failed: {session_error}")
                                if not last_error:
                                    last_error = session_error
                        
                        # Method 3: Try library confirm() method as last resort
                        if not confirm_success:
                            try:
                                print("   Trying library confirm() method as fallback...")
                                aternos_server.confirm()
                                print("   ✅ Library confirm() method called")
                                confirm_success = True
                            except Exception as lib_error:
                                print(f"   ⚠️ Library confirm() failed: {lib_error}")
                                if not last_error:
                                    last_error = lib_error
                    else:
                        # No atconn, try library method
                        print("   No atconn, trying library confirm() method...")
                        aternos_server.confirm()
                        print("   ✅ Library confirm() method called")
                        confirm_success = True
                        
                except Exception as confirm_error:
                    print(f"   ❌ All confirm methods failed")
                    last_error = confirm_error
                    import traceback
                    traceback.print_exc()
                
                if confirm_success:
                    self.confirmed = True
                    print("   ✅✅✅ CONFIRMATION SUCCESSFUL!")
                else:
                    raise Exception(f"All confirmation methods failed. Last error: {last_error}")
                
                # Disable both buttons
                for item in self.children:
                    item.disabled = True
                
                # Edit the message to disable buttons
                try:
                    await interaction.message.edit(view=self)
                except Exception as edit_error:
                    print(f'Could not edit message (non-critical): {edit_error}')
                
                # Send success message
                await interaction.followup.send('✅ **Confirmation sent!** Starting server...\n⏳ Please wait, server is starting...')
                
            except Exception as e:
                error_msg = str(e)
                print(f'❌❌❌ Error confirming server: {e}')
                import traceback
                traceback.print_exc()
                
                # Try to re-authenticate if it's a 400/401 error
                if '400' in error_msg or '401' in error_msg or 'Bad Request' in error_msg:
                    print("🔄 Attempting to re-authenticate due to 400/401 error...")
                    print("   This will get a fresh Aternos token...")
                    try:
                        # Force re-authentication
                        guild_id_str = str(self.guild_id)
                        if await connect_to_aternos(self.guild_id):
                            print("✅ Re-authenticated successfully with fresh token")
                            aternos_server = server_servers.get(guild_id_str)
                            if aternos_server:
                                # Fetch fresh status
                                aternos_server.fetch()
                                print(f"   Fresh status: {aternos_server.status}")
                                
                                # Check if still needs confirmation
                                still_needs_confirm = False
                                if hasattr(aternos_server, '_info'):
                                    info_data = getattr(aternos_server, '_info')
                                    if isinstance(info_data, dict) and 'queue' in info_data:
                                        queue_info = info_data.get('queue', {})
                                        if isinstance(queue_info, dict):
                                            pending = queue_info.get('pending', '')
                                            if pending and str(pending).lower() == 'pending':
                                                still_needs_confirm = True
                                
                                if still_needs_confirm or aternos_server.status != 'online':
                                    # Try confirm again with fresh token
                                    try:
                                        print("   Attempting confirm() with fresh token...")
                                        aternos_server.confirm()
                                        print("   ✅ Confirm successful with fresh token!")
                                        self.confirmed = True
                                        for item in self.children:
                                            item.disabled = True
                                        try:
                                            await interaction.message.edit(view=self)
                                        except:
                                            pass
                                        await interaction.followup.send('✅ **Confirmation sent!** (After re-authentication)\n⏳ Starting server...')
                                        return
                                    except Exception as retry_error:
                                        print(f"❌ Confirm failed after re-auth: {retry_error}")
                                        import traceback
                                        traceback.print_exc()
                                else:
                                    print("   Server no longer needs confirmation")
                    except Exception as reconnect_error:
                        print(f"❌ Re-authentication failed: {reconnect_error}")
                        import traceback
                        traceback.print_exc()
                
                # Send error message
                try:
                    await interaction.followup.send(
                        f'❌ **Error confirming:** {error_msg}\n\n'
                        f'**Possible causes:**\n'
                        f'• Server might not need confirmation right now\n'
                        f'• Token expired - try restarting the bot\n'
                        f'• Server status changed\n\n'
                        f'**Try:**\n'
                        f'• Check Aternos website manually\n'
                        f'• Use `!confirm` command\n'
                        f'• Restart the bot if error persists'
                    )
                except:
                    pass
        except Exception as e:
            print(f'Error in confirm button handler: {e}')
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send('❌ An error occurred. Please try again or use `!confirm` command.', ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="🛑 Stop", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        """Handle stop button click"""
        # CRITICAL: Defer immediately to prevent timeout
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except Exception as defer_error:
            print(f'Error deferring interaction: {defer_error}')
            try:
                await interaction.response.send_message('⏳ Processing...', ephemeral=True)
            except:
                pass
            return
        
        try:
            aternos_server = server_servers.get(str(self.guild_id))
            if not aternos_server:
                await interaction.followup.send('❌ Server not found!', ephemeral=True)
                return
            
            try:
                # Refresh server status first
                aternos_server.fetch()
                
                # Stop the server
                aternos_server.stop()
                
                # Disable both buttons
                for item in self.children:
                    item.disabled = True
                
                # Edit the message to disable buttons
                try:
                    await interaction.message.edit(view=self)
                except Exception as edit_error:
                    print(f'Could not edit message (non-critical): {edit_error}')
                
                await interaction.followup.send('✅ **Server stop command sent!**')
                
            except Exception as e:
                error_msg = str(e)
                print(f'Error stopping server: {e}')
                import traceback
                traceback.print_exc()
                try:
                    await interaction.followup.send(f'❌ **Error stopping server:** {error_msg}')
                except:
                    pass
        except Exception as e:
            print(f'Error in stop button handler: {e}')
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send('❌ An error occurred. Please try again.', ephemeral=True)
            except:
                pass

async def fetch_queue_data_from_panel(aternos_server):
    """Fetch queue position and time from Aternos panel page HTML"""
    queue_position = None
    queue_time_str = None
    
    try:
        if hasattr(aternos_server, 'atconn') and hasattr(aternos_server, 'servid'):
            atconn = aternos_server.atconn
            server_id = aternos_server.servid
            
            # Try multiple URLs
            urls_to_try = [
                'https://aternos.org/server/',  # Main panel
                f'https://aternos.org/server/?id={server_id}',  # Server-specific
                'https://aternos.org/panel/',  # Panel page
            ]
            
            # Use the session from atconn
            if hasattr(atconn, 'session'):
                session = atconn.session
                import aiohttp
                import requests
                
                for panel_url in urls_to_try:
                    try:
                        if isinstance(session, aiohttp.ClientSession):
                            # Async aiohttp session
                            async with session.get(panel_url) as response:
                                print(f"Fetching queue data from: {panel_url} (status: {response.status})")
                                if response.status == 200:
                                    html_content = await response.text()
                                    queue_position, queue_time_str = parse_queue_from_html(html_content)
                                    if queue_position or queue_time_str:
                                        print(f"Successfully found queue data from {panel_url}")
                                        break
                                else:
                                    print(f"Failed to fetch {panel_url}: Status {response.status}")
                        elif isinstance(session, requests.Session):
                            # Sync requests session
                            loop = asyncio.get_event_loop()
                            response = await loop.run_in_executor(None, session.get, panel_url)
                            print(f"Fetching queue data from: {panel_url} (status: {response.status_code})")
                            if response.status_code == 200:
                                html_content = response.text
                                queue_position, queue_time_str = parse_queue_from_html(html_content)
                                if queue_position or queue_time_str:
                                    print(f"Successfully found queue data from {panel_url}")
                                    break
                            else:
                                print(f"Failed to fetch {panel_url}: Status {response.status_code}")
                    except Exception as e:
                        print(f"Error fetching {panel_url}: {e}")
                        continue
                        
                # If HTML parsing didn't work, try the queue API endpoint
                if not queue_position and not queue_time_str:
                    try:
                        queue_api_url = f'https://aternos.org/panel/ajax/queue.php?id={server_id}'
                        print(f"Trying queue API: {queue_api_url}")
                        
                        if isinstance(session, aiohttp.ClientSession):
                            async with session.get(queue_api_url) as response:
                                if response.status == 200:
                                    try:
                                        api_data = await response.json()
                                        print(f"Queue API response: {api_data}")
                                        # Parse API response
                                        if isinstance(api_data, dict):
                                            # Look for position in various formats
                                            for key in ['position', 'pos', 'queue_pos', 'current']:
                                                if key in api_data:
                                                    pos_val = api_data[key]
                                                    if isinstance(pos_val, (int, str)):
                                                        queue_position = str(pos_val)
                                                        # Check for max position
                                                        for max_key in ['max', 'max_position', 'total']:
                                                            if max_key in api_data:
                                                                max_val = api_data[max_key]
                                                                queue_position = f"{pos_val} / {max_val}"
                                                                break
                                                        break
                                            
                                            # Look for time
                                            for key in ['time', 'wait', 'eta', 'estimated']:
                                                if key in api_data:
                                                    time_val = api_data[key]
                                                    if isinstance(time_val, (int, float)):
                                                        minutes = int(time_val / 60) if time_val > 60 else int(time_val)
                                                        queue_time_str = f"ca. {minutes} min"
                                                        break
                                    except:
                                        # Try as text/HTML
                                        text_data = await response.text()
                                        queue_position, queue_time_str = parse_queue_from_html(text_data)
                                elif response.status == 503:
                                    # Service Unavailable - silently skip
                                    pass
                        elif isinstance(session, requests.Session):
                            loop = asyncio.get_event_loop()
                            response = await loop.run_in_executor(None, session.get, queue_api_url)
                            if response.status_code == 200:
                                try:
                                    api_data = response.json()
                                    print(f"Queue API response: {api_data}")
                                    # Same parsing as above
                                    if isinstance(api_data, dict):
                                        for key in ['position', 'pos', 'queue_pos', 'current']:
                                            if key in api_data:
                                                pos_val = api_data[key]
                                                if isinstance(pos_val, (int, str)):
                                                    queue_position = str(pos_val)
                                                    for max_key in ['max', 'max_position', 'total']:
                                                        if max_key in api_data:
                                                            max_val = api_data[max_key]
                                                            queue_position = f"{pos_val} / {max_val}"
                                                            break
                                                    break
                                        
                                        for key in ['time', 'wait', 'eta', 'estimated']:
                                            if key in api_data:
                                                time_val = api_data[key]
                                                if isinstance(time_val, (int, float)):
                                                    minutes = int(time_val / 60) if time_val > 60 else int(time_val)
                                                    queue_time_str = f"ca. {minutes} min"
                                                    break
                                except:
                                    text_data = response.text
                                    queue_position, queue_time_str = parse_queue_from_html(text_data)
                            elif response.status_code == 503:
                                # Service Unavailable - silently skip
                                pass
                    except Exception as e:
                        error_str = str(e)
                        # Don't spam console with 503 errors
                        if '503' not in error_str and 'Service Unavailable' not in error_str:
                            print(f"Error fetching queue API: {e}")
            else:
                print("No session available in atconn")
    except Exception as e:
        print(f"Error in fetch_queue_data_from_panel: {e}")
        import traceback
        traceback.print_exc()
    
    return queue_position, queue_time_str

def parse_queue_from_html(html_content):
    """Parse queue position and time from Aternos HTML"""
    queue_position = None
    queue_time_str = None
    
    try:
        # Try using BeautifulSoup if available
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find queue position: <span class="server-status-label-right queue-position"> (may have "hidden" class)
            queue_pos_elem = soup.find('span', class_=lambda x: x and 'queue-position' in x)
            if queue_pos_elem:
                queue_position = queue_pos_elem.get_text(strip=True)
                if queue_position:
                    print(f"Found queue position in HTML: {queue_position}")
            
            # Find queue time: <div class="server-status-label-left queue-time"> (may have "hidden" class)
            queue_time_elem = soup.find('div', class_=lambda x: x and 'queue-time' in x)
            if queue_time_elem:
                queue_time_str = queue_time_elem.get_text(strip=True)
                if queue_time_str:
                    print(f"Found queue time in HTML: {queue_time_str}")
        except ImportError:
            # BeautifulSoup not available, use regex
            pass
        except Exception as e:
            print(f"Error with BeautifulSoup, trying regex: {e}")
        
        # Always try regex as fallback (works even if BeautifulSoup failed)
        if not queue_position:
            # Pattern for queue position: "3535 / 3835" or "3535/3835" (handles "hidden" class)
            pos_match = re.search(r'<span[^>]*class="[^"]*queue-position[^"]*"[^>]*>([^<]+)</span>', html_content, re.IGNORECASE | re.DOTALL)
            if pos_match:
                queue_position = pos_match.group(1).strip()
                if queue_position:
                    print(f"Found queue position in HTML (regex): {queue_position}")
        
        if not queue_time_str:
            # Pattern for queue time: "ca. 8 min" (handles "hidden" class)
            time_match = re.search(r'<div[^>]*class="[^"]*queue-time[^"]*"[^>]*>([^<]+)</div>', html_content, re.IGNORECASE | re.DOTALL)
            if time_match:
                queue_time_str = time_match.group(1).strip()
                if queue_time_str:
                    print(f"Found queue time in HTML (regex): {queue_time_str}")
        
        # Also try to find the data in the status div directly
        if not queue_position or not queue_time_str:
            # Look for the pattern in the status div: <div class="status queueing">
            status_match = re.search(r'<div[^>]*class="[^"]*status[^"]*queueing[^"]*"[^>]*>.*?</div>', html_content, re.IGNORECASE | re.DOTALL)
            if status_match:
                status_html = status_match.group(0)
                # Try to extract from this section
                if not queue_position:
                    pos_in_status = re.search(r'(\d+\s*[/]\s*\d+)', status_html)
                    if pos_in_status:
                        queue_position = pos_in_status.group(1).strip()
                        print(f"Found queue position in status div: {queue_position}")
                
                if not queue_time_str:
                    time_in_status = re.search(r'ca\.\s*(\d+)\s*min', status_html, re.IGNORECASE)
                    if time_in_status:
                        queue_time_str = f"ca. {time_in_status.group(1)} min"
                        print(f"Found queue time in status div: {queue_time_str}")
    except Exception as e:
        print(f"Error parsing HTML: {e}")
        import traceback
        traceback.print_exc()
    
    return queue_position, queue_time_str

def parse_countdown_from_html(html_content):
    """Parse countdown timer from Aternos HTML (format: M:SS or SS)"""
    countdown_seconds = None
    extend_button_exists = False
    
    try:
        # First, check if extend button exists (indicates countdown <= 60 seconds)
        if 'server-extend-end' in html_content or 'btn btn-tiny btn-success server-extend-end' in html_content:
            extend_button_exists = True
            print("✅ Extend button found in HTML - countdown is <= 60 seconds")
        
        # Try using BeautifulSoup if available
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find countdown: <div class="server-end-countdown">0:35</div>
            # Also check for bis_skin_checked attribute
            countdown_elem = soup.find('div', class_=lambda x: x and 'server-end-countdown' in x)
            if not countdown_elem:
                # Try finding by text pattern
                countdown_elem = soup.find('div', string=re.compile(r'\d+:\d+'))
            
            if countdown_elem:
                countdown_text = countdown_elem.get_text(strip=True)
                if countdown_text:
                    # Parse format like "0:35" or "35"
                    if ':' in countdown_text:
                        parts = countdown_text.split(':')
                        if len(parts) == 2:
                            try:
                                minutes = int(parts[0])
                                seconds = int(parts[1])
                                countdown_seconds = minutes * 60 + seconds
                            except ValueError:
                                pass
                    else:
                        # Just seconds
                        try:
                            countdown_seconds = int(countdown_text)
                        except ValueError:
                            pass
                    
                    if countdown_seconds is not None:
                        print(f"Found countdown in HTML: {countdown_text} ({countdown_seconds}s)")
        except ImportError:
            # BeautifulSoup not available, use regex
            pass
        except Exception as e:
            print(f"Error with BeautifulSoup, trying regex: {e}")
        
        # Always try regex as fallback
        if countdown_seconds is None:
            # Pattern for countdown: <div class="server-end-countdown">0:35</div>
            # Handle bis_skin_checked attribute
            countdown_match = re.search(r'<div[^>]*class="[^"]*server-end-countdown[^"]*"[^>]*>([^<]+)</div>', html_content, re.IGNORECASE | re.DOTALL)
            if countdown_match:
                countdown_text = countdown_match.group(1).strip()
                # Parse format like "0:35" or "35"
                if ':' in countdown_text:
                    parts = countdown_text.split(':')
                    if len(parts) == 2:
                        try:
                            minutes = int(parts[0])
                            seconds = int(parts[1])
                            countdown_seconds = minutes * 60 + seconds
                        except ValueError:
                            pass
                else:
                    # Just seconds
                    try:
                        countdown_seconds = int(countdown_text)
                    except ValueError:
                        pass
                
                if countdown_seconds is not None:
                    print(f"Found countdown in HTML (regex): {countdown_text} ({countdown_seconds}s)")
        
        # If extend button exists but we couldn't parse countdown, assume it's <= 60 seconds
        if extend_button_exists and countdown_seconds is None:
            print("⚠️ Extend button found but couldn't parse exact countdown, assuming <= 60 seconds")
            countdown_seconds = 60  # Set to 60 as a safe default when button is visible
        
    except Exception as e:
        print(f"Error parsing countdown HTML: {e}")
        import traceback
        traceback.print_exc()
    
    return countdown_seconds

async def check_extend_button_exists(aternos_server):
    """Check if extend button exists in HTML (indicates countdown <= 60 seconds)"""
    try:
        if hasattr(aternos_server, 'atconn') and hasattr(aternos_server, 'servid'):
            atconn = aternos_server.atconn
            server_id = aternos_server.servid
            
            # Try multiple URLs
            urls_to_try = [
                f'https://aternos.org/server/?id={server_id}',
                'https://aternos.org/server/',
            ]
            
            if hasattr(atconn, 'session'):
                session = atconn.session
                import aiohttp
                import requests
                
                for panel_url in urls_to_try:
                    try:
                        html_content = None
                        if isinstance(session, aiohttp.ClientSession):
                            async with session.get(panel_url) as response:
                                if response.status == 200:
                                    html_content = await response.text()
                        elif isinstance(session, requests.Session):
                            loop = asyncio.get_event_loop()
                            response = await loop.run_in_executor(None, session.get, panel_url)
                            if response.status_code == 200:
                                html_content = response.text
                        
                        if html_content:
                            # Try multiple search patterns for the extend button
                            button_patterns = [
                                'server-extend-end',
                                'btn btn-tiny btn-success server-extend-end',
                                'server-extend-end',
                                'class="extend"',
                                'server-extend',
                                'extend-end',
                                'fas fa-plus',
                            ]
                            
                            for pattern in button_patterns:
                                if pattern in html_content:
                                    print(f"✅ Extend button found using pattern: '{pattern}'")
                                    return True
                            
                            # Also check for the countdown div which appears with the button
                            if 'server-end-countdown' in html_content:
                                # If countdown exists, check if extend div is nearby
                                # The extend button appears in the same section as countdown
                                if 'extend' in html_content.lower() or 'fa-plus' in html_content:
                                    print(f"✅ Extend button likely exists (found countdown + extend references)")
                                    return True
                    except Exception as e:
                        print(f"Error checking extend button from {panel_url}: {e}")
                        continue
    except Exception as e:
        print(f"Error in check_extend_button_exists: {e}")
        import traceback
        traceback.print_exc()
    
    return False

async def fetch_countdown_and_button(aternos_server):
    """Fetch countdown timer and check for extend button from Aternos panel page HTML"""
    countdown_seconds = None
    extend_button_exists = False
    
    try:
        # First, try to get countdown from server status object (most reliable)
        # JavaScript shows: COUNTDOWN_END = status.countdown ? status.countdown + Math.round(Date.now() / 1000) : false;
        if hasattr(aternos_server, '_info'):
            info_data = getattr(aternos_server, '_info')
            if isinstance(info_data, dict):
                # Check for countdown in status
                countdown_from_status = info_data.get('countdown', None)
                if countdown_from_status is not None:
                    try:
                        # Countdown is seconds until server stops
                        countdown_seconds = int(countdown_from_status)
                        print(f"✅ Found countdown from status object: {countdown_seconds}s")
                    except (ValueError, TypeError):
                        pass
        
        # Also check server attributes directly
        if countdown_seconds is None:
            if hasattr(aternos_server, 'countdown'):
                try:
                    countdown_seconds = int(aternos_server.countdown)
                    print(f"✅ Found countdown from server attribute: {countdown_seconds}s")
                except (ValueError, TypeError):
                    pass
        
        # If we have countdown and it's <= 60, button should be visible
        if countdown_seconds is not None and countdown_seconds <= 60:
            extend_button_exists = True
            print(f"✅ Countdown is {countdown_seconds}s (<= 60s), extend button should be visible")
        
        # Also fetch HTML to double-check button visibility
        if hasattr(aternos_server, 'atconn') and hasattr(aternos_server, 'servid'):
            atconn = aternos_server.atconn
            server_id = aternos_server.servid
            
            # Try multiple URLs - prioritize server-specific URL
            urls_to_try = [
                f'https://aternos.org/server/?id={server_id}',  # Server-specific (most reliable)
                'https://aternos.org/server/',  # Main panel
            ]
            
            # Use the session from atconn
            if hasattr(atconn, 'session'):
                session = atconn.session
                import aiohttp
                import requests
                
                for panel_url in urls_to_try:
                    try:
                        html_content = None
                        if isinstance(session, aiohttp.ClientSession):
                            # Async aiohttp session
                            async with session.get(panel_url) as response:
                                if response.status == 200:
                                    html_content = await response.text()
                        elif isinstance(session, requests.Session):
                            # Sync requests session
                            loop = asyncio.get_event_loop()
                            response = await loop.run_in_executor(None, session.get, panel_url)
                            if response.status_code == 200:
                                html_content = response.text
                        
                        if html_content:
                            # Check for extend button first (more reliable indicator)
                            button_patterns = [
                                'server-extend-end',
                                'btn btn-tiny btn-success server-extend-end',
                                'class="extend"',
                                'server-extend',
                                'extend-end',
                                'fas fa-plus',
                            ]
                            
                            for pattern in button_patterns:
                                if pattern in html_content:
                                    extend_button_exists = True
                                    print(f"✅ Extend button found using pattern: '{pattern}'")
                                    break
                            
                            # Also check for countdown div which appears with the button
                            if 'server-end-countdown' in html_content:
                                # If countdown exists, check if extend div is nearby
                                if 'extend' in html_content.lower() or 'fa-plus' in html_content:
                                    extend_button_exists = True
                                    print(f"✅ Extend button likely exists (found countdown + extend references)")
                            
                            # Parse countdown from HTML if we don't have it yet
                            if countdown_seconds is None:
                                countdown_seconds = parse_countdown_from_html(html_content)
                            
                            if countdown_seconds is not None or extend_button_exists:
                                print(f"✅ Successfully fetched data from {panel_url}")
                                break
                    except Exception as e:
                        print(f"Error fetching {panel_url}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
    except Exception as e:
        print(f"Error in fetch_countdown_and_button: {e}")
        import traceback
        traceback.print_exc()
    
    return countdown_seconds, extend_button_exists

def get_players_online(aternos_server):
    """Get number of players currently online"""
    try:
        players_list = getattr(aternos_server, 'players_list', None)
        if players_list is not None:
            if isinstance(players_list, list):
                return len(players_list)
            elif isinstance(players_list, (int, str)):
                return int(players_list)
        return 0
    except Exception as e:
        print(f"Error getting players online: {e}")
        return 0

async def extend_server_time(aternos_server):
    """Extend server time by clicking the extend button"""
    try:
        if hasattr(aternos_server, 'atconn') and hasattr(aternos_server, 'servid'):
            atconn = aternos_server.atconn
            server_id = aternos_server.servid
            
            # Try multiple extend endpoints - CORRECT ENDPOINT: /ajax/server/extend-end
            extend_urls = [
                'https://aternos.org/ajax/server/extend-end',  # CORRECT endpoint from JavaScript
                f'https://aternos.org/ajax/server/extend-end?id={server_id}',
                'https://aternos.org/ajax/server/extend',  # Fallback
                f'https://aternos.org/ajax/server/extend?id={server_id}',
            ]
            
            if hasattr(atconn, 'request_cloudflare'):
                for extend_url in extend_urls:
                    try:
                        # Try POST request to extend endpoint (matches JavaScript: aget('/ajax/server/extend-end'))
                        print(f"   Trying POST to {extend_url}...")
                        response = atconn.request_cloudflare(extend_url, 'POST')
                        if response is not None:
                            # Check if response indicates success (JavaScript checks: data.success)
                            if isinstance(response, dict):
                                # JavaScript expects: if (!data.success) { ... }
                                if response.get('success', False) is True:
                                    print(f"✅✅✅ Server time extended successfully via {extend_url}!")
                                    return True
                                elif response.get('status') == 'success' or 'success' in str(response).lower():
                                    print(f"✅✅✅ Server time extended successfully via {extend_url}!")
                                    return True
                            elif isinstance(response, str):
                                # Try to parse as JSON
                                try:
                                    import json
                                    parsed = json.loads(response)
                                    if isinstance(parsed, dict) and parsed.get('success', False) is True:
                                        print(f"✅✅✅ Server time extended successfully via {extend_url}!")
                                        return True
                                except:
                                    pass
                                if 'success' in response.lower() or 'ok' in response.lower():
                                    print(f"✅✅✅ Server time extended successfully via {extend_url}!")
                                    return True
                            else:
                                # Any response is likely success
                                print(f"✅✅✅ Server time extended successfully via {extend_url}!")
                                return True
                    except Exception as post_err:
                        print(f"   POST to {extend_url} failed: {post_err}")
                        # Try GET as fallback
                        try:
                            response = atconn.request_cloudflare(extend_url, 'GET')
                            if response is not None:
                                print(f"✅✅✅ Server time extended successfully via {extend_url} (GET)!")
                                return True
                        except Exception as get_err:
                            print(f"   GET to {extend_url} also failed: {get_err}")
                            continue
            
            # Try direct session POST
            if hasattr(atconn, 'session'):
                session = atconn.session
                import requests
                if isinstance(session, requests.Session):
                    for extend_url in extend_urls:
                        try:
                            loop = asyncio.get_event_loop()
                            response = await loop.run_in_executor(None, lambda: session.post(extend_url, data={}, timeout=10))
                            if response.status_code in [200, 201]:
                                # Check response content for success
                                try:
                                    response_data = response.json()
                                    if isinstance(response_data, dict) and response_data.get('success', False) is True:
                                        print(f"✅✅✅ Server time extended successfully via {extend_url} (direct POST)!")
                                        return True
                                    elif response.status_code == 200:
                                        # 200 status usually means success
                                        print(f"✅✅✅ Server time extended successfully via {extend_url} (direct POST)!")
                                        return True
                                except:
                                    # If JSON parsing fails, assume success on 200 status
                                    if response.status_code == 200:
                                        print(f"✅✅✅ Server time extended successfully via {extend_url} (direct POST)!")
                                        return True
                        except Exception as session_err:
                            print(f"   Direct session POST to {extend_url} failed: {session_err}")
                            continue
    except Exception as e:
        print(f"Error extending server time: {e}")
        import traceback
        traceback.print_exc()
    
    return False

async def monitor_auto_start(guild_id):
    """Background task to monitor server and auto-start if it goes offline"""
    print(f"🔄 Auto-start monitoring started for guild {guild_id}")
    last_status = None
    
    while True:
        try:
            # Check if auto-start is still enabled
            if not get_auto_start_enabled(guild_id):
                print(f"⏸️ Auto-start disabled for guild {guild_id}, stopping monitor")
                if str(guild_id) in auto_start_tasks:
                    del auto_start_tasks[str(guild_id)]
                return
            
            # Get server
            aternos_server = server_servers.get(str(guild_id))
            if not aternos_server:
                # Server not configured, wait longer before retry
                await asyncio.sleep(60)
                continue
            
            try:
                # Refresh server status
                aternos_server.fetch()
                current_status = aternos_server.status
                
                # Only log status changes
                if current_status != last_status:
                    print(f"📊 Server status for guild {guild_id}: {current_status}")
                    last_status = current_status
                
                # Check if server needs confirmation (works for any status, including "waiting")
                confirm_needed = False
                confirm_reason = None
                
                try:
                    # Use the same comprehensive detection as monitor_queue
                    if hasattr(aternos_server, '_info'):
                        info_data = getattr(aternos_server, '_info')
                        if isinstance(info_data, dict):
                            # PRIMARY CHECK: queue.pending == 'pending'
                            if 'queue' in info_data:
                                queue_info = info_data.get('queue', {})
                                if isinstance(queue_info, dict):
                                    pending = queue_info.get('pending', '')
                                    position = queue_info.get('position', None)
                                    
                                    # CRITICAL: Only confirm when position is 1 or 0
                                    # Don't confirm just because pending='pending' - wait for position <= 1
                                    if position is not None:
                                        if position <= 1:
                                            # Position <= 1 means queue finished - ready to confirm
                                            if pending and str(pending).lower() == 'pending':
                                                confirm_needed = True
                                                confirm_reason = f"queue position={position}, pending='{pending}' (queue finished)"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                            elif 'confirm' in str(pending).lower():
                                                confirm_needed = True
                                                confirm_reason = f"queue position={position}, pending contains 'confirm': '{pending}'"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                            else:
                                                # Position is 1 but no pending status - still needs confirmation
                                                confirm_needed = True
                                                confirm_reason = f"queue position={position} (queue finished)"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                        elif position > 1:
                                            # Position > 1 means queue not finished yet - DO NOT confirm
                                            if pending and str(pending).lower() == 'pending':
                                                print(f"⏳ Queue position {position} with pending status - waiting for position 1 (not ready yet)")
                                    # If position is unknown/None, don't confirm based on pending alone
                                    # Wait until we have position information
                                    
                                    # Also check if position is very low (2-5) and status is waiting
                                    if not confirm_needed and position is not None and 2 <= position <= 5:
                                        if current_status == 'waiting':
                                            # Queue is almost done, check more frequently
                                            print(f"🔍 Queue position is {position}, monitoring closely...")
                            
                            # Check label, class, lang
                            if not confirm_needed:
                                label = info_data.get('label', '')
                                info_class = info_data.get('class', '')
                                lang = info_data.get('lang', '')
                                
                                if label:
                                    label_lower = str(label).lower()
                                    if 'confirm' in label_lower:
                                        confirm_needed = True
                                        confirm_reason = f"label contains 'confirm': '{label}'"
                                        print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                    elif 'pending' in label_lower and 'waiting' not in label_lower:
                                        confirm_needed = True
                                        confirm_reason = f"label contains 'pending': '{label}'"
                                        print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                
                                if not confirm_needed and info_class:
                                    class_lower = str(info_class).lower()
                                    if 'confirm' in class_lower or 'queueconfirm' in class_lower:
                                        confirm_needed = True
                                        confirm_reason = f"class contains 'confirm': '{info_class}'"
                                        print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                    elif 'pending' in class_lower and 'queueing' not in class_lower:
                                        confirm_needed = True
                                        confirm_reason = f"class contains 'pending': '{info_class}'"
                                        print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                            
                            # Check status_num
                            if not confirm_needed:
                                status_num = info_data.get('status', None)
                                if status_num is not None and status_num != 10:  # 10 = waiting
                                    if 'queue' in info_data:
                                        queue_info = info_data.get('queue', {})
                                        if isinstance(queue_info, dict):
                                            pending = queue_info.get('pending', '')
                                            if pending and str(pending).lower() == 'pending':
                                                confirm_needed = True
                                                confirm_reason = f"status_num={status_num}, pending='{pending}'"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                    
                    # Check css_class
                    if not confirm_needed and hasattr(aternos_server, 'css_class'):
                        css_class = str(aternos_server.css_class)
                        css_class_lower = css_class.lower()
                        if 'confirm' in css_class_lower or 'queueconfirm' in css_class_lower:
                            if 'queueing' not in css_class_lower:
                                confirm_needed = True
                                confirm_reason = f"css_class='{css_class}'"
                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                        elif 'pending' in css_class_lower:
                            if css_class_lower != 'queueing' and 'queueing' not in css_class_lower:
                                confirm_needed = True
                                confirm_reason = f"css_class contains 'pending': '{css_class}'"
                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                    
                    # Check is_confirm_required
                    if not confirm_needed and hasattr(aternos_server, 'is_confirm_required'):
                        try:
                            if aternos_server.is_confirm_required:
                                confirm_needed = True
                                confirm_reason = "is_confirm_required=True"
                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                        except:
                            pass
                            
                except Exception as check_error:
                    print(f"⚠️ Error checking confirmation need: {check_error}")
                    import traceback
                    traceback.print_exc()
                
                # If confirmation is needed, try to confirm automatically with retries
                if confirm_needed:
                    print(f"🚨🚨🚨 CONFIRMATION REQUIRED - REASON: {confirm_reason} 🚨🚨🚨")
                    print(f"🚀 Attempting AUTOMATIC confirmation for guild {guild_id} (no manual interaction needed)...")
                    
                    # Wait a moment to ensure server is ready for confirmation
                    await asyncio.sleep(2)
                    
                    auto_confirm_success = False
                    max_retries = 3  # Reduced retries to avoid spam
                    last_reauth_time = 0
                    
                    for retry in range(max_retries):
                        try:
                            # Refresh server status first
                            try:
                                aternos_server.fetch()
                                
                                # Double-check that confirmation is still needed and queue is ready
                                queue_ready = False
                                if hasattr(aternos_server, '_info'):
                                    info_data = getattr(aternos_server, '_info')
                                    if isinstance(info_data, dict) and 'queue' in info_data:
                                        queue_info = info_data.get('queue', {})
                                        if isinstance(queue_info, dict):
                                            position = queue_info.get('position', None)
                                            pending = queue_info.get('pending', '')
                                            # Only proceed if position is 1 or 0
                                            if position is not None and position <= 1:
                                                if pending and str(pending).lower() == 'pending':
                                                    queue_ready = True
                                                elif position == 1:
                                                    # Position 1 usually means ready
                                                    queue_ready = True
                                
                                if not queue_ready:
                                    print(f"   Queue not ready yet (position might be > 1). Waiting...")
                                    await asyncio.sleep(3)
                                    continue
                            except Exception as fetch_err:
                                print(f"   Fetch error: {fetch_err}")
                            
                            if hasattr(aternos_server, 'atconn'):
                                atconn = aternos_server.atconn
                                server_id = getattr(aternos_server, 'servid', None)
                                
                                # Method 1: Try library confirm() method FIRST (most reliable)
                                if hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm):
                                    try:
                                        print(f"   Attempt {retry + 1}/{max_retries}: Trying library confirm() method...")
                                        aternos_server.confirm()
                                        auto_confirm_success = True
                                        print(f"✅✅✅ AUTO-CONFIRMED (library method) for guild {guild_id}!")
                                        break
                                    except Exception as lib_err:
                                        error_str = str(lib_err)
                                        print(f"   Library confirm() failed: {lib_err}")
                                        # Don't re-auth on 400 errors - might just mean not ready yet
                                        # Only re-auth once per confirmation attempt to avoid spam
                                        import time
                                        current_time = time.time()
                                        if ('401' in error_str or 'token' in error_str.lower()) and (current_time - last_reauth_time) > 10:
                                            print(f"   Token error detected, re-authenticating...")
                                            last_reauth_time = current_time
                                            await connect_to_aternos(guild_id)
                                            aternos_server = server_servers.get(str(guild_id))
                                            if aternos_server:
                                                aternos_server.fetch()
                                        elif '400' in error_str:
                                            # 400 might mean not ready yet, wait and retry
                                            print(f"   400 error - server might not be ready yet, waiting...")
                                            await asyncio.sleep(5)  # Wait longer for 400 errors
                                
                                # Method 2: Try request_cloudflare with server ID
                                if not auto_confirm_success and hasattr(atconn, 'request_cloudflare'):
                                    try:
                                        # Build confirm URL with server ID if available
                                        if server_id:
                                            confirm_url = f'https://aternos.org/ajax/server/confirm?id={server_id}'
                                        else:
                                            confirm_url = 'https://aternos.org/ajax/server/confirm'
                                        
                                        print(f"   Attempt {retry + 1}/{max_retries}: Trying POST request to {confirm_url}...")
                                        
                                        # Try POST first (more reliable for confirmations)
                                        try:
                                            response = atconn.request_cloudflare(confirm_url, 'POST')
                                            if response is not None:
                                                auto_confirm_success = True
                                                print(f"✅✅✅ AUTO-CONFIRMED (POST) for guild {guild_id}!")
                                                break
                                        except Exception as post_err:
                                            error_str = str(post_err)
                                            print(f"   POST failed: {post_err}")
                                            # If 400 error, might not be ready - wait before retry
                                            if '400' in error_str:
                                                print(f"   400 error - waiting before retry...")
                                                await asyncio.sleep(3)
                                            else:
                                                # Try GET as fallback for other errors
                                                try:
                                                    response = atconn.request_cloudflare(confirm_url, 'GET')
                                                    if response is not None:
                                                        auto_confirm_success = True
                                                        print(f"✅✅✅ AUTO-CONFIRMED (GET) for guild {guild_id}!")
                                                        break
                                                except Exception as get_err:
                                                    print(f"   GET also failed: {get_err}")
                                    
                                    except Exception as cf_error:
                                        print(f"   request_cloudflare failed: {cf_error}")
                                
                                # Method 3: Direct session POST with proper data
                                if not auto_confirm_success and hasattr(atconn, 'session'):
                                    try:
                                        session = atconn.session
                                        if server_id:
                                            confirm_url = f'https://aternos.org/ajax/server/confirm?id={server_id}'
                                        else:
                                            confirm_url = 'https://aternos.org/ajax/server/confirm'
                                        
                                        print(f"   Attempt {retry + 1}/{max_retries}: Trying direct session POST...")
                                        
                                        import requests
                                        if isinstance(session, requests.Session):
                                            loop = asyncio.get_event_loop()
                                            # Try POST with empty data
                                            response = await loop.run_in_executor(None, lambda: session.post(confirm_url, data={}, timeout=10))
                                            if response.status_code in [200, 201]:
                                                auto_confirm_success = True
                                                print(f"✅✅✅ AUTO-CONFIRMED (direct POST) for guild {guild_id}!")
                                                break
                                    except Exception as session_err:
                                        print(f"   Direct session POST failed: {session_err}")
                            else:
                                # No atconn, try library method directly
                                if hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm):
                                    try:
                                        print(f"   Attempt {retry + 1}/{max_retries}: Trying library confirm() method (no atconn)...")
                                        aternos_server.confirm()
                                        auto_confirm_success = True
                                        print(f"✅✅✅ AUTO-CONFIRMED (library method) for guild {guild_id}!")
                                        break
                                    except Exception as lib_err:
                                        print(f"   Library confirm() failed: {lib_err}")
                            
                            # If we got here and didn't succeed, wait before retry
                            if not auto_confirm_success and retry < max_retries - 1:
                                wait_time = (retry + 1) * 2  # Exponential backoff: 2s, 4s, 6s, 8s
                                print(f"   Waiting {wait_time} seconds before retry...")
                                await asyncio.sleep(wait_time)
                                
                        except Exception as confirm_error:
                            print(f"   Error in auto-confirm attempt {retry + 1}: {confirm_error}")
                            import traceback
                            traceback.print_exc()
                            if retry < max_retries - 1:
                                wait_time = (retry + 1) * 2
                                await asyncio.sleep(wait_time)
                    
                    if auto_confirm_success:
                        # Confirmation successful - wait and check status
                        print(f"✅ Confirmation sent! Checking server status...")
                        await asyncio.sleep(3)
                        try:
                            aternos_server.fetch()
                            new_status = aternos_server.status
                            print(f"📡 Server status after confirmation: {new_status}")
                        except:
                            pass
                        # Continue monitoring
                        continue
                    else:
                        print(f"⚠️ All auto-confirmation attempts failed for guild {guild_id}, will retry on next check")
                        # Continue monitoring - might succeed on next iteration
                        continue
                
                # If server is offline, start it automatically
                if current_status == 'offline':
                    print(f"🔴 Server is offline for guild {guild_id}, auto-starting...")
                    
                    try:
                        # Start the server
                        aternos_server.start()
                        print(f"✅ Auto-start command sent for guild {guild_id}")
                        
                        # Wait a bit for status to update
                        await asyncio.sleep(5)
                        
                        # Check if it's in queue or starting
                        aternos_server.fetch()
                        new_status = aternos_server.status
                        
                        if new_status in ['waiting', 'starting', 'loading', 'loading_preparing']:
                            print(f"⏳ Server is now {new_status} for guild {guild_id}")
                        elif new_status == 'online':
                            print(f"🟢 Server is already online for guild {guild_id}")
                        else:
                            print(f"📡 Server status after auto-start: {new_status}")
                            
                    except Exception as start_error:
                        print(f"❌ Error auto-starting server for guild {guild_id}: {start_error}")
                
                # Auto-extend: If server is online and no players, check countdown and extend if < 60 seconds
                elif current_status == 'online':
                    try:
                        # Check if players are online
                        players_online = get_players_online(aternos_server)
                        
                        if players_online == 0:
                            # No players online - check countdown timer
                            print(f"👤 No players online for guild {guild_id}, checking countdown timer...")
                            
                            # Fetch countdown and check for button in one go (more efficient)
                            countdown_seconds, extend_button_exists = await fetch_countdown_and_button(aternos_server)
                            
                            # If button exists OR countdown < 60, extend
                            should_extend = False
                            reason = ""
                            
                            if extend_button_exists:
                                should_extend = True
                                reason = "extend button is visible"
                                if countdown_seconds is not None:
                                    reason += f" (countdown: {countdown_seconds}s)"
                            elif countdown_seconds is not None and countdown_seconds < 60:
                                should_extend = True
                                reason = f"countdown is {countdown_seconds}s (< 60s)"
                            
                            if should_extend:
                                print(f"🚨 Extending server time - {reason}...")
                                
                                extend_success = await extend_server_time(aternos_server)
                                
                                if extend_success:
                                    print(f"✅ Server time extended by 1 minute for guild {guild_id}")
                                    # Wait a bit for the countdown to update
                                    await asyncio.sleep(3)
                                else:
                                    print(f"⚠️ Failed to extend server time for guild {guild_id}, will retry on next check")
                            else:
                                if countdown_seconds is not None:
                                    print(f"✅ Countdown is {countdown_seconds}s (>= 60s), no extension needed")
                                elif extend_button_exists:
                                    # Button exists but we couldn't parse countdown - extend anyway
                                    print(f"🚨 Extend button visible but couldn't parse countdown, extending anyway...")
                                    extend_success = await extend_server_time(aternos_server)
                                    if extend_success:
                                        print(f"✅ Server time extended by 1 minute for guild {guild_id}")
                                        await asyncio.sleep(3)
                                else:
                                    print(f"ℹ️ Could not fetch countdown timer for guild {guild_id} (button not visible, countdown likely > 60s)")
                        else:
                            # Players are online, no need to extend
                            print(f"👥 {players_online} player(s) online for guild {guild_id}, no extension needed")
                    except Exception as extend_error:
                        print(f"⚠️ Error in auto-extend check for guild {guild_id}: {extend_error}")
                        import traceback
                        traceback.print_exc()
                
                # Adjust wait time based on server status
                # If server is waiting and might need confirmation soon, check more frequently
                wait_time = 5
                if current_status == 'waiting':
                    # Check if queue position is low (might need confirmation soon)
                    if hasattr(aternos_server, '_info'):
                        info_data = getattr(aternos_server, '_info')
                        if isinstance(info_data, dict) and 'queue' in info_data:
                            queue_info = info_data.get('queue', {})
                            if isinstance(queue_info, dict):
                                position = queue_info.get('position', None)
                                if position is not None and position <= 5:
                                    # Queue is close to finishing, check every 2 seconds
                                    wait_time = 2
                                    print(f"⏱️ Queue position {position}, checking every {wait_time}s for confirmation...")
                
                await asyncio.sleep(wait_time)
                
            except Exception as fetch_error:
                print(f"⚠️ Error fetching server status for guild {guild_id}: {fetch_error}")
                # Wait longer on error
                await asyncio.sleep(60)
                
        except asyncio.CancelledError:
            print(f"🛑 Auto-start monitoring cancelled for guild {guild_id}")
            if str(guild_id) in auto_start_tasks:
                del auto_start_tasks[str(guild_id)]
            return
        except Exception as e:
            print(f"❌ Error in auto-start monitor for guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            # Wait longer on error
            await asyncio.sleep(60)

async def monitor_queue(ctx, loading_msg, aternos_server, guild_id):
    """Monitor queue status with real-time updates"""
    try:
        start_time = time.time()
        last_queue_time = None
        last_queue_position = None
        last_queue_time_str = None
        static_queue_time_str = None  # Store the static "ca. X min" value
        
        while True:
            try:
                # Refresh server status
                aternos_server.fetch()
                current_status = aternos_server.status
                
                # Debug: Print status and key indicators
                print(f"Status: {current_status}")
                
                # Comprehensive debug output when checking for confirmation
                if hasattr(aternos_server, '_info'):
                    info_data = getattr(aternos_server, '_info')
                    if isinstance(info_data, dict) and 'queue' in info_data:
                        queue_info = info_data.get('queue', {})
                        if isinstance(queue_info, dict):
                            pending = queue_info.get('pending', '')
                            position = queue_info.get('position', None)
                            if pending or (position is not None and position <= 5):
                                print(f"🔍 CONFIRM CHECK: status={current_status}, pending='{pending}', position={position}, css_class={getattr(aternos_server, 'css_class', 'N/A')}")
                
                # ========================================================================
                # COMPREHENSIVE CONFIRMATION DETECTION - CHECK FIRST, BEFORE QUEUE STATUS
                # ========================================================================
                # This section checks EVERY possible indicator that confirmation is needed
                # Multiple fallbacks ensure instant detection when website shows "Confirm now!"
                # ========================================================================
                confirm_required = False
                confirm_reason = None
                
                try:
                    # ====================================================================
                    # METHOD 1: Check _info['queue']['pending'] - PRIMARY INDICATOR
                    # ====================================================================
                    if hasattr(aternos_server, '_info'):
                        info_data = getattr(aternos_server, '_info')
                        if isinstance(info_data, dict):
                            # Check queue data in _info
                            if 'queue' in info_data:
                                queue_info = info_data['queue']
                                if isinstance(queue_info, dict):
                                    # PRIMARY CHECK: pending status
                                    pending = queue_info.get('pending', '')
                                    position = queue_info.get('position', None)
                                    count = queue_info.get('count', None)
                                    queue_status = queue_info.get('queue', None)
                                    
                                    # Check 1.1: pending == 'pending' (most reliable)
                                    if pending:
                                        pending_lower = str(pending).lower()
                                        if pending_lower == 'pending':
                                            confirm_required = True
                                            confirm_reason = f"queue.pending='{pending}'"
                                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                        
                                        # Check 1.2: 'confirm' in pending
                                        elif 'confirm' in pending_lower:
                                            confirm_required = True
                                            confirm_reason = f"queue.pending contains 'confirm': '{pending}'"
                                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                    
                                    # Check 1.3: Position is 1 or 0 (queue finished)
                                    if not confirm_required and position is not None:
                                        if position <= 1:
                                            # Position 1 or 0 + pending = needs confirmation
                                            if pending and str(pending).lower() == 'pending':
                                                confirm_required = True
                                                confirm_reason = f"queue position={position}, pending='{pending}'"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                            # Position <= 1 = queue finished, needs confirmation
                                            elif position == 1:
                                                confirm_required = True
                                                confirm_reason = f"queue position={position} (queue finished), status={current_status}"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                            # Position 0 = definitely needs confirmation
                                            elif position == 0:
                                                confirm_required = True
                                                confirm_reason = f"queue position={position} (queue finished), status={current_status}"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                    
                                    # Check 1.4: Queue status changed
                                    if not confirm_required and queue_status is not None:
                                        if queue_status != 2 and position is not None and position <= 1:
                                            confirm_required = True
                                            confirm_reason = f"queue.queue={queue_status}, position={position}"
                                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                    
                                    # Debug logging for low positions
                                    if position is not None and position <= 10:
                                        print(f"🔍 DEBUG: position={position}, pending='{pending}', status={current_status}, queue={queue_status}")
                            
                            # ============================================================
                            # METHOD 2: Check _info['label'] and _info['class']
                            # ============================================================
                            label = info_data.get('label', '')
                            info_class = info_data.get('class', '')
                            lang = info_data.get('lang', '')
                            
                            # Check 2.1: Label contains confirm/pending
                            if not confirm_required and label:
                                label_lower = str(label).lower()
                                if 'confirm' in label_lower:
                                    confirm_required = True
                                    confirm_reason = f"label contains 'confirm': '{label}'"
                                    print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                elif 'pending' in label_lower and 'waiting' not in label_lower:
                                    confirm_required = True
                                    confirm_reason = f"label contains 'pending': '{label}'"
                                    print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                            
                            # Check 2.2: Class contains confirm/pending/queueconfirm
                            if not confirm_required and info_class:
                                class_lower = str(info_class).lower()
                                if 'confirm' in class_lower or 'queueconfirm' in class_lower:
                                    confirm_required = True
                                    confirm_reason = f"class contains 'confirm': '{info_class}'"
                                    print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                elif 'pending' in class_lower and 'queueing' not in class_lower:
                                    confirm_required = True
                                    confirm_reason = f"class contains 'pending': '{info_class}'"
                                    print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                            
                            # Check 2.3: Lang field
                            if not confirm_required and lang:
                                lang_lower = str(lang).lower()
                                if 'confirm' in lang_lower or 'pending' in lang_lower:
                                    if 'waiting' not in lang_lower:
                                        confirm_required = True
                                        confirm_reason = f"lang contains confirm/pending: '{lang}'"
                                        print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                            
                            # ============================================================
                            # METHOD 3: Check status_num and status changes
                            # ============================================================
                            status_num = info_data.get('status', None)
                            if not confirm_required and status_num is not None:
                                # Status 10 = waiting, other statuses might indicate confirmation needed
                                if status_num != 10:  # Not waiting
                                    if current_status != 'online' and current_status != 'starting' and current_status != 'offline':
                                        # Check if queue has pending status
                                        if 'queue' in info_data:
                                            queue_info = info_data.get('queue', {})
                                            if isinstance(queue_info, dict):
                                                pending = queue_info.get('pending', '')
                                                if pending and str(pending).lower() == 'pending':
                                                    confirm_required = True
                                                    confirm_reason = f"status_num={status_num}, pending='{pending}'"
                                                    print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                            
                            # ============================================================
                            # METHOD 4: Check all _info keys for confirmation indicators
                            # ============================================================
                            if not confirm_required:
                                for key, value in info_data.items():
                                    if value and isinstance(value, (str, int)):
                                        value_str = str(value).lower()
                                        # Look for confirm/pending in any value
                                        if key != 'label' and key != 'class' and key != 'lang':
                                            if ('confirm' in value_str or 'pending' in value_str) and 'waiting' not in value_str:
                                                # Check if this is a meaningful indicator
                                                if key in ['message', 'text', 'status_text', 'action']:
                                                    confirm_required = True
                                                    confirm_reason = f"_info['{key}']='{value}'"
                                                    print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                                    break
                    
                    
                    # ============================================================
                    # METHOD 5: Check css_class attribute
                    # ============================================================
                    if not confirm_required and hasattr(aternos_server, 'css_class'):
                        css_class = str(aternos_server.css_class)
                        css_class_lower = css_class.lower()
                        
                        # Check 5.1: Contains confirm/queueconfirm
                        if 'confirm' in css_class_lower or 'queueconfirm' in css_class_lower:
                            if 'queueing' not in css_class_lower or css_class_lower != 'queueing':
                                confirm_required = True
                                confirm_reason = f"css_class='{css_class}'"
                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                        
                        # Check 5.2: Contains pending (but not just "queueing")
                        elif 'pending' in css_class_lower:
                            if css_class_lower != 'queueing' and 'queueing' not in css_class_lower:
                                confirm_required = True
                                confirm_reason = f"css_class contains 'pending': '{css_class}'"
                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                    
                    # ============================================================
                    # METHOD 6: Check status string
                    # ============================================================
                    if not confirm_required and current_status:
                        status_lower = str(current_status).lower()
                        
                        # Check 6.1: Status contains confirm
                        if 'confirm' in status_lower:
                            confirm_required = True
                            confirm_reason = f"status contains 'confirm': '{current_status}'"
                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                        
                        # Check 6.2: Status contains pending (but not waiting)
                        elif 'pending' in status_lower and 'waiting' not in status_lower:
                            confirm_required = True
                            confirm_reason = f"status contains 'pending': '{current_status}'"
                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                        
                        # Check 6.3: Status is queueconfirm
                        elif status_lower == 'queueconfirm':
                            confirm_required = True
                            confirm_reason = f"status='queueconfirm'"
                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                    
                    # ============================================================
                    # METHOD 7: Check status transitions (waiting -> something else)
                    # ============================================================
                    if not confirm_required:
                        # If status changed from waiting to something else (but not online/starting/offline)
                        if current_status not in ['waiting', 'online', 'starting', 'offline', 'stopping']:
                            # Check _info for pending status
                            if hasattr(aternos_server, '_info'):
                                info_data = getattr(aternos_server, '_info')
                                if isinstance(info_data, dict) and 'queue' in info_data:
                                    queue_info = info_data.get('queue', {})
                                    if isinstance(queue_info, dict):
                                        pending = queue_info.get('pending', '')
                                        position = queue_info.get('position', None)
                                        
                                        # If pending is set or position is 1, needs confirmation
                                        if pending and str(pending).lower() == 'pending':
                                            confirm_required = True
                                            confirm_reason = f"status changed to '{current_status}', pending='{pending}'"
                                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                        elif position is not None and position <= 1:
                                            confirm_required = True
                                            confirm_reason = f"status changed to '{current_status}', position={position}"
                                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                    
                    # ============================================================
                    # METHOD 8: Check countdown value
                    # ============================================================
                    if not confirm_required and hasattr(aternos_server, 'countdown'):
                        countdown = aternos_server.countdown
                        # Countdown 0 or None + not waiting/online = might need confirmation
                        if (countdown == 0 or countdown is None) and current_status not in ['waiting', 'online', 'starting', 'offline']:
                            # Double-check with _info
                            if hasattr(aternos_server, '_info'):
                                info_data = getattr(aternos_server, '_info')
                                if isinstance(info_data, dict) and 'queue' in info_data:
                                    queue_info = info_data.get('queue', {})
                                    if isinstance(queue_info, dict):
                                        pending = queue_info.get('pending', '')
                                        if pending and str(pending).lower() == 'pending':
                                            confirm_required = True
                                            confirm_reason = f"countdown={countdown}, pending='{pending}'"
                                            print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                    
                    # ============================================================
                    # METHOD 9: Check is_confirm_required attribute
                    # ============================================================
                    if not confirm_required and hasattr(aternos_server, 'is_confirm_required'):
                        try:
                            is_confirm = aternos_server.is_confirm_required
                            if is_confirm:
                                confirm_required = True
                                confirm_reason = "is_confirm_required=True"
                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                        except:
                            pass
                    
                    # ============================================================
                    # METHOD 10: Check all server attributes for confirmation indicators
                    # ============================================================
                    if not confirm_required:
                        # Check all non-private attributes
                        for attr_name in dir(aternos_server):
                            if not attr_name.startswith('_') and not callable(getattr(aternos_server, attr_name, None)):
                                try:
                                    attr_value = getattr(aternos_server, attr_name)
                                    if attr_value and isinstance(attr_value, str):
                                        attr_lower = attr_value.lower()
                                        # Look for confirm/pending in attribute values
                                        if ('confirm' in attr_lower or 'pending' in attr_lower) and 'waiting' not in attr_lower:
                                            # Check if this is a meaningful attribute
                                            if attr_name in ['status_text', 'message', 'action', 'button_text', 'label_text']:
                                                confirm_required = True
                                                confirm_reason = f"{attr_name}='{attr_value}'"
                                                print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                                break
                                except:
                                    pass
                    
                    # ============================================================
                    # METHOD 11: Final check - if position is 1 and status is not waiting
                    # ============================================================
                    if not confirm_required and hasattr(aternos_server, '_info'):
                        info_data = getattr(aternos_server, '_info')
                        if isinstance(info_data, dict) and 'queue' in info_data:
                            queue_info = info_data.get('queue', {})
                            if isinstance(queue_info, dict):
                                position = queue_info.get('position', None)
                                pending = queue_info.get('pending', '')
                                
                                # Check if queue finished (position <= 1) or has pending status
                                if position is not None and position <= 1:
                                    # Position 1 or 0 means queue finished - needs confirmation even if status is "waiting"
                                    if hasattr(aternos_server, 'confirm'):
                                        confirm_required = True
                                        confirm_reason = f"position={position} (queue finished), status={current_status}, confirm() method available"
                                        print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                                # Also check for pending status even if position is not 1
                                elif pending and str(pending).lower() == 'pending':
                                    # Pending status means confirmation needed
                                    confirm_required = True
                                    confirm_reason = f"queue pending='{pending}', status={current_status}"
                                    print(f"✅✅✅ CONFIRM DETECTED: {confirm_reason}")
                    
                    # ============================================================
                    # FINAL ACTION: Auto-confirm when detected (NO MANUAL CONFIRMATION NEEDED)
                    # ============================================================
                    if confirm_required:
                        print(f"🚨🚨🚨 CONFIRMATION REQUIRED - REASON: {confirm_reason} 🚨🚨🚨")
                        
                        # Try to confirm IMMEDIATELY and automatically (multiple attempts with retries)
                        print("🚀 Attempting AUTOMATIC confirmation (no manual interaction needed)...")
                        auto_confirm_success = False
                        max_retries = 5  # Increased retries
                        
                        for retry in range(max_retries):
                            try:
                                # Refresh server status and re-authenticate if needed
                                try:
                                    aternos_server.fetch()
                                except:
                                    # If fetch fails, try re-authenticating
                                    print(f"   Fetch failed, re-authenticating...")
                                    await connect_to_aternos(guild_id)
                                    aternos_server = server_servers.get(str(guild_id))
                                    if aternos_server:
                                        aternos_server.fetch()
                                
                                if hasattr(aternos_server, 'atconn'):
                                    atconn = aternos_server.atconn
                                    server_id = getattr(aternos_server, 'servid', None)
                                    
                                    # Method 1: Try library confirm() method FIRST (most reliable)
                                    if hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm):
                                        try:
                                            print(f"   Attempt {retry + 1}/{max_retries}: Trying library confirm() method...")
                                            aternos_server.confirm()
                                            auto_confirm_success = True
                                            print("✅✅✅ AUTOMATIC CONFIRMATION SUCCESSFUL (library method)!")
                                            break
                                        except Exception as lib_err:
                                            error_str = str(lib_err)
                                            print(f"   Library confirm() failed: {lib_err}")
                                            # If it's a token error, try re-auth
                                            if '400' in error_str or '401' in error_str or 'token' in error_str.lower():
                                                print(f"   Token error detected, re-authenticating...")
                                                await connect_to_aternos(guild_id)
                                                aternos_server = server_servers.get(str(guild_id))
                                                if aternos_server:
                                                    aternos_server.fetch()
                                    
                                    # Method 2: Try request_cloudflare with server ID
                                    if not auto_confirm_success and hasattr(atconn, 'request_cloudflare'):
                                        try:
                                            # Build confirm URL with server ID if available
                                            if server_id:
                                                confirm_url = f'https://aternos.org/ajax/server/confirm?id={server_id}'
                                            else:
                                                confirm_url = 'https://aternos.org/ajax/server/confirm'
                                            
                                            print(f"   Attempt {retry + 1}/{max_retries}: Trying POST request to {confirm_url}...")
                                            
                                            # Try POST first (more reliable for confirmations)
                                            try:
                                                response = atconn.request_cloudflare(confirm_url, 'POST')
                                                if response is not None:
                                                    auto_confirm_success = True
                                                    print("✅✅✅ AUTOMATIC CONFIRMATION SUCCESSFUL (POST)!")
                                                    break
                                            except Exception as post_err:
                                                print(f"   POST failed: {post_err}, trying GET...")
                                                try:
                                                    response = atconn.request_cloudflare(confirm_url, 'GET')
                                                    if response is not None:
                                                        auto_confirm_success = True
                                                        print("✅✅✅ AUTOMATIC CONFIRMATION SUCCESSFUL (GET)!")
                                                        break
                                                except Exception as get_err:
                                                    print(f"   GET also failed: {get_err}")
                                        
                                        except Exception as cf_error:
                                            print(f"   request_cloudflare failed: {cf_error}")
                                    
                                    # Method 3: Direct session POST with proper data
                                    if not auto_confirm_success and hasattr(atconn, 'session'):
                                        try:
                                            session = atconn.session
                                            if server_id:
                                                confirm_url = f'https://aternos.org/ajax/server/confirm?id={server_id}'
                                            else:
                                                confirm_url = 'https://aternos.org/ajax/server/confirm'
                                            
                                            print(f"   Attempt {retry + 1}/{max_retries}: Trying direct session POST...")
                                            
                                            import requests
                                            if isinstance(session, requests.Session):
                                                loop = asyncio.get_event_loop()
                                                # Try POST with empty data
                                                response = await loop.run_in_executor(None, lambda: session.post(confirm_url, data={}, timeout=10))
                                                if response.status_code in [200, 201]:
                                                    auto_confirm_success = True
                                                    print("✅✅✅ AUTOMATIC CONFIRMATION SUCCESSFUL (direct POST)!")
                                                    break
                                        except Exception as session_err:
                                            print(f"   Direct session POST failed: {session_err}")
                                else:
                                    # No atconn, try library method directly
                                    if hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm):
                                        try:
                                            print(f"   Attempt {retry + 1}/{max_retries}: Trying library confirm() method (no atconn)...")
                                            aternos_server.confirm()
                                            auto_confirm_success = True
                                            print("✅✅✅ AUTOMATIC CONFIRMATION SUCCESSFUL (library method)!")
                                            break
                                        except Exception as lib_err:
                                            print(f"   Library confirm() failed: {lib_err}")
                                
                                # If we got here and didn't succeed, wait before retry
                                if not auto_confirm_success and retry < max_retries - 1:
                                    wait_time = (retry + 1) * 2  # Exponential backoff: 2s, 4s, 6s, 8s
                                    print(f"   Waiting {wait_time} seconds before retry...")
                                    await asyncio.sleep(wait_time)
                                    
                            except Exception as confirm_error:
                                print(f"   Error in auto-confirm attempt {retry + 1}: {confirm_error}")
                                import traceback
                                traceback.print_exc()
                                if retry < max_retries - 1:
                                    wait_time = (retry + 1) * 2
                                    await asyncio.sleep(wait_time)
                        
                        if auto_confirm_success:
                            # Confirmation successful - update message and continue monitoring
                            await loading_msg.edit(content='✅ **Confirmation sent automatically!**\n⏳ Server is starting...\n\n_No manual confirmation needed!_')
                            # Wait a bit and check status
                            await asyncio.sleep(3)
                            try:
                                aternos_server.fetch()
                                new_status = aternos_server.status
                                print(f"📡 Server status after confirmation: {new_status}")
                            except:
                                pass
                            # Continue monitoring to see server go online
                            await asyncio.sleep(2)
                            continue
                        else:
                            # All auto-confirm attempts failed - still try to continue, but log the issue
                            print("⚠️⚠️⚠️ All auto-confirmation attempts failed, but continuing to monitor...")
                            await loading_msg.edit(content='⚠️ **Confirmation required but auto-confirm failed**\n⏳ Retrying automatically...')
                            # Wait a bit and continue monitoring - might succeed on next iteration
                            await asyncio.sleep(3)
                            continue
                except Exception as e:
                    print(f"Error checking confirmation: {e}")
                
                # Check for queue - Try different approaches
                queue_position = None
                queue_time = None
                queue_time_str = None
                in_queue = False
                
                # Approach 0: Check _info first (most reliable - contains queue data directly)
                try:
                    if hasattr(aternos_server, '_info'):
                        info_data = getattr(aternos_server, '_info')
                        if isinstance(info_data, dict) and 'queue' in info_data:
                            queue_info = info_data['queue']
                            if isinstance(queue_info, dict):
                                # Extract position and count
                                if 'position' in queue_info and 'count' in queue_info:
                                    pos = queue_info['position']
                                    count = queue_info['count']
                                    queue_position = f"{pos} / {count}"
                                    print(f"Found queue position in _info: {queue_position}")
                                
                                # Extract time (already in "ca. X min" format) - LOCK IT IN ONCE, NEVER UPDATE
                                if 'time' in queue_info:
                                    new_time_str = queue_info['time']
                                    # ONLY set static value if it's not set yet - NEVER UPDATE IT AFTER THAT
                                    if static_queue_time_str is None:
                                        static_queue_time_str = new_time_str
                                        print(f"🔒 LOCKED static queue time: {static_queue_time_str} (will never change)")
                                    # Always use the locked static value - ignore any new values from _info
                                    queue_time_str = static_queue_time_str
                                    # Also set queue_time for compatibility (convert to seconds)
                                    if 'minutes' in queue_info:
                                        queue_time = queue_info['minutes'] * 60
                                
                                in_queue = True
                                print(f"Queue data from _info: position={queue_position}, time={queue_time_str}")
                except Exception as e:
                    print(f"Error checking _info data: {e}")
                
                # Approach 1: Check status - "waiting" means in queue!
                if current_status in ['loading', 'loading_preparing', 'waiting', 'queue'] or 'queue' in str(current_status).lower():
                    in_queue = True
                
                # Approach 2: Check queue attribute
                try:
                    if hasattr(aternos_server, 'queue') and aternos_server.queue is not None:
                        in_queue = True
                        queue_obj = aternos_server.queue
                        
                        # Try different attribute names for position
                        for attr in ['position', 'pos', 'place', 'number']:
                            if hasattr(queue_obj, attr):
                                val = getattr(queue_obj, attr)
                                if val is not None:
                                    queue_position = val
                                    break
                        
                        # Try different attribute names for time
                        for attr in ['time', 'wait', 'estimated', 'estimate', 'eta']:
                            if hasattr(queue_obj, attr):
                                val = getattr(queue_obj, attr)
                                if val is not None:
                                    queue_time = val
                                    break
                        
                        if queue_position or queue_time:
                            print(f"Queue from attribute - Position: {queue_position}, Time: {queue_time}")
                except Exception as e:
                    print(f"Error checking queue attribute: {e}")
                
                # Approach 3: Check for queue_position directly on server
                try:
                    if hasattr(aternos_server, 'queue_position'):
                        queue_position = aternos_server.queue_position
                        in_queue = True
                except:
                    pass
                
                # Approach 4: Check for queue_time directly
                try:
                    if hasattr(aternos_server, 'queue_time'):
                        queue_time = aternos_server.queue_time
                        in_queue = True
                except:
                    pass
                
                # Approach 5: Try to get queue info from atserver methods
                try:
                    # Some versions use atserver.get_queue()
                    if hasattr(aternos_server, 'get_queue'):
                        queue_info = aternos_server.get_queue()
                        if queue_info:
                            print(f"Queue from get_queue(): {queue_info}")
                            in_queue = True
                except:
                    pass
                
                # Approach 6: Check for loading/waiting attributes
                try:
                    if hasattr(aternos_server, 'loading') and aternos_server.loading:
                        in_queue = True
                except:
                    pass
                
                # Approach 7: Try to get queue info from atconn (connection object) - Direct API call
                try:
                    if hasattr(aternos_server, 'atconn') and hasattr(aternos_server, 'servid'):
                        atconn = aternos_server.atconn
                        server_id = aternos_server.servid
                        
                        # Try multiple methods to get queue data
                        # Method 1: Using session.get() if available (could be requests or aiohttp)
                        if hasattr(atconn, 'session'):
                            try:
                                queue_url = f'https://aternos.org/panel/ajax/queue.php?id={server_id}'
                                print(f"Trying to fetch queue data from: {queue_url}")
                                
                                session = atconn.session
                                
                                # Check if it's aiohttp session (async) or requests session (sync)
                                import aiohttp
                                import requests
                                
                                if isinstance(session, aiohttp.ClientSession):
                                    # Async aiohttp session
                                    async with session.get(queue_url) as response:
                                        if response.status == 200:
                                            try:
                                                queue_data = await response.json()
                                                print(f"Queue API response (JSON): {queue_data}")
                                                
                                                if isinstance(queue_data, dict):
                                                    # Try different possible keys for position
                                                    for pos_key in ['position', 'pos', 'queue_pos', 'queue_position', 'current', 'now']:
                                                        if pos_key in queue_data:
                                                            pos_val = queue_data[pos_key]
                                                            if isinstance(pos_val, (int, str)) and str(pos_val).isdigit():
                                                                queue_position = int(pos_val)
                                                                print(f"Found queue position in API ({pos_key}): {queue_position}")
                                                                break
                                                    
                                                    # Try different possible keys for max position
                                                    for max_key in ['max', 'max_position', 'total', 'queue_max', 'max_queue']:
                                                        if max_key in queue_data:
                                                            max_val = queue_data[max_key]
                                                            if isinstance(max_val, (int, str)) and str(max_val).isdigit():
                                                                if queue_position is not None:
                                                                    queue_position = f"{queue_position}/{max_val}"
                                                                print(f"Found queue max in API ({max_key}): {max_val}")
                                                                break
                                                    
                                                    # Try different possible keys for time
                                                    for time_key in ['time', 'wait', 'eta', 'estimated', 'estimate', 'wait_time', 'queue_time']:
                                                        if time_key in queue_data:
                                                            time_val = queue_data[time_key]
                                                            if isinstance(time_val, (int, float)):
                                                                queue_time = int(time_val)
                                                                print(f"Found queue time in API ({time_key}): {queue_time}")
                                                                break
                                                            elif isinstance(time_val, str):
                                                                # Try to parse time string like "8 min" or "480"
                                                                import re
                                                                numbers = re.findall(r'\d+', time_val)
                                                                if numbers:
                                                                    num = int(numbers[0])
                                                                    if 'min' in time_val.lower():
                                                                        queue_time = num * 60
                                                                    else:
                                                                        queue_time = num
                                                                    print(f"Found queue time in API (parsed from '{time_key}'): {queue_time}")
                                                                    break
                                                    
                                                    in_queue = True
                                            except Exception as json_e:
                                                # Try text response
                                                text_data = await response.text()
                                                print(f"Queue API response (text): {text_data}")
                                        elif response.status == 503:
                                            # Service Unavailable - don't spam console, just skip this fetch
                                            pass  # Silently skip 503 errors
                                        else:
                                            # Only log non-503 errors
                                            if response.status != 503:
                                                print(f"Queue API returned status: {response.status}")
                                elif isinstance(session, requests.Session):
                                    # Sync requests session - run in executor to avoid blocking
                                    loop = asyncio.get_event_loop()
                                    response = await loop.run_in_executor(None, session.get, queue_url)
                                    if response.status_code == 200:
                                        try:
                                            queue_data = response.json()
                                            print(f"Queue API response (JSON): {queue_data}")
                                            
                                            if isinstance(queue_data, dict):
                                                # Same parsing logic as above
                                                for pos_key in ['position', 'pos', 'queue_pos', 'queue_position', 'current', 'now']:
                                                    if pos_key in queue_data:
                                                        pos_val = queue_data[pos_key]
                                                        if isinstance(pos_val, (int, str)) and str(pos_val).isdigit():
                                                            queue_position = int(pos_val)
                                                            print(f"Found queue position in API ({pos_key}): {queue_position}")
                                                            break
                                                
                                                for max_key in ['max', 'max_position', 'total', 'queue_max', 'max_queue']:
                                                    if max_key in queue_data:
                                                        max_val = queue_data[max_key]
                                                        if isinstance(max_val, (int, str)) and str(max_val).isdigit():
                                                            if queue_position is not None:
                                                                queue_position = f"{queue_position}/{max_val}"
                                                            print(f"Found queue max in API ({max_key}): {max_val}")
                                                            break
                                                
                                                for time_key in ['time', 'wait', 'eta', 'estimated', 'estimate', 'wait_time', 'queue_time']:
                                                    if time_key in queue_data:
                                                        time_val = queue_data[time_key]
                                                        if isinstance(time_val, (int, float)):
                                                            queue_time = int(time_val)
                                                            print(f"Found queue time in API ({time_key}): {queue_time}")
                                                            break
                                                        elif isinstance(time_val, str):
                                                            import re
                                                            numbers = re.findall(r'\d+', time_val)
                                                            if numbers:
                                                                num = int(numbers[0])
                                                                if 'min' in time_val.lower():
                                                                    queue_time = num * 60
                                                                else:
                                                                    queue_time = num
                                                                print(f"Found queue time in API (parsed from '{time_key}'): {queue_time}")
                                                                break
                                                
                                                in_queue = True
                                        except Exception as json_e:
                                            text_data = response.text
                                            print(f"Queue API response (text): {text_data}")
                                    elif response.status_code == 503:
                                        # Service Unavailable - don't spam console, just skip this fetch
                                        pass  # Silently skip 503 errors
                                    else:
                                        # Only log non-503 errors
                                        if response.status_code != 503:
                                            print(f"Queue API returned status: {response.status_code}")
                            except Exception as e:
                                print(f"Error fetching queue API with session: {e}")
                        
                        # Method 2: Using request_cloudflare if available
                        if queue_position is None and hasattr(atconn, 'request_cloudflare'):
                            try:
                                queue_url = f'https://aternos.org/panel/ajax/queue.php?id={server_id}'
                                print(f"Trying request_cloudflare for queue data: {queue_url}")
                                
                                response = atconn.request_cloudflare(queue_url, 'GET')
                                print(f"Queue API response (cloudflare): {response}")
                                
                                if response:
                                    if isinstance(response, dict):
                                        # Extract queue position and time
                                        for pos_key in ['position', 'pos', 'queue_pos']:
                                            if pos_key in response:
                                                queue_position = response[pos_key]
                                                print(f"Found queue position in API ({pos_key}): {queue_position}")
                                                break
                                        
                                        for time_key in ['time', 'wait', 'eta']:
                                            if time_key in response:
                                                queue_time = response[time_key]
                                                print(f"Found queue time in API ({time_key}): {queue_time}")
                                                break
                                        
                                        in_queue = True
                                    elif isinstance(response, str):
                                        # Try to parse HTML or text response
                                        import re
                                        # Look for position pattern like "3573 / 3852" or "3573/3852"
                                        pos_match = re.search(r'(\d+)\s*[/]\s*(\d+)', response)
                                        if pos_match:
                                            queue_position = f"{pos_match.group(1)}/{pos_match.group(2)}"
                                            print(f"Found queue position in text: {queue_position}")
                                        
                                        # Look for time pattern like "ca. 8 min" or "8 min"
                                        time_match = re.search(r'(\d+)\s*min', response, re.IGNORECASE)
                                        if time_match:
                                            queue_time = int(time_match.group(1)) * 60
                                            print(f"Found queue time in text: {queue_time}")
                                        
                                        if queue_position or queue_time:
                                            in_queue = True
                            except Exception as e:
                                error_str = str(e)
                                # Don't spam console with 503 errors
                                if '503' not in error_str and 'Service Unavailable' not in error_str:
                                    print(f"Error fetching queue API with request_cloudflare: {e}")
                except Exception as e:
                    print(f"Error with atconn approach: {e}")
                
                # If in queue - check status first to ensure "waiting" is always treated as queue
                if current_status == 'waiting':
                    in_queue = True
                    
                    # IMPORTANT: Check if queue has finished and needs confirmation (even while status is "waiting")
                    # This handles the case where server is "waiting" but queue finished and needs confirmation
                    if hasattr(aternos_server, '_info'):
                        info_data = getattr(aternos_server, '_info')
                        if isinstance(info_data, dict) and 'queue' in info_data:
                            queue_info = info_data.get('queue', {})
                            if isinstance(queue_info, dict):
                                position = queue_info.get('position', None)
                                pending = queue_info.get('pending', '')
                                
                                # If position is 1 or 0, or pending status, queue finished - try to confirm automatically
                                if (position is not None and position <= 1) or (pending and str(pending).lower() == 'pending'):
                                    print(f"🔍 Queue finished while in 'waiting' status! Position: {position}, Pending: {pending}")
                                    print("🚀 Attempting automatic confirmation...")
                                    
                                    auto_confirm_success = False
                                    
                                    try:
                                        # Refresh server status first
                                        aternos_server.fetch()
                                        
                                        # Try library confirm() method FIRST (most reliable)
                                        if hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm):
                                            try:
                                                aternos_server.confirm()
                                                auto_confirm_success = True
                                                print("✅✅✅ AUTO-CONFIRMED using library method!")
                                            except Exception as lib_err:
                                                print(f"   Library confirm() failed: {lib_err}")
                                        
                                        # Try request_cloudflare if library method failed
                                        if not auto_confirm_success and hasattr(aternos_server, 'atconn'):
                                            atconn = aternos_server.atconn
                                            server_id = getattr(aternos_server, 'servid', None)
                                            
                                            if hasattr(atconn, 'request_cloudflare'):
                                                if server_id:
                                                    confirm_url = f'https://aternos.org/ajax/server/confirm?id={server_id}'
                                                else:
                                                    confirm_url = 'https://aternos.org/ajax/server/confirm'
                                                
                                                try:
                                                    # Try POST first
                                                    response = atconn.request_cloudflare(confirm_url, 'POST')
                                                    if response is not None:
                                                        auto_confirm_success = True
                                                        print("✅✅✅ AUTO-CONFIRMED while in waiting status (POST)!")
                                                except:
                                                    try:
                                                        # Try GET as fallback
                                                        response = atconn.request_cloudflare(confirm_url, 'GET')
                                                        if response is not None:
                                                            auto_confirm_success = True
                                                            print("✅✅✅ AUTO-CONFIRMED while in waiting status (GET)!")
                                                    except:
                                                        pass
                                        
                                        if auto_confirm_success:
                                            await loading_msg.edit(content='✅ **Queue finished! Confirmation sent automatically.**\n⏳ Server is starting...')
                                            await asyncio.sleep(3)
                                            try:
                                                aternos_server.fetch()
                                                new_status = aternos_server.status
                                                print(f"📡 Server status after confirmation: {new_status}")
                                            except:
                                                pass
                                            await asyncio.sleep(2)
                                            continue
                                        
                                    except Exception as auto_confirm_err:
                                        print(f"⚠️ Auto-confirm failed while waiting: {auto_confirm_err}")
                                        import traceback
                                        traceback.print_exc()
                                        # Continue with normal queue monitoring
                    
                    # Try to fetch queue data from panel page HTML (fetch every 3 seconds to avoid rate limiting)
                    current_elapsed = int(time.time() - start_time)
                    # Fetch on first iteration (0 seconds) and then every 3 seconds
                    if current_elapsed == 0 or current_elapsed % 3 == 0:
                        print(f"Fetching queue data (elapsed: {current_elapsed}s)")
                        panel_queue_pos, panel_queue_time_str = await fetch_queue_data_from_panel(aternos_server)
                        if panel_queue_pos:
                            queue_position = panel_queue_pos
                            last_queue_position = panel_queue_pos
                            print(f"Updated queue position: {queue_position}")
                        if panel_queue_time_str:
                            last_queue_time_str = panel_queue_time_str
                            print(f"Updated queue time: {panel_queue_time_str}")
                        if not panel_queue_pos and not panel_queue_time_str:
                            print("No queue data found from panel fetch")
                
                # If in queue, show queue message
                if in_queue or current_status == 'waiting':
                    # Update last known values
                    if queue_time is not None:
                        last_queue_time = queue_time
                    if queue_position is not None:
                        last_queue_position = queue_position
                    if queue_time_str is not None:
                        last_queue_time_str = queue_time_str
                    elif 'last_queue_time_str' not in locals() or last_queue_time_str is None:
                        last_queue_time_str = None
                    
                    elapsed = int(time.time() - start_time)
                    elapsed_str = f'{elapsed // 60}m {elapsed % 60}s' if elapsed >= 60 else f'{elapsed}s'
                    
                    # Build the message based on available data
                    message = '⏳ **Waiting in Queue**\n\n'
                    
                    # Add queue position if available
                    if queue_position is not None:
                        message += f'📊 **Queue Position:** {queue_position}\n'
                    elif last_queue_position is not None:
                        message += f'📊 **Queue Position:** {last_queue_position}\n'
                    else:
                        message += f'📊 **Queue Position:** Unknown\n'
                    
                    # Add estimated time - ALWAYS use static locked value (NEVER changes)
                    if static_queue_time_str:
                        # Use the LOCKED static "ca. X min" value (never changes, only elapsed time updates)
                        message += f'⏱️ {static_queue_time_str}\n'
                    elif queue_time_str:
                        # First time only - lock it in
                        if static_queue_time_str is None:
                            static_queue_time_str = queue_time_str
                            print(f"🔒 LOCKED static queue time from queue_time_str: {static_queue_time_str}")
                        message += f'⏱️ {static_queue_time_str}\n'
                    elif last_queue_time_str:
                        # First time only - lock it in
                        if static_queue_time_str is None:
                            static_queue_time_str = last_queue_time_str
                            print(f"🔒 LOCKED static queue time from last_queue_time_str: {static_queue_time_str}")
                        message += f'⏱️ {static_queue_time_str}\n'
                    elif queue_time is not None:
                        # First time only - lock it in
                        if static_queue_time_str is None:
                            est_minutes = int(queue_time / 60)
                            static_queue_time_str = f"ca. {est_minutes} min"
                            print(f"🔒 LOCKED static queue time from queue_time: {static_queue_time_str}")
                        message += f'⏱️ {static_queue_time_str}\n'
                    elif last_queue_time is not None:
                        # First time only - lock it in
                        if static_queue_time_str is None:
                            est_minutes = int(last_queue_time / 60)
                            static_queue_time_str = f"ca. {est_minutes} min"
                            print(f"🔒 LOCKED static queue time from last_queue_time: {static_queue_time_str}")
                        message += f'⏱️ {static_queue_time_str}\n'
                    else:
                        # Check if countdown is available - first time only
                        if static_queue_time_str is None:
                            countdown = getattr(aternos_server, 'countdown', -1)
                            if countdown >= 0:
                                countdown_min = int(countdown / 60)
                                static_queue_time_str = f"ca. {countdown_min} min"
                                print(f"🔒 LOCKED static queue time from countdown: {static_queue_time_str}")
                        
                        if static_queue_time_str:
                            message += f'⏱️ {static_queue_time_str}\n'
                        else:
                            message += f'⏱️ **ca.** Calculating...\n'
                    
                    message += f'🕐 **Elapsed:** {elapsed_str}\n'
                    message += f'📡 **Status:** {current_status.upper()}'
                    
                    await loading_msg.edit(content=message)
                    
                    # Wait 1 second before next update
                    await asyncio.sleep(1)
                    continue
                
                # Check if server is online
                if current_status == 'online':
                    if str(guild_id) in queue_monitoring_tasks:
                        del queue_monitoring_tasks[str(guild_id)]
                    
                    await loading_msg.edit(content=f'✅ **Server Started!**\n🟢 **Status:** ONLINE\n\n_Server is ready to use!_')
                    return
                
                # Check if starting
                if current_status == 'starting':
                    elapsed = int(time.time() - start_time)
                    elapsed_str = f'{elapsed // 60}m {elapsed % 60}s' if elapsed >= 60 else f'{elapsed}s'
                    
                    await loading_msg.edit(
                        content=f'⏳ **Loading... Preparing server...**\n🟡 **Status:** STARTING\n'
                                f'🕐 **Elapsed:** {elapsed_str}\n\n_Please wait, server is starting up..._'
                    )
                    await asyncio.sleep(2)
                    continue
                
                # For other statuses, wait a bit longer
                await asyncio.sleep(2)
                
            except discord.errors.NotFound:
                # Message was deleted
                if str(guild_id) in queue_monitoring_tasks:
                    del queue_monitoring_tasks[str(guild_id)]
                return
            except Exception as e:
                print(f'Error in queue monitoring loop: {e}')
                await asyncio.sleep(2)
                
    except asyncio.CancelledError:
        # Task was cancelled
        if str(guild_id) in queue_monitoring_tasks:
            del queue_monitoring_tasks[str(guild_id)]
        return
    except Exception as e:
        print(f'Error in monitor_queue: {e}')
        if str(guild_id) in queue_monitoring_tasks:
            del queue_monitoring_tasks[str(guild_id)]

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
        
        # Cancel any existing queue monitoring task for this guild
        if str(ctx.guild.id) in queue_monitoring_tasks:
            queue_monitoring_tasks[str(ctx.guild.id)].cancel()
        
        # Start queue monitoring task
        task = asyncio.create_task(monitor_queue(ctx, loading_msg, aternos_server, ctx.guild.id))
        queue_monitoring_tasks[str(ctx.guild.id)] = task
        
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

@bot.command(name='autostart')
async def auto_start_toggle(ctx, action: str = None):
    """Enable or disable 24/7 auto-start (keeps server online automatically)"""
    if not action:
        # Show current status
        is_enabled = get_auto_start_enabled(ctx.guild.id)
        status_text = "🟢 **ENABLED**" if is_enabled else "🔴 **DISABLED**"
        await ctx.send(
            f'**24/7 Auto-Start Status:** {status_text}\n\n'
            f'**Usage:**\n'
            f'`!autostart enable` - Enable 24/7 auto-start\n'
            f'`!autostart disable` - Disable 24/7 auto-start\n\n'
            f'_When enabled, the bot will automatically start the server if it goes offline._'
        )
        return
    
    action_lower = action.lower()
    
    if action_lower == 'enable':
        # Check if server is configured
        aternos_server = server_servers.get(str(ctx.guild.id))
        if not aternos_server:
            await ctx.send('❌ Server not configured. Please set up your Aternos credentials in the `server-setup` channel using `!username` and `!password` commands.')
            return
        
        # Enable auto-start
        set_auto_start_enabled(ctx.guild.id, True)
        
        # Start monitoring task if not already running
        if str(ctx.guild.id) not in auto_start_tasks:
            task = asyncio.create_task(monitor_auto_start(ctx.guild.id))
            auto_start_tasks[str(ctx.guild.id)] = task
            print(f'✅ Auto-start monitoring started for guild {ctx.guild.id}')
        
        await ctx.send(
            '✅ **24/7 Auto-Start ENABLED!**\n\n'
            '🔄 The bot will now automatically start your server if it goes offline.\n'
            '⏱️ Checking every 5 seconds...\n\n'
            '_Use `!autostart disable` to turn this off._'
        )
        
    elif action_lower == 'disable':
        # Disable auto-start
        set_auto_start_enabled(ctx.guild.id, False)
        
        # Stop monitoring task if running
        if str(ctx.guild.id) in auto_start_tasks:
            task = auto_start_tasks[str(ctx.guild.id)]
            task.cancel()
            del auto_start_tasks[str(ctx.guild.id)]
            print(f'⏸️ Auto-start monitoring stopped for guild {ctx.guild.id}')
        
        await ctx.send(
            '⏸️ **24/7 Auto-Start DISABLED**\n\n'
            '_The bot will no longer automatically start your server._\n'
            '_Use `!autostart enable` to turn it back on._'
        )
    else:
        await ctx.send(
            '❌ Invalid action. Use:\n'
            '`!autostart enable` - Enable 24/7 auto-start\n'
            '`!autostart disable` - Disable 24/7 auto-start'
        )

@bot.command(name='debug')
async def debug_server(ctx):
    """Debug command to see all server attributes"""
    # Get server-specific Aternos server
    aternos_server = server_servers.get(str(ctx.guild.id))
    
    if not aternos_server:
        await ctx.send('❌ Server not configured.')
        return
    
    try:
        # Refresh server info
        aternos_server.fetch()
        
        debug_info = f"**Debug Information:**\n\n"
        debug_info += f"**Status:** `{aternos_server.status}`\n"
        
        # Check all possible queue-related attributes
        debug_info += f"\n**Queue Detection:**\n"
        debug_info += f"Has 'queue' attr: {hasattr(aternos_server, 'queue')}\n"
        
        if hasattr(aternos_server, 'queue') and aternos_server.queue:
            queue_obj = aternos_server.queue
            debug_info += f"Queue object type: {type(queue_obj)}\n"
            if hasattr(queue_obj, 'position'):
                debug_info += f"Queue position: {queue_obj.position}\n"
            if hasattr(queue_obj, 'time'):
                debug_info += f"Queue time: {queue_obj.time}\n"
        
        # Check other queue attributes
        queue_attrs = ['queue_position', 'queue_time', 'loading', 'waiting']
        for attr in queue_attrs:
            if hasattr(aternos_server, attr):
                debug_info += f"{attr}: {getattr(aternos_server, attr)}\n"
        
        # Check for confirmation
        debug_info += f"\n**Confirmation:**\n"
        debug_info += f"Has 'is_confirm_required': {hasattr(aternos_server, 'is_confirm_required')}\n"
        if hasattr(aternos_server, 'is_confirm_required'):
            debug_info += f"Confirm required: {aternos_server.is_confirm_required}\n"
        
        # List some important attributes
        debug_info += f"\n**Key Attributes:**\n"
        attrs = ['address', 'status', 'players_count', 'software', 'version']
        for attr in attrs:
            if hasattr(aternos_server, attr):
                debug_info += f"{attr}: {getattr(aternos_server, attr)}\n"
        
        # Check if there are any methods that might give queue info
        debug_info += f"\n**Available Methods:**\n"
        methods = [m for m in dir(aternos_server) if callable(getattr(aternos_server, m)) and not m.startswith('_')]
        queue_methods = [m for m in methods if 'queue' in m.lower() or 'wait' in m.lower() or 'confirm' in m.lower()]
        if queue_methods:
            debug_info += f"Relevant methods: {', '.join(queue_methods)}\n"
        
        # Show ALL non-private, non-callable attributes with values
        debug_info += f"\n**All Attributes:**\n```\n"
        for attr in dir(aternos_server):
            if not attr.startswith('_') and not callable(getattr(aternos_server, attr)):
                try:
                    value = getattr(aternos_server, attr)
                    debug_info += f"{attr}: {value}\n"
                except:
                    pass
        debug_info += "```"
        
        # Split message if too long
        if len(debug_info) > 2000:
            # Send in chunks
            chunks = [debug_info[i:i+1900] for i in range(0, len(debug_info), 1900)]
            for chunk in chunks:
                await ctx.send(chunk)
        else:
            await ctx.send(debug_info)
        
    except Exception as e:
        await ctx.send(f'❌ Error: {e}')

@bot.command(name='confirm')
async def confirm_start(ctx):
    """Manually confirm server start if confirmation is required - Works same as button"""
    aternos_server = server_servers.get(str(ctx.guild.id))
    
    if not aternos_server:
        await ctx.send('❌ Server not configured.')
        return
    
    try:
        # Refresh server status first
        aternos_server.fetch()
        current_status = aternos_server.status
        
        # Check if confirmation is actually needed
        needs_confirm = False
        if hasattr(aternos_server, '_info'):
            info_data = getattr(aternos_server, '_info')
            if isinstance(info_data, dict) and 'queue' in info_data:
                queue_info = info_data.get('queue', {})
                if isinstance(queue_info, dict):
                    pending = queue_info.get('pending', '')
                    if pending and str(pending).lower() == 'pending':
                        needs_confirm = True
        
        # Also check css_class
        if not needs_confirm and hasattr(aternos_server, 'css_class'):
            css_class = str(aternos_server.css_class).lower()
            if 'pending' in css_class or 'confirm' in css_class:
                if 'queueing' not in css_class:
                    needs_confirm = True
        
        # Try to confirm
        if hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm):
            confirm_msg = await ctx.send('⏳ Sending confirmation to Aternos...')
            
            try:
                # ============================================================
                # EXTENSIVE DEBUGGING BEFORE CONFIRMATION (COMMAND)
                # ============================================================
                print("=" * 60)
                print("🔍 !CONFIRM COMMAND - DEBUGGING")
                print("=" * 60)
                
                # Refresh server status first
                print("1. Refreshing server status...")
                aternos_server.fetch()
                current_status = aternos_server.status
                print(f"   Status after fetch: {current_status}")
                
                # Check _info for confirmation status
                print("2. Checking _info for confirmation requirements...")
                if hasattr(aternos_server, '_info'):
                    info_data = getattr(aternos_server, '_info')
                    if isinstance(info_data, dict):
                        print(f"   _info keys: {list(info_data.keys())}")
                        if 'queue' in info_data:
                            queue_info = info_data.get('queue', {})
                            if isinstance(queue_info, dict):
                                pending = queue_info.get('pending', '')
                                position = queue_info.get('position', None)
                                print(f"   Queue pending: '{pending}', position: {position}")
                
                # Check css_class
                print("3. Checking css_class...")
                css_class = getattr(aternos_server, 'css_class', 'N/A')
                print(f"   css_class: '{css_class}'")
                
                # Check if confirm method exists
                print("4. Checking confirm() method...")
                has_confirm = hasattr(aternos_server, 'confirm') and callable(aternos_server.confirm)
                print(f"   Has confirm method: {has_confirm}")
                
                # Check connection
                print("5. Checking connection...")
                if hasattr(aternos_server, 'atconn'):
                    atconn = aternos_server.atconn
                    print(f"   Has atconn: True")
                    if hasattr(atconn, 'session'):
                        print(f"   Has session: True")
                
                print("6. Server attributes before confirm:")
                print(f"   status: {current_status}")
                print(f"   css_class: {css_class}")
                print("=" * 60)
                
                # Try to refresh connection/token if possible
                print("7. Attempting to refresh connection...")
                try:
                    # Re-fetch to get fresh token
                    aternos_server.fetch()
                    print("   ✅ Server status refreshed")
                except Exception as refresh_error:
                    print(f"   ⚠️ Could not refresh: {refresh_error}")
                
                # FORCE RE-AUTHENTICATION before confirming to get fresh token
                print("8. Force re-authenticating with Aternos to get fresh token...")
                try:
                    if await connect_to_aternos(ctx.guild.id):
                        aternos_server = server_servers.get(str(ctx.guild.id))
                        if aternos_server:
                            aternos_server.fetch()
                            print("   ✅ Re-authenticated and refreshed server")
                        else:
                            print("   ⚠️ Re-authenticated but server not found")
                    else:
                        print("   ⚠️ Re-authentication failed, continuing with existing connection")
                except Exception as reauth_error:
                    print(f"   ⚠️ Re-authentication error (non-critical): {reauth_error}")
                
                # Send confirmation to Aternos - Try multiple methods (same as button)
                print("9. Attempting to confirm server start...")
                confirm_success = False
                last_error = None
                
                try:
                    # Get the connection
                    if hasattr(aternos_server, 'atconn'):
                        atconn = aternos_server.atconn
                        server_id = aternos_server.servid
                        
                        # Method 1: Use request_cloudflare (most reliable for Aternos)
                        if hasattr(atconn, 'request_cloudflare'):
                            try:
                                print("   Trying request_cloudflare method...")
                                confirm_url = 'https://aternos.org/ajax/server/confirm'
                                response = atconn.request_cloudflare(confirm_url, 'GET')
                                print(f"   request_cloudflare response: {response}")
                                
                                if response:
                                    if isinstance(response, dict):
                                        if response.get('status') == 'success' or 'success' in str(response).lower():
                                            confirm_success = True
                                            print("   ✅ Confirm successful via request_cloudflare")
                                    elif isinstance(response, str):
                                        if 'success' in response.lower() or 'ok' in response.lower():
                                            confirm_success = True
                                            print("   ✅ Confirm successful via request_cloudflare")
                                    else:
                                        confirm_success = True
                                        print("   ✅ Confirm successful via request_cloudflare (got response)")
                            except Exception as cf_error:
                                print(f"   ⚠️ request_cloudflare failed: {cf_error}")
                                last_error = cf_error
                        
                        # Method 2: Direct session call
                        if not confirm_success and hasattr(atconn, 'session'):
                            try:
                                print("   Trying direct session call...")
                                session = atconn.session
                                import aiohttp
                                import requests
                                
                                confirm_url = 'https://aternos.org/ajax/server/confirm'
                                
                                if isinstance(session, aiohttp.ClientSession):
                                    async with session.get(confirm_url) as response:
                                        if response.status == 200:
                                            result = await response.text()
                                            print(f"   ✅ Direct session GET successful: {result}")
                                            confirm_success = True
                                elif isinstance(session, requests.Session):
                                    loop = asyncio.get_event_loop()
                                    response = await loop.run_in_executor(None, session.get, confirm_url)
                                    if response.status_code == 200:
                                        print(f"   ✅ Direct session GET successful: {response.text}")
                                        confirm_success = True
                            except Exception as session_error:
                                print(f"   ⚠️ Direct session call failed: {session_error}")
                                if not last_error:
                                    last_error = session_error
                        
                        # Method 3: Library method as fallback
                        if not confirm_success:
                            try:
                                print("   Trying library confirm() method as fallback...")
                                aternos_server.confirm()
                                print("   ✅ Library confirm() method called")
                                confirm_success = True
                            except Exception as lib_error:
                                print(f"   ⚠️ Library confirm() failed: {lib_error}")
                                if not last_error:
                                    last_error = lib_error
                    else:
                        # No atconn, try library method
                        print("   No atconn, trying library confirm() method...")
                        aternos_server.confirm()
                        print("   ✅ Library confirm() method called")
                        confirm_success = True
                        
                except Exception as confirm_error:
                    print(f"   ❌ All confirm methods failed")
                    last_error = confirm_error
                    import traceback
                    traceback.print_exc()
                
                if not confirm_success:
                    raise Exception(f"All confirmation methods failed. Last error: {last_error}")
                
                # Wait a moment for status to update
                await asyncio.sleep(2)
                
                # Check status after confirmation
                aternos_server.fetch()
                new_status = aternos_server.status
                
                # Update message with success
                await confirm_msg.edit(
                    content=f'✅ **Confirmation sent!**\n'
                           f'📡 **Server Status:** `{new_status}`\n'
                           f'⏳ The server should start soon...'
                )
                
                # If status is starting or online, send additional message
                if new_status in ['starting', 'online']:
                    await ctx.send('🎉 **Server is starting!** Please wait...')
                elif needs_confirm:
                    await ctx.send('✅ **Confirmation processed!** The server should start soon.')
                    
            except Exception as confirm_error:
                error_msg = str(confirm_error)
                print(f'❌❌❌ Error in confirm command: {confirm_error}')
                import traceback
                traceback.print_exc()
                
                # Try to re-authenticate if it's a 400/401 error
                if '400' in error_msg or '401' in error_msg or 'Bad Request' in error_msg:
                    print("🔄 Attempting to re-authenticate due to 400/401 error...")
                    try:
                        # Try to reconnect
                        if await connect_to_aternos(ctx.guild.id):
                            print("✅ Re-authenticated successfully")
                            aternos_server = server_servers.get(str(ctx.guild.id))
                            if aternos_server:
                                aternos_server.fetch()
                                # Try confirm again
                                try:
                                    aternos_server.confirm()
                                    await confirm_msg.edit(
                                        content=f'✅ **Confirmation sent!** (After re-authentication)\n'
                                               f'📡 **Server Status:** `{aternos_server.status}`\n'
                                               f'⏳ The server should start soon...'
                                    )
                                    return
                                except Exception as retry_error:
                                    print(f"❌ Confirm failed after re-auth: {retry_error}")
                    except Exception as reconnect_error:
                        print(f"❌ Re-authentication failed: {reconnect_error}")
                
                await confirm_msg.edit(
                    content=f'❌ **Error confirming:** {error_msg}\n\n'
                           f'**Possible causes:**\n'
                           f'• Server might not need confirmation right now\n'
                           f'• Token expired - try restarting the bot\n'
                           f'• Server status changed\n\n'
                           f'**Please check the server status on Aternos website.**'
                )
        else:
            await ctx.send('❌ No confirmation method available.\n'
                          'The server might not need confirmation right now, or it\'s already confirmed.')
    except Exception as e:
        error_msg = str(e)
        print(f'Error in confirm command: {e}')
        import traceback
        traceback.print_exc()
        await ctx.send(f'❌ **Error:** {error_msg}')

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
        print('\n' + '='*60)
        print('❌ ERROR: DISCORD_TOKEN not found!')
        print('='*60)
        print('\n📝 To fix this:')
        print('   1. Create a file named ".env" in the same folder as bot.py')
        print('   2. Add this line to the .env file:')
        print('      DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE')
        print('\n   Example:')
        print('      DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE')
        print('\n   Get your token from:')
        print('   https://discord.com/developers/applications/1442827241892352073/bot')
        print('\n' + '='*60 + '\n')
        exit(1)
    
    # Validate token format
    if len(DISCORD_TOKEN) < 50:
        print('\n' + '='*60)
        print('❌ ERROR: Discord token appears to be invalid!')
        print('='*60)
        print('\n⚠️  Discord bot tokens are usually 59+ characters long.')
        print(f'   Your token length: {len(DISCORD_TOKEN)}')
        print('\n📝 Please check your .env file and make sure:')
        print('   1. The token is correct (no extra spaces)')
        print('   2. The token is on a single line')
        print('   3. There are no quotes around the token')
        print('\n   Example format in .env:')
        print('      DISCORD_TOKEN=MTQ0MjgyNzI0MTg5MjM1MjA3Mw.GZEJJe.3ZJob0TcDel9GlnGPAxfCc6LSWkBtzLAvDKu0M')
        print('\n' + '='*60 + '\n')
        exit(1)
    
    print('\n' + '='*50)
    print('🤖 Aternos Discord Bot Starting...')
    print('='*50)
    print(f'\n✅ Bot token loaded (length: {len(DISCORD_TOKEN)} characters)')
    print(f'\n📋 To make bot public:')
    print(f'   1. Go to: https://discord.com/developers/applications/1442827241892352073/bot')
    print(f'   2. Enable "Public Bot" toggle')
    print(f'\n🔗 Invite URL:')
    print(f'   https://discord.com/oauth2/authorize?client_id=1442827241892352073&permissions=2147568640&scope=bot')
    print(f'\n' + '='*50 + '\n')
    
    # Start HTTP server for Render.com port binding (runs in background thread)
    def start_http_server():
        """Start a simple HTTP server to satisfy Render.com port requirement"""
        from http.server import HTTPServer, BaseHTTPRequestHandler
        
        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/plain; charset=utf-8')
                self.end_headers()
                message = '🤖 Aternos Discord Bot is running!'
                self.wfile.write(message.encode('utf-8'))
            
            def log_message(self, format, *args):
                pass  # Suppress HTTP server logs
        
        port = int(os.getenv('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        
        def run_server():
            print(f'🌐 HTTP server started on port {port}')
            server.serve_forever()
        
        import threading
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        return server
    
    # Start HTTP server in background
    start_http_server()
    
    try:
        bot.run(DISCORD_TOKEN)
    except discord.errors.LoginFailure:
        print('\n' + '='*60)
        print('❌ ERROR: Failed to login to Discord!')
        print('='*60)
        print('\n⚠️  The Discord token is invalid or expired.')
        print('\n📝 To fix this:')
        print('   1. Go to: https://discord.com/developers/applications/1442827241892352073/bot')
        print('   2. Click "Reset Token" to get a new token')
        print('   3. Copy the new token')
        print('   4. Update your .env file with the new token')
        print('   5. Restart the bot')
        print('\n' + '='*60 + '\n')
        exit(1)
    except Exception as e:
        print(f'\n❌ Unexpected error: {e}')
        import traceback
        traceback.print_exc()
        exit(1)

