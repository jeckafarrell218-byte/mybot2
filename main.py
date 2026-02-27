import discord
from discord import app_commands
from discord.ext import commands
import random
import json
import asyncio
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

#----------------- FLASK CODE TRICK ---------------

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Help meee"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# -------------------- CONFIG --------------------

DATA_FILE = Path("data.json")
GIF_URL = "https://tenor.com/view/king-von-red-eyes-meme-king-von-gif-16983836547607203086"
KEYWORD = "von"
MIN_THRESHOLD = 100
MAX_THRESHOLD = 150
KEYWORD_TIMEOUT = 30
MIN_REWARD = 1
MAX_REWARD = 10
OWNER_ID = 1226961794296320053
MAX_GIVE = 20_000_000

# -------------------- BOT SETUP --------------------

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=None, intents=intents)
data_lock = asyncio.Lock()

# -------------------- DATA HELPERS --------------------

def load_data():
    if not DATA_FILE.exists():
        return {"guilds": {}, "users": {}, "cooldowns": {}, "pray_state": {}}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"guilds": {}, "users": {}, "cooldowns": {}, "pray_state": {}}

async def save_data(d):
    """
    Write the JSON to disk.
    NOTE: this function does NOT acquire data_lock to avoid nested-lock deadlocks.
    Callers that need atomic consistency should wrap calls in `async with data_lock:`.
    """
    # write atomically (simple sync write)
    DATA_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")

async def get_guild_state(d, guild_id):
    g = d["guilds"].setdefault(guild_id, {})
    g.setdefault("message_count", 0)
    g.setdefault("threshold", random.randint(MIN_THRESHOLD, MAX_THRESHOLD))
    g.setdefault("active_event", False)
    return g

async def add_von_dreads(d, user_id, amount):
    u = d["users"].setdefault(user_id, {})
    u["von_dreads"] = u.get("von_dreads", 0) + amount
    return u["von_dreads"]

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

# -------------------- EVENTS --------------------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Command sync failed:", e)
    await save_data(load_data())
    print("Bot is ready.")

def is_keyword_message(msg):
    return not msg.author.bot and msg.content.strip().lower() == KEYWORD

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    d = load_data()
    guild_id = str(message.guild.id)
    g = await get_guild_state(d, guild_id)
    g["message_count"] += 1

    if not g["active_event"] and g["message_count"] >= g["threshold"]:
        g["active_event"] = True
        g["message_count"] = 0
        g["threshold"] = random.randint(MIN_THRESHOLD, MAX_THRESHOLD)
        await save_data(d)
        bot.loop.create_task(handle_gif_event(message.channel, message.guild))

    await save_data(d)

# -------------------- GIF EVENT --------------------

async def handle_gif_event(channel, guild):
    guild_id = str(guild.id)
    reward = random.randint(MIN_REWARD, MAX_REWARD)

    d = load_data()
    async with data_lock:
        g = await get_guild_state(d, guild_id)
        if not g["active_event"]:
            return

        embed = discord.Embed(
            title="K Vibes",
            description=f"First to type **{KEYWORD}** wins **{reward} Von Dreads**! You got {KEYWORD_TIMEOUT} seconds homie."
        )
        embed.set_image(url=GIF_URL)
        await channel.send(embed=embed)

    def check(m):
        return (
            m.guild == guild
            and m.channel == channel
            and is_keyword_message(m)
        )

    try:
        winner = await bot.wait_for("message", timeout=KEYWORD_TIMEOUT, check=check)
    except asyncio.TimeoutError:
        await channel.send(f"None of you mothafuckas typed **{KEYWORD}** in time... better luck next time yall")
    else:
        async with data_lock:
            d = load_data()
            total = await add_von_dreads(d, str(winner.author.id), reward)
            g = await get_guild_state(d, guild_id)
            g["active_event"] = False
            await save_data(d)

        await channel.send(
            f"Damn yall, {winner.author.mention} said **{KEYWORD}** first and won "
            f"**{reward} Von Dreads**. Now they got **{total} Von Dreads**."
        )

    async with data_lock:
        d = load_data()
        g = await get_guild_state(d, guild_id)
        g["active_event"] = False
        await save_data(d)

# -------------------- SLASH COMMANDS --------------------

