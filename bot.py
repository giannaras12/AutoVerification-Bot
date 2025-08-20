import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select
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
ROLE_ID = int(os.getenv("ROLE_ID"))                  # Role to give on verification
COUNTING_CHANNEL_ID = int(os.getenv("COUNTING_CHANNEL_ID"))  # Counting channel
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))    # Log channel for moderation
MODERATOR_ROLES = [1407804031547474061, 1407804295763595324, 1407805292586078257]

MESSAGE_FILE = "verification.json"
COUNT_FILE = "counting.json"

# --- INTENTS AND BOT ---
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

# --- Load counting progress ---
if os.path.exists(COUNT_FILE):
    with open(COUNT_FILE, "r") as f:
        data = json.load(f)
        last_number = data.get("last_number", 0)
else:
    last_number = 0

# --- Save last number ---
def save_count():
    with open(COUNT_FILE, "w") as f:
        json.dump({"last_number": last_number}, f)

# --- Verification Embed ---
def create_verification_embed():
    embed = discord.Embed(
        title="✅ Verification",
        description="By reacting to this message with the ✅ emoji you confirm that you have **read** and will **respect** the community rules.",
        color=discord.Color.green()
    )
    embed.set_footer(text="Welcome to the community!")
    return embed

# --- Timeout Views for moderation ---
class TimeoutView(View):
    def __init__(self, target_message, moderator):
        super().__init__(timeout=60)
        self.target_message = target_message
        self.moderator = moderator

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.moderator

    @discord.ui.button(label="✅ Yes", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Choose timeout duration:", view=DurationView(self.target_message, self.moderator), ephemeral=True)
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("❌ Timeout cancelled.", ephemeral=True)
        self.stop()

class DurationView(View):
    def __init__(self, target_message, moderator):
        super().__init__(timeout=60)
        self.target_message = target_message
        self.moderator = moderator

        options = [
            discord.SelectOption(label="15 minutes", value="900"),
            discord.SelectOption(label="1 hour", value="3600"),
            discord.SelectOption(label="3 hours", value="10800"),
            discord.SelectOption(label="6 hours", value="21600"),
            discord.SelectOption(label="1 day", value="86400"),
        ]
        self.add_item(Select(placeholder="Select duration", options=options, custom_id="duration_select"))

    @discord.ui.select(custom_id="duration_select")
    async def select_duration(self, interaction: discord.Interaction, select: Select):
        duration_seconds = int(select.values[0])
        duration = datetime.timedelta(seconds=duration_seconds)
        member = self.target_message.author

        try:
            await member.timeout_for(duration, reason=f"Timeout by {self.moderator}")
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ Missing permissions to timeout this user.", ephemeral=True)
            return

        # Log to channel
        log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            messages = [m async for m in self.target_message.channel.history(limit=20) if m.author.id == member.id]
            last_5 = "\n".join([f"- {m.content}" for m in messages[:5]])

            embed = discord.Embed(
                title="🚨 Timeout Applied",
                color=discord.Color.red(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="Moderator", value=self.moderator.mention, inline=True)
            embed.add_field(name="User", value=member.mention, inline=True)
            embed.add_field(name="Duration", value=str(duration), inline=True)
            embed.add_field(name="Channel", value=self.target_message.channel.mention, inline=False)
            embed.add_field(name="Message", value=self.target_message.content or "*[No content]*", inline=False)
            embed.add_field(name="Last 5 Messages", value=last_5 or "No history", inline=False)
            await log_channel.send(embed=embed)

        await interaction.response.send_message(f"✅ {member.mention} has been timed out for {duration}.", ephemeral=True)

# --- Context Menu Command ---
@bot.tree.context_menu(name="Timeout")
async def timeout_message(interaction: discord.Interaction, message: discord.Message):
    # Check moderator role
    if not any(r.id in MODERATOR_ROLES for r in interaction.user.roles):
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Are you sure you want to timeout {message.author.mention}?",
        view=TimeoutView(message, interaction.user),
        ephemeral=True
    )

# --- Events ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    # Sync context menu commands
    try:
        await bot.tree.sync()
        print("✅ Synced application commands.")
    except Exception as e:
        print(f"⚠️ Failed to sync commands: {e}")

    # Verification message
    global MESSAGE_ID
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        if MESSAGE_ID is None:
            msg = await channel.send(embed=create_verification_embed())
            await msg.add_reaction("✅")
            MESSAGE_ID = msg.id
            with open(MESSAGE_FILE, "w") as f:
                json.dump({"message_id": MESSAGE_ID}, f)
            print(f"📌 Verification message sent (ID: {MESSAGE_ID})")
        else:
            print(f"🔗 Using existing verification message (ID: {MESSAGE_ID})")

    # Start counting bot loop
    send_random_number.start()

# --- Reaction role ---
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

# --- Counting channel ---
@bot.event
async def on_message(message):
    global last_number
    if message.author.bot:
        return

    # Counting channel logic
    if message.channel.id == COUNTING_CHANNEL_ID:
        if not message.content.isdigit():
            await message.delete()
            return

        number = int(message.content)
        if number != last_number + 1:
            await message.delete()
            return

        last_number = number
        save_count()

    await bot.process_commands(message)

# --- Random counting by bot ---
@tasks.loop(hours=24)
async def send_random_number():
    global last_number
    await asyncio.sleep(random.randint(0, 24*60*60))
    channel = bot.get_channel(COUNTING_CHANNEL_ID)
    if channel:
        last_number += 1
        await channel.send(str(last_number))
        save_count()

# --- Keep Alive ---
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
