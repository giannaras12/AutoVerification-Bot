import discord
from discord.ext import commands, tasks
from discord.ui import View, Select
import os
import json
import random
import asyncio
import datetime
from flask import Flask
from threading import Thread

# --- CONFIG ---
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))            # Verification channel
ROLE_ID = int(os.getenv("ROLE_ID"))                  # Role given on verification
COUNTING_CHANNEL_ID = int(os.getenv("COUNTING_CHANNEL_ID"))  # Counting channel
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))    # Timeout log channel
MODERATOR_ROLES = [1407804031547474061, 1407804295763595324, 1407805292586078257]

MESSAGE_FILE = "verification.json"
COUNT_FILE = "counting.json"

intents = discord.Intents.default()
intents.reactions = True
intents.members = True
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Load verification message ---
if os.path.exists(MESSAGE_FILE):
    with open(MESSAGE_FILE, "r") as f:
        data = json.load(f)
        MESSAGE_ID = data.get("message_id", None)
else:
    MESSAGE_ID = None

# --- Load last counting number ---
if os.path.exists(COUNT_FILE):
    with open(COUNT_FILE, "r") as f:
        data = json.load(f)
        last_number = data.get("last_number", 0)
else:
    last_number = 0

def save_count():
    with open(COUNT_FILE, "w") as f:
        json.dump({"last_number": last_number}, f)

# --- Verification embed ---
def create_verification_embed():
    embed = discord.Embed(
        title="✅ Verification",
        description="By reacting to this message with the ✅ emoji you confirm that you have **read** and will **respect** the community rules.",
        color=discord.Color.green()
    )
    embed.set_footer(text="Welcome to the community!")
    return embed

# --- Bot ready event ---
@bot.event
async def on_ready():
    global MESSAGE_ID, last_number
    print(f"✅ Logged in as {bot.user}")

    # Verification message
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        if MESSAGE_ID is None:
            msg = await channel.send(embed=create_verification_embed())
            await msg.add_reaction("✅")
            MESSAGE_ID = msg.id
            with open(MESSAGE_FILE, "w") as f:
                json.dump({"message_id": MESSAGE_ID}, f)
            print(f"📌 Verification message sent (ID: {MESSAGE_ID})")

    # Counting channel: fetch last number robustly
    count_channel = bot.get_channel(COUNTING_CHANNEL_ID)
    if count_channel:
        last_number_found = False
        async for m in count_channel.history(limit=None, oldest_first=False):
            if m.content.isdigit():
                last_number = int(m.content)
                last_number_found = True
                break
        if not last_number_found:
            # Empty or no numeric message → send 1
            last_number = 1
            await count_channel.send("1")
        save_count()

    send_random_number.start()

    # Sync commands for timeout
    try:
        await bot.tree.sync()
        print("✅ Synced application commands.")
    except Exception as e:
        print(f"⚠️ Failed to sync commands: {e}")

# --- Verification role ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id == MESSAGE_ID and str(payload.emoji) == "✅":
        guild = bot.get_guild(payload.guild_id)
        role = guild.get_role(ROLE_ID)
        if role:
            member = guild.get_member(payload.user_id)
            if member and not member.bot:
                try:
                    await member.add_roles(role)
                    print(f"🎉 Gave role {role.name} to {member.name}")
                except discord.Forbidden:
                    print("⚠️ Missing permissions to add role.")

# --- Counting channel logic ---
@bot.event
async def on_message(message):
    global last_number
    if message.author.bot:
        return

    if message.channel.id == COUNTING_CHANNEL_ID:
        if not message.content.isdigit():
            try:
                await message.delete()
            except:
                pass
            return

        number = int(message.content)

        # FIXED: Ensure last_number is initialized correctly
        if last_number == 0:
            last_number = number - 1

        if number != last_number + 1:
            try:
                await message.delete()
            except:
                pass
            return

        last_number = number
        save_count()

    await bot.process_commands(message)

# --- Random number every 24–48h ---
@tasks.loop(hours=24)
async def send_random_number():
    global last_number
    await asyncio.sleep(random.randint(0, 24*60*60))  # Random delay 0–24h
    channel = bot.get_channel(COUNTING_CHANNEL_ID)
    if channel:
        last_number += 1
        await channel.send(str(last_number))
        save_count()

# --- Timeout via context menu ---
@bot.tree.context_menu(name="Timeout")
async def timeout_message(interaction: discord.Interaction, message: discord.Message):
    if not any(r.id in MODERATOR_ROLES for r in interaction.user.roles):
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True)
        return

    options = [
        discord.SelectOption(label="15 minutes", value="900"),
        discord.SelectOption(label="1 hour", value="3600"),
        discord.SelectOption(label="3 hours", value="10800"),
        discord.SelectOption(label="6 hours", value="21600"),
        discord.SelectOption(label="1 day", value="86400"),
    ]

    class DurationSelectView(View):
        def __init__(self):
            super().__init__(timeout=60)
            self.select = Select(placeholder="Select timeout duration", options=options)
            self.select.callback = self.select_callback
            self.add_item(self.select)

        async def select_callback(self, interaction2: discord.Interaction):
            duration_seconds = int(self.select.values[0])
            duration = datetime.timedelta(seconds=duration_seconds)
            member = message.author
            try:
                await member.timeout(duration, reason=f"Timeout by {interaction.user}")
            except discord.Forbidden:
                await interaction2.response.send_message("⚠️ Missing permissions to timeout this user.", ephemeral=True)
                return

            # Log embed
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                messages = [m async for m in message.channel.history(limit=20) if m.author.id == member.id]
                last_5 = "\n".join([f"- {m.content}" for m in messages[:5]])
                embed = discord.Embed(
                    title="🚨 Timeout Applied",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.utcnow()
                )
                embed.add_field(name="Moderator", value=interaction.user.mention)
                embed.add_field(name="User", value=member.mention)
                embed.add_field(name="Duration", value=str(duration))
                embed.add_field(name="Channel", value=message.channel.mention)
                embed.add_field(name="Message", value=message.content or "*[No content]*")
                embed.add_field(name="Last 5 Messages", value=last_5 or "No history")
                await log_channel.send(embed=embed)

            await interaction2.response.send_message(f"✅ {member.mention} timed out for {duration}.", ephemeral=True)
            self.stop()

    await interaction.response.send_message("Select timeout duration:", view=DurationSelectView(), ephemeral=True)

# --- Keep-alive server for UptimeRobot ---
app = Flask("")

@app.route("/")
def home():
    return "Bot is running!"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()
bot.run(TOKEN)