@bot.tree.command(name="vondreads", description="Lets see them bands...")
@app_commands.describe(member="Check someone's Von Dreads")
async def vondreads(interaction, member: discord.Member | None = None):
    target = member or interaction.user
    d = load_data()
    bal = d["users"].get(str(target.id), {}).get("von_dreads", 0)
    await interaction.response.send_message(
        f"{target.mention} has got **{bal} Von Dreads**."
    )

@bot.tree.command(name="daily", description="Von still provides for the community. Take a daily reward.")
async def daily(interaction):
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    d = load_data()
    cd = d.setdefault("cooldowns", {}).setdefault("daily", {})
    last = cd.get(str(interaction.user.id))

    if last:
        last_dt = datetime.fromisoformat(last)
        if now < last_dt + timedelta(hours=24):
            remaining = (last_dt + timedelta(hours=24)) - now
            embed = discord.Embed(
                description=f"Don't be gettin greedy now homie... Come back in **{remaining}**"
            )
            embed.set_author(
                name=interaction.user.display_name,
                icon_url=interaction.user.display_avatar.url
            )
            await interaction.response.send_message(embed=embed)
            return

    reward = random.randint(20, 100)
    async with data_lock:
        d = load_data()
        u = d["users"].setdefault(str(interaction.user.id), {})
        u["von_dreads"] = u.get("von_dreads", 0) + reward
        d["cooldowns"]["daily"][str(interaction.user.id)] = now.isoformat()
        await save_data(d)

    await interaction.response.send_message(
        f"Von still provides for the community. You got **{reward} Von Dreads**."
    )

