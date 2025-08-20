import discord
from discord.ext import commands, tasks
import os
import json
import random
import asyncio

# --- CONFIG ---
TOKEN = os.getenv("DISCORD_TOKEN")  
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  
ROLE_ID = int(os.getenv("ROLE_ID"))  
COUNTING_CHANNEL_ID = int(os.getenv("COUNTING_CHANNEL_ID"))  # 👈 set this in Render
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

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
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

    # Start background task for random counting
    send_random_number.start()

# --- Role assignment ---
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

# --- Counting game ---
@bot.event
async def on_message(message):
    global last_number
    if message.author.bot:
        return

    # Only enforce rules in counting channel
    if message.channel.id == COUNTING_CHANNEL_ID:
        if not message.content.isdigit():
            await message.delete()
            return

        number = int(message.content)

        # Check if number is correct sequence
        if number != last_number + 1:
            await message.delete()
            return

        # Valid number → accept it
        last_number = number
        save_count()

    # Allow commands & other bot processing
    await bot.process_commands(message)

# --- Random bot counting ---
@tasks.loop(hours=24)
async def send_random_number():
    global last_number
    await asyncio.sleep(random.randint(0, 24*60*60))  # add random 0–24h extra delay
    channel = bot.get_channel(COUNTING_CHANNEL_ID)
    if channel:
        last_number += 1
        await channel.send(str(last_number))
        save_count()

# --- Keep Alive ---
from flask import Flask
from threading import Thread

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
