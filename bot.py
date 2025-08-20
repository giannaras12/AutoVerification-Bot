import discord
from discord.ext import commands
import os
import json

# --- CONFIG ---
TOKEN = os.getenv("DISCORD_TOKEN")  # token stored as environment variable
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # set in Render
ROLE_ID = int(os.getenv("ROLE_ID"))  # set in Render
MESSAGE_FILE = "verification.json"

intents = discord.Intents.default()
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Load message ID if exists ---
if os.path.exists(MESSAGE_FILE):
    with open(MESSAGE_FILE, "r") as f:
        data = json.load(f)
        MESSAGE_ID = data.get("message_id", None)
else:
    MESSAGE_ID = None

# --- Create Embed ---
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
        if MESSAGE_ID is None:  # send only if no message exists yet
            msg = await channel.send(embed=create_verification_embed())
            await msg.add_reaction("✅")
            MESSAGE_ID = msg.id
            with open(MESSAGE_FILE, "w") as f:
                json.dump({"message_id": MESSAGE_ID}, f)
            print(f"📌 Verification message sent (ID: {MESSAGE_ID})")
        else:
            print(f"🔗 Using existing verification message (ID: {MESSAGE_ID})")

# --- Give Role on Reaction ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.message_id == MESSAGE_ID and str(payload.emoji) == "✅":
        guild = bot.get_guild(payload.guild_id)
        role = guild.get_role(ROLE_ID)
        if role:
            member = guild.get_member(payload.user_id)
            if member and not member.bot:
                await member.add_roles(role)
                print(f"🎉 Gave role {role.name} to {member.name}")

# --- Keep-Alive Server for UptimeRobot ---
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