@bot.tree.command(name="pray", description="Pray to the spirit of Von (3 tries per real-world hour).")
async def pray(interaction: discord.Interaction):
    # Blocks Legends from praying (Legend of the Raq)
    d = load_data()
    # helper: get the user's title safely
    def _user_title(data, uid: str):
        return data.get("users", {}).get(uid, {}).get("title")

    if _user_title(d, str(interaction.user.id)) == "Legend of the Raq":
        embed = discord.Embed(
            title="No One Prays at the Top",
            description=(
                "You rule the streets now, everyone fears your name… but you can't pray no more… you betrayed Von, remember?"
            )
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    hour = datetime.utcnow().strftime("%Y-%m-%dT%H")
    state = d.setdefault("pray_state", {}).setdefault(
        str(interaction.user.id),
        {"hour": hour, "attempts": 0, "penalized": False}
    )

    if state["hour"] != hour:
        state.update({"hour": hour, "attempts": 0, "penalized": False})

    state["attempts"] = state.get("attempts", 0) + 1
    attempts = state["attempts"]

    # Overuse handling
    if attempts > 3:
        if attempts == 10 and not state.get("penalized", False):
            async with data_lock:
                d = load_data()
                u = d.setdefault("users", {}).setdefault(str(interaction.user.id), {})
                u["von_dreads"] = max(0, u.get("von_dreads", 0) - 80)
                # mark penalized so it only happens once
                ps = d.setdefault("pray_state", {}).setdefault(str(interaction.user.id), {})
                ps["penalized"] = True
                ps["hour"] = hour
                ps["attempts"] = attempts
                await save_data(d)
            await interaction.response.send_message(
                f"YOU JUST PISSED OFF VON. HE STOLE **-80 Von Dreads** from {interaction.user.mention}.",
                ephemeral=False
            )
            return
        # normal overuse reply
        async with data_lock:
            d = load_data()
            # persist increased attempts
            d.setdefault("pray_state", {})[str(interaction.user.id)] = state
            await save_data(d)
        await interaction.response.send_message("Go home man, before you upset Von.", ephemeral=True)
        return

    # Allowed pray attempt (one of the first 3 this hour)
    r = random.random()
    # Probabilities:
    # 0.00 - 0.45 -> win 1-10
    # 0.45 - 0.55 -> lose 1-10 (von don't like)
    # 0.55 - 0.80 -> lose 1-10 (misbehaving)
    # 0.80 - 0.95 -> nothing
    # 0.95 - 1.00 -> jackpot +50
    outcome_text = ""
    delta = 0

    if r < 0.45:
        delta = random.randint(1, 10)
        outcome_text = f"Von respects you... you won **{delta} Von Dreads**"
    elif r < 0.55:
        delta = -random.randint(1, 10)
        outcome_text = f"Von don't like you... he took **{abs(delta)} Von Dreads**."
    elif r < 0.80:
        delta = -random.randint(1, 10)
        outcome_text = f"Von thinks you been misbehavin'... he took **{abs(delta)} Von Dreads**."
    elif r < 0.95:
        delta = 0
        outcome_text = "Even though you had such audacity to bother Von, he decided to spare you. No change."
    else:
        delta = 50
        outcome_text = "YOU WON THE LEGENDARY VON JACKPOT... +50 DREADS"

    # apply delta under lock and persist pray_state
    async with data_lock:
        d = load_data()
        u = d.setdefault("users", {}).setdefault(str(interaction.user.id), {})
        old = u.get("von_dreads", 0)
        new = max(0, old + delta)
        u["von_dreads"] = new
        # persist pray_state updates
        d.setdefault("pray_state", {})[str(interaction.user.id)] = state
        await save_data(d)

    await interaction.response.send_message(f"{interaction.user.mention} — {outcome_text}\nTotal: **{new} Von Dreads**", ephemeral=False)

@bot.tree.command(name="givedreads", description="(Owner) Give Von Dreads to a user")
@app_commands.check(is_owner)
async def givedreads(interaction, member: discord.Member, amount: int):
    amount = max(1, min(amount, MAX_GIVE))
    async with data_lock:
        d = load_data()
        u = d["users"].setdefault(str(member.id), {})
        u["von_dreads"] = u.get("von_dreads", 0) + amount
        await save_data(d)
    await interaction.response.send_message(
        f"A bot developer just gave {member.mention} **{amount} Von Dreads**.",
        ephemeral=True
    )

@bot.tree.command(name="removedreads", description="(Owner) Wipe a user's Von Dreads")
@app_commands.check(is_owner)
async def removedreads(interaction, member: discord.Member):
    async with data_lock:
        d = load_data()
        d["users"].setdefault(str(member.id), {})["von_dreads"] = 0
        await save_data(d)
    await interaction.response.send_message(
        f"Oh shit man... a bot developer just wiped {member.mention}'s Von Dreads to **0**...",
        ephemeral=True
    )

# -------------------- SHOP / INVENTORY / TITLES --------------------
# Requires: load_data(), save_data(), data_lock, add_von_dreads(), OWNER_ID constant
# Place this after those existing helpers in your bot file.

BASE_ASSET_URL = "https://raw.githubusercontent.com/jeckafarrell218-byte/bot-assets/main/"

# Catalog definitions
ITEM_CATALOG = {
    "glock": {
        "display": "Glock",
        "file": "glock-item.png",
        "price": 200,
        "uses": 10,
        "description": "Pop yo opponents with this, it does a ton of damage.",
    },
    "switch": {
        "display": "Switch",
        "file": "switch-item.png",
        "price": 50,
        "uses": 1,
        "description": "50/50 chance to drop ya opps or damage you...",
    },
    "crowbar": {
        "display": "Crowbar",
        "file": "crowbar-item.png",
        "price": 200,
        "uses": 5,
        "description": "You can't go robbin people without this.",
    },
    "mask": {
        "display": "Mask",
        "file": "mask-item.png",
        "price": 25,
        "uses": 1,
        "description": "Got the 12 or some rivals on your ass? This mask will help you keep your dreads homie.",
    },
    "nerf": {
        "display": "Nerf Gun",
        "file": "nerf-item.png",
        "price": 10,
        "uses": 1,
        "description": "Mostly does 1 damage, but it's got a 1% chance to slime anyone out instantly with 1000 damage.",
    },
    "von_blessing": {
        "display": "Von Blessing",
        "file": "von-blessing-item.png",
        "price": 1000,
        "uses": 1,  # default single-use "save one consequence" or 3-use "triple rewards" instances can be encoded in instance metadata
        "description": "A blessing straight from Von himself. Triple rewards for up to three games, or escape 1 consequence.",
    }
}

# Title catalog: ordered list enforces buy-chain
TITLE_ORDER = [
    "Lil Von",
    "Certified Stepper",
    "O-Block Resident",
    "Von's Right Hand Man",
    "Legend of the Raq",
]

TITLE_CATALOG = {
    "Lil Von": {
        "cost": 10,
        "desc_lines": [
            "Get a Beginner's Luck +4 attack damage bonus on every attack",
            "Get access to O-Block raiding"
        ],
    },
    "Certified Stepper": {
        "cost": 100,
        "desc_lines": [
            "With this title, you can now join gangs",
            "Mostly a skill gate for intermediate-beginners..."
        ],
    },
    "O-Block Resident": {
        "cost": 500,
        "desc_lines": [
            "Get the ability to create your own gang",
            "Get a level up bonus of 10 free masks, 3 glocks, a switch, and a lucky Von blessing..."
        ],
        # included pack
        "pack": {"mask": 10, "glock": 3, "switch": 1, "von_blessing": 1},
    },
    "Von's Right Hand Man": {
        "cost": 1000,
        "desc_lines": [
            "The odds of using a Switch twist in your favor to 65/35",
            "Glocks get a permanent 50% discount",
            "Level up bonus of 3 Von blessings."
        ],
        "pack": {"von_blessing": 3},
    },
    "Legend of the Raq": {
        "cost": 50000,
        "desc_lines": [
            "Once you get this, you've overthrown Von himself and been crowned the ruler of the hood.",
            "Lose access to /pray command and gain access to a much more rewarding /fightvon minigame.",
            "Permanent 2× multiplier on ALL Von Dreads you gain.",
            "Sharp attack bonus for O-Block raids... you'll now be able to solo bosses alone.",
            "Boosted damage in /slimetheopps minigame.",
            "Your gang members get a rewards multiplier everytime they win a PvP game",
            "Glocks get a 75% discount",
            "Unlock the 'Fight Back' ability when you get caught in /duckthesirens",
            "Become the undisputed ruler of O-Block and the hood",
        ],
        "pack": {},
    },
}

# -------------------- Inventory helpers --------------------

def get_user_node(d, user_id: str):
    """Ensure user node exists and return it."""
    u = d.setdefault("users", {}).setdefault(user_id, {})
    u.setdefault("von_dreads", 0)
    u.setdefault("inventory", {})  # dict: item_id -> list of instances
    u.setdefault("title", None)
    return u

def give_item_to_user(d, user_id: str, item_id: str, quantity: int = 1, uses: int | None = None):
    """
    Add quantity instances of item_id to user's inventory. Each instance is a dict
    with 'uses_left' and optional metadata.
    """
    if item_id not in ITEM_CATALOG:
        return False
    inv = get_user_node(d, user_id)["inventory"]
    inv.setdefault(item_id, [])
    for _ in range(quantity):
        # default uses from catalog unless overridden
        instance_uses = ITEM_CATALOG[item_id].get("uses", 1) if uses is None else uses
        inv[item_id].append({"uses_left": int(instance_uses)})
    return True

def consume_item_instance(d, user_id: str, item_id: str):
    """
    Consume one instance of an item for the user (used by item effects).
    Returns the instance dict if consumed, else None.
    """
    u = get_user_node(d, user_id)
    inv = u["inventory"]
    lst = inv.get(item_id, [])
    if not lst:
        return None
    # pop first instance with uses > 0
    for idx, inst in enumerate(lst):
        if inst.get("uses_left", 0) > 0:
            inst["uses_left"] -= 1
            consumed = dict(inst)
            # remove instance if uses_left == 0
            if inst["uses_left"] <= 0:
                lst.pop(idx)
            # persist will be handled by caller
            return consumed
    return None

def get_item_price_for_user(d, user_id: str, item_id: str) -> int:
    """
    Returns the effective price for a user, applying title discounts if relevant.
    """
    base = ITEM_CATALOG[item_id]["price"]
    u = get_user_node(d, user_id)
    title = u.get("title")
    # Von's Right Hand Man -> 50% off glocks
    if item_id == "glock":
        if title == "Von's Right Hand Man":
            return max(1, base // 2)
        if title == "Legend of the Raq":
            return max(1, base * 25 // 100)  # 75% off
    # other discounts (if any) go here
    return base

def user_has_title(d, user_id: str, title_name: str) -> bool:
    u = get_user_node(d, user_id)
    return u.get("title") == title_name

def user_title(d, user_id: str):
    u = get_user_node(d, user_id)
    return u.get("title")

# Convenience checks
def is_lilvon(d, user_id: str) -> bool:
    return user_title(d, user_id) == "Lil Von"

def is_legend(d, user_id: str) -> bool:
    return user_title(d, user_id) == "Legend of the Raq"

# -------------------- Shop UI (embed pages) --------------------

def build_shop_embed(page:int=0):
    """
    page 0: main items (glock, switch, crowbar, mask)
    page 1: more items (nerf, von blessing)
    page 2: titles list
    """
    if page == 0:
        e = discord.Embed(title="Common Items", description="Use /buy <item|title> to purchase.")
        # show each item with field
        items = ["glock", "switch", "crowbar", "mask"]
        for key in items:
            it = ITEM_CATALOG[key]
            e.add_field(name=f"{it['display']} — {it['price']} Dreads", value=it["description"], inline=True)
        # set a representative image (glock)
        e.set_image(url=f"{BASE_ASSET_URL}{ITEM_CATALOG['glock']['file']}")
        e.set_footer(text="Press More Items... to see more and Titles for role purchases.")
        return e
    elif page == 1:
        e = discord.Embed(title="Other Items", description="Use /buy <item|title> to purchase.")
        items = ["nerf", "von_blessing"]
        for key in items:
            it = ITEM_CATALOG[key]
            e.add_field(name=f"{it['display']} — {it['price']} Dreads", value=it["description"], inline=False)
        e.set_image(url=f"{BASE_ASSET_URL}{ITEM_CATALOG['nerf']['file']}")
        e.set_footer(text="Titles are available on the Titles page.")
        return e
    elif page == 2:
        e = discord.Embed(title="Shop — Titles", description="Titles are purchased in order. Buying a title removes your previous title.")
        # long title list
        for t in TITLE_ORDER:
            info = TITLE_CATALOG[t]
            cost = info["cost"]
            desc = "\n".join(f"• {line}" for line in info["desc_lines"])
            e.add_field(name=f"{t} — Cost: {cost} Dreads", value=desc, inline=False)
        e.set_footer(text="Titles are permanent purchases. Make sure you meet the chain requirements.")
        return e
    else:
        return discord.Embed(title="Shop", description="Invalid page.")

class ShopNavView(discord.ui.View):
    def __init__(self, *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.page = 0

    async def update_message(self, interaction: discord.Interaction):
        embed = build_shop_embed(self.page)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            # fallback if response already used
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                try:
                    msg = await interaction.original_response()
                    await msg.edit(embed=embed, view=self)
                except Exception:
                    pass

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="shop_prev")
    async def prev_btn(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self.update_message(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="shop_next")
    async def next_btn(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.page = min(2, self.page + 1)
        await self.update_message(interaction)

    @discord.ui.button(label="More items...", style=discord.ButtonStyle.primary, custom_id="shop_more")
    async def more_btn(self, button: discord.ui.Button, interaction: discord.Interaction):
        # if currently on page 0, go to page 1, else cycle to page 0
        if self.page == 0:
            self.page = 1
        else:
            self.page = 0
        await self.update_message(interaction)

    @discord.ui.button(label="Titles", style=discord.ButtonStyle.primary, custom_id="shop_titles")
    async def titles_btn(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.page = 2
        await self.update_message(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="shop_close")
    async def close_btn(self, button: discord.ui.Button, interaction: discord.Interaction):
        # disable view and edit message
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(content="Shop closed.", embed=None, view=self)
        except Exception:
            # fallback: try editing the original response (if possible), otherwise fetch and edit the message
            try:
                await interaction.edit_original_response(content="Shop closed.", embed=None, view=self)
            except Exception:
                try:
                    msg = await interaction.original_response()
                    await msg.edit(content="Shop closed.", embed=None, view=self)
                except Exception:
                    pass
        self.stop()

# Slash command to open shop
@bot.tree.command(name="shop", description="Buy titles, weapons, and useful tools.")
async def shop(interaction: discord.Interaction):
    v = ShopNavView()
    embed = build_shop_embed(0)
    await interaction.response.send_message(embed=embed, view=v, ephemeral=False)

# -------------------- RUN BOT --------------------

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable not set.")
    
    # 1. Start the Flask website in the background
    keep_alive() 
    
    # 2. Start the Discord bot
    bot.run(TOKEN)
