import os
import io
import re
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import discord
from discord.ext import commands


# =========================================================
# CONFIG
# =========================================================

TOKEN = ""
DATA_FILE = Path("fusioncollab_v2_data.json")

HELP_COLOR = 0x18191C
DEFAULT_EMBED_COLOR = 0x2B2D31

DEFAULT_DATA = {
    "prefix": ".",
    "panels": {},
    "tickets": {},
    "claims": {}
}

DEFAULT_PANEL = {
    "title": "FusionCollab",
    "description": "Create a private ticket to continue.",
    "embed_color": DEFAULT_EMBED_COLOR,
    "button_label": "Create Ticket",
    "button_emoji": None,
    "button_style": "secondary",
    "footer": "FusionCollab",
    "thumbnail": None
}

DEFAULT_TYPE = {
    "label": "Deals",
    "description": "Open this ticket type",
    "emoji": None,
    "category_id": None,
    "log_channel_id": None,
    "staff_roles": [],
    "viewer_roles": [],
    "ticket_prefix": "deal",
    "ticket_title": "Private Room",
    "ticket_message": "Welcome to your private space.\nState your purpose clearly.\nA team member will assist you shortly.",
    "embed_color": DEFAULT_EMBED_COLOR,
    "max_open_per_user": 1,
    "close_delay": 3,

    "claim_button_label": "Claim",
    "claim_button_emoji": None,
    "claim_button_style": "primary",

    "close_button_label": "Close",
    "close_button_emoji": None,
    "close_button_style": "danger",

    "transcript_button_label": "Transcript",
    "transcript_button_emoji": None,
    "transcript_button_style": "secondary",

    "reopen_button_emoji": "🔓",
    "delete_button_emoji": "🗑️",
    "confirm_close_button_emoji": "🔒",
    "cancel_button_emoji": "↩️",
}

# =========================================================
# STORAGE
# =========================================================

def deep_copy(value):
    return json.loads(json.dumps(value))


def ensure_data_file():
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps(deep_copy(DEFAULT_DATA), indent=2), encoding="utf-8")


def load_data() -> dict:
    ensure_data_file()
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        raw = deep_copy(DEFAULT_DATA)

    for key, value in DEFAULT_DATA.items():
        if key not in raw or not isinstance(raw[key], type(value)):
            raw[key] = deep_copy(value)

    return raw


def save_data():
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


data = load_data()


# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

async def get_prefix(bot, message):
    return data.get("prefix", ".")

bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=None,
    case_insensitive=True
)


# =========================================================
# HELPERS
# =========================================================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_newlines(value: str) -> str:
    return value.replace("\\n", "\n")


def sanitize_channel_name(name: str) -> str:
    name = name.strip().lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:95] or "ticket-room"


def extract_id(raw: str) -> Optional[int]:
    if raw is None:
        return None
    raw = str(raw).strip()
    if raw.isdigit():
        return int(raw)
    match = re.search(r"(\d{15,25})", raw)
    if match:
        return int(match.group(1))
    return None


def extract_many_ids(raw: str) -> List[int]:
    return [int(x) for x in re.findall(r"\d{15,25}", str(raw))]


def parse_hex_color(value: str) -> int:
    value = value.strip().replace("#", "")
    return int(value, 16)


def style_from_name(name: str) -> discord.ButtonStyle:
    mapping = {
        "primary": discord.ButtonStyle.primary,
        "secondary": discord.ButtonStyle.secondary,
        "success": discord.ButtonStyle.success,
        "danger": discord.ButtonStyle.danger,
    }
    return mapping.get(str(name).lower(), discord.ButtonStyle.secondary)


def parse_button_emoji(value):
    if not value:
        return None

    value = str(value).strip()
    if not value or value.lower() == "none":
        return None

    try:
        return discord.PartialEmoji.from_str(value)
    except Exception:
        return value


def get_panel(panel_key: str) -> Optional[dict]:
    return data["panels"].get(panel_key.lower())


def set_panel(panel_key: str, panel: dict):
    data["panels"][panel_key.lower()] = panel
    save_data()


def delete_panel(panel_key: str):
    data["panels"].pop(panel_key.lower(), None)
    save_data()


def panel_with_defaults(panel: dict) -> dict:
    merged = deep_copy(DEFAULT_PANEL)
    merged.update(panel)
    merged.setdefault("types", {})
    return merged


def ticket_type_with_defaults(ticket_type: dict) -> dict:
    merged = deep_copy(DEFAULT_TYPE)
    merged.update(ticket_type)
    return merged


def is_ticket_channel(channel: discord.abc.GuildChannel) -> bool:
    return str(channel.id) in data["tickets"]


def get_ticket_meta(channel_id: int) -> Optional[dict]:
    return data["tickets"].get(str(channel_id))


def set_ticket_meta(channel_id: int, meta: dict):
    data["tickets"][str(channel_id)] = meta
    save_data()


def delete_ticket_meta(channel_id: int):
    data["tickets"].pop(str(channel_id), None)
    data["claims"].pop(str(channel_id), None)
    save_data()


def get_claim(channel_id: int) -> Optional[int]:
    value = data["claims"].get(str(channel_id))
    return int(value) if value is not None else None


def set_claim(channel_id: int, user_id: Optional[int]):
    if user_id is None:
        data["claims"].pop(str(channel_id), None)
    else:
        data["claims"][str(channel_id)] = int(user_id)
    save_data()


def ticket_owner_id(channel_id: int) -> Optional[int]:
    meta = get_ticket_meta(channel_id)
    if not meta:
        return None
    return int(meta["owner_id"])


def format_ticket_name(prefix: str, member: discord.Member) -> str:
    base = member.display_name.lower().replace(" ", "-")
    base = re.sub(r"[^a-z0-9\-]", "", base)
    base = base[:70] or str(member.id)
    return sanitize_channel_name(f"{prefix}-{base}")


def panel_embed(panel: dict) -> discord.Embed:
    panel = panel_with_defaults(panel)
    embed = discord.Embed(
        title=panel["title"],
        description=panel["description"],
        color=panel["embed_color"],
        timestamp=now_utc()
    )
    embed.set_footer(text=panel.get("footer", "FusionCollab"))
    if panel.get("thumbnail"):
        embed.set_thumbnail(url=panel["thumbnail"])
    return embed


def ticket_embed(panel: dict, ticket_type: dict) -> discord.Embed:
    panel = panel_with_defaults(panel)
    ticket_type = ticket_type_with_defaults(ticket_type)

    embed = discord.Embed(
        title=ticket_type["ticket_title"],
        description=ticket_type["ticket_message"],
        color=ticket_type["embed_color"],
        timestamp=now_utc()
    )
    embed.set_footer(text=panel.get("footer", "FusionCollab"))
    if panel.get("thumbnail"):
        embed.set_thumbnail(url=panel["thumbnail"])
    return embed


def member_has_staff_access(member: discord.Member, panel_key: str, type_key: str) -> bool:
    if member.guild_permissions.administrator:
        return True

    panel = get_panel(panel_key)
    if not panel:
        return False

    panel = panel_with_defaults(panel)
    ticket_type = panel["types"].get(type_key.lower())
    if not ticket_type:
        return False

    ticket_type = ticket_type_with_defaults(ticket_type)
    role_ids = {role.id for role in member.roles}
    return any(int(role_id) in role_ids for role_id in ticket_type.get("staff_roles", []))


def build_overwrites(
    guild: discord.Guild,
    owner: discord.Member,
    ticket_type: dict
) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    ticket_type = ticket_type_with_defaults(ticket_type)
    overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        owner: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )
    }

    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True
        )

    for role_id in ticket_type.get("staff_roles", []):
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

    for role_id in ticket_type.get("viewer_roles", []):
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True
            )

    return overwrites


async def create_transcript_file(channel: discord.TextChannel) -> discord.File:
    lines = []
    async for message in channel.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        content = message.content or ""
        if message.attachments:
            content += "\nAttachments: " + ", ".join(a.url for a in message.attachments)
        if message.embeds:
            content += f"\n[Embeds: {len(message.embeds)}]"
        lines.append(f"[{timestamp}] {message.author} ({message.author.id}): {content}")

    stream = io.BytesIO("\n".join(lines).encode("utf-8"))
    return discord.File(stream, filename=f"{channel.name}-transcript.txt")


async def send_type_log(guild: discord.Guild, panel_key: str, type_key: str, content: str, file: Optional[discord.File] = None):
    panel = get_panel(panel_key)
    if not panel:
        return

    panel = panel_with_defaults(panel)
    ticket_type = panel["types"].get(type_key.lower())
    if not ticket_type:
        return

    ticket_type = ticket_type_with_defaults(ticket_type)
    log_channel_id = ticket_type.get("log_channel_id")
    if not log_channel_id:
        return

    channel = guild.get_channel(int(log_channel_id))
    if isinstance(channel, discord.TextChannel):
        if file:
            await channel.send(content=content, file=file)
        else:
            await channel.send(content)


async def safe_send(ctx_or_interaction, content=None, embed=None, ephemeral=False, file=None, view=None):
    if isinstance(ctx_or_interaction, commands.Context):
        return await ctx_or_interaction.send(content=content, embed=embed, file=file, view=view)
    if isinstance(ctx_or_interaction, discord.Interaction):
        if ctx_or_interaction.response.is_done():
            return await ctx_or_interaction.followup.send(content=content, embed=embed, file=file, ephemeral=ephemeral, view=view)
        return await ctx_or_interaction.response.send_message(content=content, embed=embed, file=file, ephemeral=ephemeral, view=view)


async def open_ticket_for_member(guild: discord.Guild, member: discord.Member, panel_key: str, type_key: str):
    panel = get_panel(panel_key)
    if not panel:
        return None, "Panel not found."

    panel = panel_with_defaults(panel)
    ticket_type = panel["types"].get(type_key.lower())
    if not ticket_type:
        return None, "Ticket type not found."

    ticket_type = ticket_type_with_defaults(ticket_type)

    if not ticket_type.get("category_id"):
        return None, "This ticket type has no category configured."

    category = guild.get_channel(int(ticket_type["category_id"]))
    if not isinstance(category, discord.CategoryChannel):
        return None, "Configured category was not found."

    max_open = int(ticket_type.get("max_open_per_user", 1))
    current_open = 0

    for channel_id, meta in data["tickets"].items():
        if (
            meta.get("panel_key") == panel_key.lower()
            and meta.get("type_key") == type_key.lower()
            and int(meta.get("owner_id", 0)) == member.id
        ):
            ch = guild.get_channel(int(channel_id))
            if isinstance(ch, discord.TextChannel):
                current_open += 1

    if current_open >= max_open:
        return None, f"You already have the maximum open tickets for `{type_key}`."

    name = format_ticket_name(ticket_type.get("ticket_prefix", "ticket"), member)
    overwrites = build_overwrites(guild, member, ticket_type)

    channel = await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        topic=f"owner={member.id} panel={panel_key.lower()} type={type_key.lower()} created={now_utc().isoformat()}",
        reason=f"Ticket opened by {member}"
    )

    set_ticket_meta(channel.id, {
        "owner_id": member.id,
        "panel_key": panel_key.lower(),
        "type_key": type_key.lower(),
        "created_at": now_utc().isoformat()
    })

    await channel.send(
        content=member.mention,
        embed=ticket_embed(panel, ticket_type),
        view=TicketControlsView(panel_key.lower(), type_key.lower())
    )

    await send_type_log(
        guild,
        panel_key.lower(),
        type_key.lower(),
        f"🟢 Opened: {channel.mention} | Owner: {member.mention} | Panel: `{panel_key.lower()}` | Type: `{type_key.lower()}`"
    )

    return channel, None

SETUPCHECK_OK = 0x57F287
SETUPCHECK_WARN = 0xFEE75C
SETUPCHECK_BAD = 0xED4245


def setupcheck_type_snapshot(guild: discord.Guild, panel_key: str, type_key: str, ticket_type: dict) -> dict:
    ticket_type = ticket_type_with_defaults(ticket_type)

    category = None
    log_channel = None

    if ticket_type.get("category_id"):
        category = guild.get_channel(int(ticket_type["category_id"]))

    if ticket_type.get("log_channel_id"):
        log_channel = guild.get_channel(int(ticket_type["log_channel_id"]))

    valid_staff_roles = []
    missing_staff_roles = []
    for role_id in ticket_type.get("staff_roles", []):
        role = guild.get_role(int(role_id))
        if role:
            valid_staff_roles.append(role)
        else:
            missing_staff_roles.append(int(role_id))

    valid_viewer_roles = []
    missing_viewer_roles = []
    for role_id in ticket_type.get("viewer_roles", []):
        role = guild.get_role(int(role_id))
        if role:
            valid_viewer_roles.append(role)
        else:
            missing_viewer_roles.append(int(role_id))

    message_customized = any(
        ticket_type.get(field) != DEFAULT_TYPE[field]
        for field in ("ticket_title", "ticket_message", "ticket_prefix", "embed_color")
    )

    buttons_customized = any(
        ticket_type.get(field) != DEFAULT_TYPE[field]
        for field in (
            "claim_button_label",
            "claim_button_emoji",
            "claim_button_style",
            "close_button_label",
            "close_button_emoji",
            "close_button_style",
            "transcript_button_label",
            "transcript_button_emoji",
            "transcript_button_style",
        )
    )

    critical_missing = []
    improve = []

    if not isinstance(category, discord.CategoryChannel):
        critical_missing.append("Category")
    if len(valid_staff_roles) == 0:
        critical_missing.append("Staff Roles")

    if not ticket_type.get("log_channel_id"):
        improve.append("Log Channel")
    elif not isinstance(log_channel, discord.TextChannel):
        improve.append("Log Channel Invalid")

    if len(valid_viewer_roles) == 0:
        improve.append("Viewer Roles")

    if missing_staff_roles:
        improve.append("Missing Staff Role IDs")

    if missing_viewer_roles:
        improve.append("Missing Viewer Role IDs")

    if not message_customized:
        improve.append("Messages Using Defaults")

    if not buttons_customized:
        improve.append("Buttons Using Defaults")

    ready = len(critical_missing) == 0
    health = "good" if ready and not improve else "warn" if ready else "bad"

    return {
        "panel_key": panel_key.lower(),
        "type_key": type_key.lower(),
        "ticket_type": ticket_type,
        "category": category,
        "log_channel": log_channel,
        "valid_staff_roles": valid_staff_roles,
        "missing_staff_roles": missing_staff_roles,
        "valid_viewer_roles": valid_viewer_roles,
        "missing_viewer_roles": missing_viewer_roles,
        "message_customized": message_customized,
        "buttons_customized": buttons_customized,
        "critical_missing": critical_missing,
        "improve": improve,
        "ready": ready,
        "health": health,
    }


def setupcheck_color(health: str) -> int:
    return HELP_COLOR


def setupcheck_status_text(health: str) -> str:
    if health == "good":
        return "Ready"
    if health == "warn":
        return "Needs Polish"
    return "Needs Setup"


def setupcheck_code_block(text: str) -> str:
    return f"```txt\n{text}\n```"


def make_setupcheck_embed(title: str, subtitle: str) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=subtitle,
        color=HELP_COLOR,
        timestamp=now_utc()
    )
    embed.set_author(name="FusionCollab Admin Guide")
    return embed


def build_setupcheck_type_pages(guild: discord.Guild, panel_key: str, type_key: str, panel: dict, ticket_type: dict) -> list[discord.Embed]:
    panel = panel_with_defaults(panel)
    snapshot = setupcheck_type_snapshot(guild, panel_key, type_key, ticket_type)
    prefix = data.get("prefix", ".")

    status_text = setupcheck_status_text(snapshot["health"])
    category_text = snapshot["category"].mention if isinstance(snapshot["category"], discord.CategoryChannel) else "`Not set`"
    log_text = snapshot["log_channel"].mention if isinstance(snapshot["log_channel"], discord.TextChannel) else "`Not set`"
    staff_text = ", ".join(role.mention for role in snapshot["valid_staff_roles"]) or "`None set`"

    missing_text = ", ".join(snapshot["critical_missing"]) if snapshot["critical_missing"] else "Nothing critical missing."
    improve_text = ", ".join(snapshot["improve"]) if snapshot["improve"] else "Nothing important to improve right now."

    next_commands = []
    if "Category" in snapshot["critical_missing"]:
        next_commands.append(f"{prefix}typeset {panel_key.lower()} {type_key.lower()} category_id <category_id>")
    if "Staff Roles" in snapshot["critical_missing"]:
        next_commands.append(f"{prefix}typeset {panel_key.lower()} {type_key.lower()} staff_roles <role_ids>")
    if "Log Channel" in snapshot["improve"]:
        next_commands.append(f"{prefix}typeset {panel_key.lower()} {type_key.lower()} log_channel_id <channel_id>")
    if "Messages Using Defaults" in snapshot["improve"]:
        next_commands.append(f"{prefix}typeset {panel_key.lower()} {type_key.lower()} ticket_message <text>")
    if "Buttons Using Defaults" in snapshot["improve"]:
        next_commands.append(f"{prefix}help buttons")
    if not next_commands:
        next_commands.append(f"{prefix}new {panel_key.lower()} {type_key.lower()}")

    page1 = make_setupcheck_embed(
        "FusionCollab Setup Check",
        (
            f"**Panel:** `{panel_key.lower()}`\n"
            f"**Type:** `{type_key.lower()}`\n\n"
            f"**Status**\n{status_text}"
        )
    )
    page1.add_field(
        name="Overview",
        value=(
            f"**Category**\n{category_text}\n\n"
            f"**Log Channel**\n{log_text}\n\n"
            f"**Staff Roles**\n{staff_text}"
        ),
        inline=False
    )
    page1.add_field(
        name="Missing",
        value=missing_text,
        inline=False
    )
    page1.add_field(
        name="Could Improve",
        value=improve_text,
        inline=False
    )
    page1.add_field(
        name="Next Command",
        value=setupcheck_code_block(next_commands[0]),
        inline=False
    )
    page1.set_footer(text="Page 1/2 • Setup Audit")

    page2 = make_setupcheck_embed(
        "FusionCollab Setup Check",
        (
            f"**Panel:** `{panel_key.lower()}`\n"
            f"**Type:** `{type_key.lower()}`\n\n"
            f"**Details**"
        )
    )
    page2.add_field(
        name="Presentation",
        value=(
            f"**Ticket Title**\n`{snapshot['ticket_type']['ticket_title']}`\n\n"
            f"**Ticket Prefix**\n`{snapshot['ticket_type']['ticket_prefix']}`\n\n"
            f"**Messages**\n{'Customized' if snapshot['message_customized'] else 'Using defaults'}\n\n"
            f"**Buttons**\n{'Customized' if snapshot['buttons_customized'] else 'Using defaults'}"
        ),
        inline=False
    )
    page2.add_field(
        name="Test",
        value=f"Run `{prefix}new {panel_key.lower()} {type_key.lower()}` and verify the ticket opens, looks correct, and logs properly.",
        inline=False
    )
    page2.set_footer(text="Page 2/2 • Setup Audit")

    return [page1, page2]


def build_setupcheck_panel_pages(guild: discord.Guild, panel_key: str, panel: dict) -> list[discord.Embed]:
    panel = panel_with_defaults(panel)
    prefix = data.get("prefix", ".")
    panel_types = panel.get("types", {})

    snapshots = [
        setupcheck_type_snapshot(guild, panel_key, type_key, ticket_type)
        for type_key, ticket_type in panel_types.items()
    ]

    if not panel_types:
        health = "bad"
    else:
        bad_count = sum(1 for x in snapshots if x["health"] == "bad")
        warn_count = sum(1 for x in snapshots if x["health"] == "warn")
        health = "good" if bad_count == 0 and warn_count == 0 else "warn" if bad_count == 0 else "bad"

    status_text = setupcheck_status_text(health)

    type_lines = []
    for type_key, ticket_type in panel_types.items():
        snapshot = setupcheck_type_snapshot(guild, panel_key, type_key, ticket_type)
        state = "Ready" if snapshot["health"] == "good" else "Polish" if snapshot["health"] == "warn" else "Fix"
        type_lines.append(f"`{type_key}` — {state}")

    if not type_lines:
        type_lines = ["No ticket types added yet."]

    next_command = f"{prefix}setupcheck {panel_key.lower()} <type>"

    page1 = make_setupcheck_embed(
        "FusionCollab Setup Check",
        (
            f"**Panel:** `{panel_key.lower()}`\n\n"
            f"**Status**\n{status_text}"
        )
    )
    page1.add_field(
        name="Overview",
        value=(
            f"**Title**\n`{panel.get('title', 'FusionCollab')}`\n\n"
            f"**Button Label**\n`{panel.get('button_label', 'Create Ticket')}`\n\n"
            f"**Types Added**\n`{len(panel_types)}`"
        ),
        inline=False
    )
    page1.add_field(
        name="Type Status",
        value="\n".join(type_lines[:8]),
        inline=False
    )
    page1.add_field(
        name="Next Command",
        value=setupcheck_code_block(next_command),
        inline=False
    )
    page1.set_footer(text="Page 1/2 • Setup Audit")

    page2 = make_setupcheck_embed(
        "FusionCollab Setup Check",
        (
            f"**Panel:** `{panel_key.lower()}`\n\n"
            f"**Details**"
        )
    )
    page2.add_field(
        name="Test",
        value=f"Run `{prefix}setupcheck {panel_key.lower()} deals` or any other type key to inspect one type in detail.",
        inline=False
    )
    page2.add_field(
        name="Guide",
        value=f"Use `{prefix}help setup` if you want the full guided setup flow.",
        inline=False
    )
    page2.set_footer(text="Page 2/2 • Setup Audit")

    return [page1, page2]


class SetupCheckView(discord.ui.View):
    def __init__(self, author_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self.sync_buttons()

    def sync_buttons(self):
        self.back_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This setup check is not for you.", ephemeral=True)
            return False
        return True

    async def redraw(self, interaction: discord.Interaction):
        self.sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        await self.redraw(interaction)

    @discord.ui.button(label="⌂ Home", style=discord.ButtonStyle.secondary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = 0
        await self.redraw(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self.redraw(interaction)

    @discord.ui.button(label="✕", style=discord.ButtonStyle.danger, row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

def build_ticketstats_snapshot(guild: discord.Guild) -> dict:
    total_open = 0
    by_type = {}
    by_panel = {}

    for channel_id, meta in data["tickets"].items():
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            continue

        total_open += 1

        panel_key = str(meta.get("panel_key", "unknown")).lower()
        type_key = str(meta.get("type_key", "unknown")).lower()

        by_type[type_key] = by_type.get(type_key, 0) + 1
        by_panel[panel_key] = by_panel.get(panel_key, 0) + 1

    sorted_types = sorted(by_type.items(), key=lambda x: (-x[1], x[0]))
    sorted_panels = sorted(by_panel.items(), key=lambda x: (-x[1], x[0]))

    return {
        "total_open": total_open,
        "by_type": sorted_types,
        "by_panel": sorted_panels,
    }


def make_ticketstats_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=HELP_COLOR,
        timestamp=now_utc()
    )
    embed.set_author(name="FusionCollab Admin Guide")
    embed.set_footer(text="FusionCollab • Ticket Stats")
    return embed


def build_ticketstats_pages(guild: discord.Guild) -> list[discord.Embed]:
    snapshot = build_ticketstats_snapshot(guild)

    total_open = snapshot["total_open"]
    by_type = snapshot["by_type"]
    by_panel = snapshot["by_panel"]

    pages = []

    page1 = make_ticketstats_embed(
        "FusionCollab Ticket Stats",
        (
            f"**Overview**\n"
            f"Current open ticket activity across this server."
        )
    )
    page1.add_field(
        name="Open Tickets",
        value=f"`{total_open}` currently open",
        inline=False
    )
    page1.add_field(
        name="Ticket Types",
        value=f"`{len(by_type)}` active type(s)",
        inline=True
    )
    page1.add_field(
        name="Panels",
        value=f"`{len(by_panel)}` active panel(s)",
        inline=True
    )
    if by_type:
        top_types = "\n".join(f"`{name}` — {count}" for name, count in by_type[:5])
    else:
        top_types = "No open tickets right now."
    page1.add_field(
        name="Top Types",
        value=top_types,
        inline=False
    )
    page1.set_footer(text="Page 1/3 • Ticket Stats")
    pages.append(page1)

    page2 = make_ticketstats_embed(
        "FusionCollab Ticket Stats",
        (
            f"**Type Breakdown**\n"
            f"Open tickets grouped by ticket type."
        )
    )
    type_lines = "\n".join(f"`{name}` — {count}" for name, count in by_type) if by_type else "No open tickets right now."
    page2.add_field(
        name="By Type",
        value=type_lines,
        inline=False
    )
    page2.set_footer(text="Page 2/3 • Ticket Stats")
    pages.append(page2)

    page3 = make_ticketstats_embed(
        "FusionCollab Ticket Stats",
        (
            f"**Panel Breakdown**\n"
            f"Open tickets grouped by panel."
        )
    )
    panel_lines = "\n".join(f"`{name}` — {count}" for name, count in by_panel) if by_panel else "No open tickets right now."
    page3.add_field(
        name="By Panel",
        value=panel_lines,
        inline=False
    )
    page3.set_footer(text="Page 3/3 • Ticket Stats")
    pages.append(page3)

    return pages


class TicketStatsView(discord.ui.View):
    def __init__(self, author_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self.sync_buttons()

    def sync_buttons(self):
        self.back_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This ticket stats view is not for you.", ephemeral=True)
            return False
        return True

    async def redraw(self, interaction: discord.Interaction):
        self.sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        await self.redraw(interaction)

    @discord.ui.button(label="⌂ Home", style=discord.ButtonStyle.secondary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = 0
        await self.redraw(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self.redraw(interaction)

    @discord.ui.button(label="✕", style=discord.ButtonStyle.danger, row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True




# =========================================================
# HELP UI
# =========================================================

HELP_THUMBNAIL = None  # set to an image url later if you want


def make_code_block(value: str) -> str:
    return f"```txt\n{value}\n```"


def build_help_embed(category: str, prefix: str) -> discord.Embed:
    category = category.lower()

    pages = {
        "home": {
            "title": "FusionCollab Help",
            "description": (
                "A clean command center for tickets, staff tools, and admin setup.\n"
                "Use the buttons below to browse categories.\n\n"
                f"**Prefix:** `{prefix}`\n"
                f"**Admin Setup:** `{prefix}help setup`"
            ),
            "fields": [
                ("Quick Start", f"`{prefix}help setup` gives a full guided setup flow for admins.", False),
                ("Direct Guides", f"`{prefix}help panel` • `{prefix}help type` • `{prefix}help buttons` • `{prefix}help test`", False),
            ],
            "footer": "FusionCollab • Main Help"
        },
        "general": {
            "title": "📌 FusionCollab • General",
            "description": "General commands for navigation and quick checks.",
            "fields": [
                ("Commands", make_code_block(
                    f"{prefix}help\n"
                    f"{prefix}help setup\n"
                    f"{prefix}ping\n"
                    f"{prefix}new <panel> <type>"
                ), False),
                ("Notes", "Use `.help setup` for a guided admin walkthrough instead of memorizing everything.", False),
            ],
            "footer": "FusionCollab • General"
        },
        "tickets": {
            "title": "🎟️ FusionCollab • Tickets",
            "description": "User-facing ticket actions and ticket opening commands.",
            "fields": [
                ("Commands", make_code_block(
                    f"{prefix}new <panel> <type>\n"
                    f"{prefix}close"
                ), False),
                ("Notes", "Ticket action buttons are configured per ticket type, so each type can have its own style and branding.", False),
            ],
            "footer": "FusionCollab • Tickets"
        },
        "staff": {
            "title": "🛡️ FusionCollab • Staff",
            "description": "Staff moderation and ticket management tools.",
            "fields": [
                ("Commands", make_code_block(
                    f"{prefix}add @user\n"
                    f"{prefix}remove @user\n"
                    f"{prefix}rename <name>\n"
                    f"{prefix}claim\n"
                    f"{prefix}unclaim\n"
                    f"{prefix}lock\n"
                    f"{prefix}unlock\n"
                    f"{prefix}transcript\n"
                    f"{prefix}delete"
                ), False),
                ("Notes", "These commands are meant for configured staff roles or administrators inside managed tickets.", False),
                ("Closed Ticket Flow", "Close now uses confirmation. Staff can reopen or delete closed tickets.", False),
            ],
            "footer": "FusionCollab • Staff"
        },
        "admin": {
            "title": "⚙️ FusionCollab • Admin",
            "description": "Administrative commands for building and customizing your ticket system.",
            "fields": [
                ("Core Commands", make_code_block(
                    f"{prefix}setprefix <prefix>\n"
                    f"{prefix}panelcreate <key>\n"
                    f"{prefix}paneldelete <key>\n"
                    f"{prefix}panelsend <key> <channel>\n"
                    f"{prefix}panelset <key> <field> <value>\n"
                    f"{prefix}typeadd <panel> <type>\n"
                    f"{prefix}typedelete <panel> <type>\n"
                    f"{prefix}typeset <panel> <type> <field> <value>\n"
                    f"{prefix}typelist <panel>"
                ), False),
                ("Admin Tools", make_code_block(
                    f"{prefix}setupcheck <panel>\n"
                    f"{prefix}setupcheck <panel> <type>\n"
                    f"{prefix}ticketstats"
                ), False),
                ("Best Route", f"Use `{prefix}help setup` to build the whole system step by step.", False),
            ],
            "footer": "FusionCollab • Admin"
        },
        "panels": {
            "title": "🧩 FusionCollab • Panels",
            "description": "Panel fields and ticket type fields available in your current config system.",
            "fields": [
                ("Panel Fields", make_code_block(
                    "title\n"
                    "description\n"
                    "embed_color\n"
                    "button_label\n"
                    "button_emoji\n"
                    "button_style\n"
                    "footer\n"
                    "thumbnail"
                ), True),
                ("Type Fields", make_code_block(
                    "label\n"
                    "description\n"
                    "emoji\n"
                    "category_id\n"
                    "log_channel_id\n"
                    "staff_roles\n"
                    "viewer_roles\n"
                    "ticket_prefix\n"
                    "ticket_title\n"
                    "ticket_message\n"
                    "embed_color\n"
                    "max_open_per_user\n"
                    "close_delay\n"
                    "claim_button_label\n"
                    "claim_button_emoji\n"
                    "claim_button_style\n"
                    "close_button_label\n"
                    "close_button_emoji\n"
                    "close_button_style\n"
                    "transcript_button_label\n"
                    "transcript_button_emoji\n"
                    "transcript_button_style\n"
                    "reopen_button_emoji\n"
                    "delete_button_emoji\n"
                    "confirm_close_button_emoji\n"
                    "cancel_button_emoji"
                ), True),            ],
            "footer": "FusionCollab • Fields"
        },
        "config": {
            "title": "🧠 FusionCollab • Config",
            "description": "Formatting rules and config tips for cleaner setup.",
            "fields": [
                ("Formatting", make_code_block(
                    "Colors: #18191C\n"
                    "Channels: mentions or raw IDs\n"
                    "Roles: mentions or raw IDs\n"
                    "Multi-role fields: comma separated or pasted mentions\n"
                    "Custom emojis: <:name:id> or <a:name:id>"
                ), False),
                ("Advice", "Set categories, staff roles, and logs before sending your public panel.", False),
            ],
            "footer": "FusionCollab • Config"
        }
    }

    page = pages.get(category, pages["home"])

    embed = discord.Embed(
        title=page["title"],
        description=page["description"],
        color=HELP_COLOR,
        timestamp=now_utc()
    )

    for name, value, inline in page.get("fields", []):
        embed.add_field(name=name, value=value, inline=inline)

    if HELP_THUMBNAIL:
        embed.set_thumbnail(url=HELP_THUMBNAIL)

    embed.set_footer(text=page.get("footer", "FusionCollab"))
    return embed


SETUP_GUIDE_PAGES = [
    {
        "key": "overview",
        "title": "FusionCollab Setup",
        "step": "Overview",
        "summary": "This guide walks admins through the cleanest order to build a full ticket system without guessing.",
        "usage": (
            "Recommended order:\n"
            "1. Create panel\n"
            "2. Add ticket types\n"
            "3. Set categories\n"
            "4. Set staff and viewer roles\n"
            "5. Set log channels\n"
            "6. Customize ticket messages\n"
            "7. Customize ticket buttons\n"
            "8. Send panel and test"
        ),
        "example": (
            ".panelcreate main\n"
            ".typeadd main deals\n"
            ".typeadd main complaint\n"
            ".typeadd main support"
        ),
        "testing": "When setup is complete, test each type with a fresh ticket and verify claims, transcript, and close flow."
    },
    {
        "key": "panel",
        "title": "FusionCollab Setup",
        "step": "Step 1/8 • Create Panel",
        "summary": "A panel is the public ticket entry point users click to choose a ticket type.",
        "usage": (
            ".panelcreate <panel_key>\n"
            ".panelset <panel_key> title <text>\n"
            ".panelset <panel_key> description <text>\n"
            ".panelset <panel_key> button_label <text>\n"
            ".panelset <panel_key> button_emoji <emoji>\n"
            ".panelset <panel_key> button_style <primary|secondary|success|danger>"
        ),
        "example": (
            ".panelcreate main\n"
            ".panelset main title FusionCollab\n"
            ".panelset main description Open a private ticket below.\n"
            ".panelset main button_label Open Ticket\n"
            ".panelset main button_style primary"
        ),
        "testing": "After sending the panel later, confirm the public button appears with the right label, emoji, and style."
    },
    {
        "key": "type",
        "title": "FusionCollab Setup",
        "step": "Step 2/8 • Add Ticket Types",
        "summary": "Types let one panel open different ticket flows like deals, complaint, or support.",
        "usage": (
            ".typeadd <panel_key> <type_key>\n"
            ".typeset <panel> <type> label <text>\n"
            ".typeset <panel> <type> description <text>\n"
            ".typeset <panel> <type> emoji <emoji>"
        ),
        "example": (
            ".typeadd main deals\n"
            ".typeadd main complaint\n"
            ".typeadd main support\n"
            ".typeset main deals label Deals\n"
            ".typeset main complaint label Complaint"
        ),
        "testing": "Run `.typelist <panel>` and check that every type appears correctly."
    },
    {
        "key": "category",
        "title": "FusionCollab Setup",
        "step": "Step 3/8 • Set Categories",
        "summary": "Each ticket type must point to the category where its channels should open.",
        "usage": (
            ".typeset <panel> <type> category_id <category_id>"
        ),
        "example": (
            ".typeset main deals category_id 123456789012345678\n"
            ".typeset main complaint category_id 234567890123456789\n"
            ".typeset main support category_id 345678901234567890"
        ),
        "testing": "Open one fresh ticket for each type and confirm every ticket lands in the correct category."
    },
    {
        "key": "roles",
        "title": "FusionCollab Setup",
        "step": "Step 4/8 • Set Roles",
        "summary": "Staff roles can manage tickets. Viewer roles can see tickets without replying.",
        "usage": (
            ".typeset <panel> <type> staff_roles <role_ids>\n"
            ".typeset <panel> <type> viewer_roles <role_ids>"
        ),
        "example": (
            ".typeset main deals staff_roles 123456789012345678,234567890123456789\n"
            ".typeset main deals viewer_roles 345678901234567890"
        ),
        "testing": "Open a test ticket and check that staff can reply while viewer roles stay read-only."
    },
    {
        "key": "logs",
        "title": "FusionCollab Setup",
        "step": "Step 5/8 • Set Log Channels",
        "summary": "Log channels receive open, claim, close, delete, and transcript events for each ticket type.",
        "usage": (
            ".typeset <panel> <type> log_channel_id <channel_id>"
        ),
        "example": (
            ".typeset main deals log_channel_id 123456789012345678\n"
            ".typeset main complaint log_channel_id 234567890123456789\n"
            ".typeset main support log_channel_id 345678901234567890"
        ),
        "testing": "Open a ticket, claim it, then close it and confirm the full event flow appears in logs."
    },
    {
        "key": "messages",
        "title": "FusionCollab Setup",
        "step": "Step 6/8 • Customize Messages",
        "summary": "Each ticket type can have its own ticket title, message, prefix, and embed color.",
        "usage": (
            ".typeset <panel> <type> ticket_title <text>\n"
            ".typeset <panel> <type> ticket_message <text>\n"
            ".typeset <panel> <type> ticket_prefix <text>\n"
            ".typeset <panel> <type> embed_color <hex>"
        ),
        "example": (
            ".typeset main deals ticket_title Deals Room\n"
            ".typeset main deals ticket_message Welcome to your deal ticket.\\nExplain your request clearly.\n"
            ".typeset main deals ticket_prefix deal\n"
            ".typeset main deals embed_color #2B2D31"
        ),
        "testing": "Create a new ticket and verify the ticket name, embed title, embed text, and color."
    },
    {
        "key": "buttons",
        "title": "FusionCollab Setup",
        "step": "Step 7/8 • Customize Buttons",
        "summary": "Claim, Close, and Transcript buttons are fully editable per ticket type for a more professional look.",
        "usage": (
            ".typeset <panel> <type> claim_button_label <text>\n"
            ".typeset <panel> <type> claim_button_emoji <emoji>\n"
            ".typeset <panel> <type> claim_button_style <primary|secondary|success|danger>\n"
            ".typeset <panel> <type> close_button_label <text>\n"
            ".typeset <panel> <type> close_button_emoji <emoji>\n"
            ".typeset <panel> <type> close_button_style <primary|secondary|success|danger>\n"
            ".typeset <panel> <type> transcript_button_label <text>\n"
            ".typeset <panel> <type> transcript_button_emoji <emoji>\n"
            ".typeset <panel> <type> transcript_button_style <primary|secondary|success|danger>"
        ),
        "example": (
            ".typeset main deals claim_button_label Claim\n"
            ".typeset main deals claim_button_emoji <:crown:123456789012345678>\n"
            ".typeset main deals claim_button_style primary\n"
            ".typeset main deals close_button_style danger\n"
            ".typeset main deals transcript_button_style secondary"
        ),
        "testing": "Open a fresh ticket and verify the label, emoji, and style of all three action buttons."
    },
    {
        "key": "test",
        "title": "FusionCollab Setup",
        "step": "Step 8/8 • Send and Test",
        "summary": "Once config is ready, send the panel and test the complete ticket flow before treating setup as finished.",
        "usage": (
            ".panelsend <panel_key> <#channel>\n"
            ".new <panel> <type>\n"
            ".claim\n"
            ".transcript\n"
            ".close"
        ),
        "example": (
            ".panelsend main #tickets\n"
            ".new main deals"
        ),
        "testing": (
            "Checklist:\n"
            "• panel button opens the type selector\n"
            "• every type opens in the correct category\n"
            "• staff can claim tickets\n"
            "• transcript works correctly\n"
            "• close sends logs and transcript"
        )
    }
]


def setup_topic_alias(topic: str) -> str:
    topic = str(topic or "overview").lower().strip()
    alias_map = {
        "setup": "overview",
        "overview": "overview",
        "panel": "panel",
        "panels": "panel",
        "type": "type",
        "types": "type",
        "category": "category",
        "categories": "category",
        "role": "roles",
        "roles": "roles",
        "log": "logs",
        "logs": "logs",
        "message": "messages",
        "messages": "messages",
        "button": "buttons",
        "buttons": "buttons",
        "test": "test",
        "testing": "test",
        "send": "test",
    }
    return alias_map.get(topic, "overview")


def get_setup_page_index(topic: str) -> int:
    wanted = setup_topic_alias(topic)
    for i, page in enumerate(SETUP_GUIDE_PAGES):
        if page["key"] == wanted:
            return i
    return 0


def replace_prefix_lines(text: str, prefix: str) -> str:
    lines = text.splitlines()
    fixed = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("."):
            leading = line[:len(line) - len(stripped)]
            fixed.append(f"{leading}{prefix}{stripped[1:]}")
        else:
            fixed.append(line)
    return "\n".join(fixed)


def build_setup_embed(index: int, prefix: str) -> discord.Embed:
    index = max(0, min(index, len(SETUP_GUIDE_PAGES) - 1))
    page = SETUP_GUIDE_PAGES[index]

    embed = discord.Embed(
        title=page["title"],
        description=f"**{page['step']}**\n{page['summary']}",
        color=HELP_COLOR,
        timestamp=now_utc()
    )

    embed.add_field(
        name="Usage",
        value=make_code_block(replace_prefix_lines(page["usage"], prefix)),
        inline=False
    )
    embed.add_field(
        name="Example",
        value=make_code_block(replace_prefix_lines(page["example"], prefix)),
        inline=False
    )
    embed.add_field(
        name="Test This",
        value=page["testing"],
        inline=False
    )

    if HELP_THUMBNAIL:
        embed.set_thumbnail(url=HELP_THUMBNAIL)

    embed.set_author(name="FusionCollab Admin Guide")
    embed.set_footer(text=f"Page {index + 1}/{len(SETUP_GUIDE_PAGES)} • Guided Setup")
    return embed


class HelpView(discord.ui.View):
    def __init__(self, author_id: int, prefix: str):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.prefix = prefix

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help panel is not for you.", ephemeral=True)
            return False
        return True

    async def update_page(self, interaction: discord.Interaction, category: str):
        await interaction.response.edit_message(embed=build_help_embed(category, self.prefix), view=self)

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, "home")

    @discord.ui.button(label="📌 General", style=discord.ButtonStyle.secondary, row=0)
    async def general_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, "general")

    @discord.ui.button(label="🎟️ Tickets", style=discord.ButtonStyle.secondary, row=1)
    async def tickets_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, "tickets")

    @discord.ui.button(label="🛡️ Staff", style=discord.ButtonStyle.secondary, row=1)
    async def staff_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, "staff")

    @discord.ui.button(label="⚙️ Admin", style=discord.ButtonStyle.secondary, row=2)
    async def admin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, "admin")

    @discord.ui.button(label="🧩 Panels", style=discord.ButtonStyle.secondary, row=2)
    async def panels_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, "panels")

    @discord.ui.button(label="🧠 Config", style=discord.ButtonStyle.secondary, row=3)
    async def config_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_page(interaction, "config")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class SetupGuideView(discord.ui.View):
    def __init__(self, author_id: int, prefix: str, start_index: int = 0):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.prefix = prefix
        self.index = max(0, min(start_index, len(SETUP_GUIDE_PAGES) - 1))
        self.sync_buttons()

    def sync_buttons(self):
        self.back_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(SETUP_GUIDE_PAGES) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This setup guide is not for you.", ephemeral=True)
            return False
        return True

    async def redraw(self, interaction: discord.Interaction):
        self.sync_buttons()
        await interaction.response.edit_message(
            embed=build_setup_embed(self.index, self.prefix),
            view=self
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        await self.redraw(interaction)

    @discord.ui.button(label="⌂ Home", style=discord.ButtonStyle.secondary, row=0)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = 0
        await self.redraw(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(SETUP_GUIDE_PAGES) - 1, self.index + 1)
        await self.redraw(interaction)

    @discord.ui.button(label="✕", style=discord.ButtonStyle.danger, row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.hybrid_command(name="help", description="Show help categories or setup guides.")
async def help_cmd(ctx: commands.Context, *, topic: Optional[str] = None):
    prefix = data.get("prefix", ".")
    topic = (topic or "home").lower().strip()

    setup_topics = {
        "setup",
        "overview",
        "panel",
        "panels",
        "type",
        "types",
        "category",
        "categories",
        "role",
        "roles",
        "log",
        "logs",
        "message",
        "messages",
        "button",
        "buttons",
        "test",
        "testing",
        "send",
    }

    if topic in setup_topics:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title="FusionCollab Help",
                description="You need administrator permission to use the setup guide.",
                color=HELP_COLOR,
                timestamp=now_utc()
            )
            embed.set_footer(text="FusionCollab")
            await ctx.send(embed=embed)
            return

        start_index = get_setup_page_index(topic)
        view = SetupGuideView(ctx.author.id, prefix, start_index=start_index)
        await ctx.send(embed=build_setup_embed(start_index, prefix), view=view)
        return

    embed = build_help_embed("home" if topic == "home" else topic, prefix)
    view = HelpView(ctx.author.id, prefix)
    await ctx.send(embed=embed, view=view)



# =========================================================
# PANEL UI
# =========================================================

class TicketTypeSelect(discord.ui.Select):
    def __init__(self, panel_key: str, panel: dict):
        self.panel_key = panel_key
        panel = panel_with_defaults(panel)

        options = []
        for type_key, type_data in panel.get("types", {}).items():
            type_data = ticket_type_with_defaults(type_data)
            options.append(
                discord.SelectOption(
                    label=str(type_data.get("label", type_key))[:100],
                    value=type_key.lower(),
                    emoji=parse_button_emoji(type_data.get("emoji")),
                    description=str(type_data.get("description", "Open this ticket type"))[:100]
                )
            )

        if not options:
            options = [discord.SelectOption(label="No Types Configured", value="none")]

        super().__init__(
            placeholder="Choose a ticket type...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("No ticket types are configured for this panel.", ephemeral=True)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        channel, error = await open_ticket_for_member(interaction.guild, interaction.user, self.panel_key, self.values[0])
        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(f"Created {channel.mention}", ephemeral=True)


class TicketTypeSelectView(discord.ui.View):
    def __init__(self, panel_key: str, panel: dict):
        super().__init__(timeout=120)
        self.add_item(TicketTypeSelect(panel_key, panel))


class PanelOpenView(discord.ui.View):
    def __init__(self, panel_key: str, panel: dict):
        super().__init__(timeout=None)
        panel = panel_with_defaults(panel)

        button = discord.ui.Button(
            label=panel.get("button_label", "Create Ticket"),
            emoji=parse_button_emoji(panel.get("button_emoji")),
            style=style_from_name(panel.get("button_style", "secondary")),
            custom_id=f"fusioncollab_panel_open:{panel_key.lower()}"
        )
        button.callback = self.make_callback(panel_key.lower())
        self.add_item(button)

    def make_callback(self, panel_key: str):
        async def callback(interaction: discord.Interaction):
            panel = get_panel(panel_key)
            if not panel:
                return await interaction.response.send_message("Panel not found.", ephemeral=True)

            panel = panel_with_defaults(panel)
            if not panel.get("types"):
                return await interaction.response.send_message("This panel has no ticket types yet.", ephemeral=True)

            embed = discord.Embed(
                title=panel.get("title", "FusionCollab"),
                description="Choose a ticket type below.",
                color=panel.get("embed_color", DEFAULT_EMBED_COLOR),
                timestamp=now_utc()
            )
            embed.set_footer(text=panel.get("footer", "FusionCollab"))
            if panel.get("thumbnail"):
                embed.set_thumbnail(url=panel["thumbnail"])

            await interaction.response.send_message(
                embed=embed,
                view=TicketTypeSelectView(panel_key, panel),
                ephemeral=True
            )
        return callback


class TicketControlsView(discord.ui.View):
    def __init__(self, panel_key: Optional[str] = None, type_key: Optional[str] = None):
        super().__init__(timeout=None)

        ticket_type = deep_copy(DEFAULT_TYPE)
        if panel_key and type_key:
            panel = get_panel(panel_key)
            if panel:
                panel = panel_with_defaults(panel)
                configured_type = panel.get("types", {}).get(type_key.lower())
                if configured_type:
                    ticket_type = ticket_type_with_defaults(configured_type)

        claim_button = discord.ui.Button(
            label=ticket_type.get("claim_button_label", "Claim"),
            emoji=parse_button_emoji(ticket_type.get("claim_button_emoji")),
            style=style_from_name(ticket_type.get("claim_button_style", "primary")),
            custom_id="fusioncollab_ticket_claim"
        )
        claim_button.callback = self.claim_button_callback
        self.add_item(claim_button)

        close_button = discord.ui.Button(
            label=ticket_type.get("close_button_label", "Close"),
            emoji=parse_button_emoji(ticket_type.get("close_button_emoji")),
            style=style_from_name(ticket_type.get("close_button_style", "danger")),
            custom_id="fusioncollab_ticket_close"
        )
        close_button.callback = self.close_button_callback
        self.add_item(close_button)

        transcript_button = discord.ui.Button(
            label=ticket_type.get("transcript_button_label", "Transcript"),
            emoji=parse_button_emoji(ticket_type.get("transcript_button_emoji")),
            style=style_from_name(ticket_type.get("transcript_button_style", "secondary")),
            custom_id="fusioncollab_ticket_transcript"
        )
        transcript_button.callback = self.transcript_button_callback
        self.add_item(transcript_button)

    async def claim_button_callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        if not is_ticket_channel(interaction.channel):
            return await interaction.response.send_message("This is not a managed ticket.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)

        meta = get_ticket_meta(interaction.channel.id)
        if not meta:
            return await interaction.response.send_message("Ticket data not found.", ephemeral=True)

        panel_key = meta["panel_key"]
        type_key = meta["type_key"]

        if not member_has_staff_access(interaction.user, panel_key, type_key):
            return await interaction.response.send_message("You do not have staff access here.", ephemeral=True)

        current = get_claim(interaction.channel.id)
        if current == interaction.user.id:
            return await interaction.response.send_message("You already claimed this ticket.", ephemeral=True)

        if current is not None:
            claimed_by = interaction.guild.get_member(current)
            if claimed_by:
                return await interaction.response.send_message(f"This ticket is already claimed by {claimed_by.mention}.", ephemeral=True)
            return await interaction.response.send_message("This ticket is already claimed.", ephemeral=True)

        set_claim(interaction.channel.id, interaction.user.id)

        await interaction.response.send_message(f"{interaction.user.mention} claimed this ticket.")
        await send_type_log(
            interaction.guild,
            panel_key,
            type_key,
            f"👑 Claimed: #{interaction.channel.name} | By: {interaction.user.mention}"
        )

    async def close_button_callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        if not is_ticket_channel(interaction.channel):
            return await interaction.response.send_message("This is not a managed ticket.", ephemeral=True)

        meta = get_ticket_meta(interaction.channel.id)
        if not meta:
            return await interaction.response.send_message("Ticket data not found.", ephemeral=True)

        owner_id = int(meta["owner_id"])
        panel_key = meta["panel_key"]
        type_key = meta["type_key"]

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)

        if interaction.user.id != owner_id and not member_has_staff_access(interaction.user, panel_key, type_key):
            return await interaction.response.send_message("You cannot close this ticket.", ephemeral=True)

        confirm_embed = themed_embed(
            "Confirm Close",
            "Are you sure you want to close this ticket?\n\nIf confirmed, the ticket will close after the configured delay."
        )

        await interaction.response.send_message(
            embed=confirm_embed,
            view=ConfirmCloseView(interaction.user.id, panel_key, type_key),
            ephemeral=True
        )

    async def transcript_button_callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        if not is_ticket_channel(interaction.channel):
            return await interaction.response.send_message("This is not a managed ticket.", ephemeral=True)

        meta = get_ticket_meta(interaction.channel.id)
        if not meta:
            return await interaction.response.send_message("Ticket data not found.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)

        if not member_has_staff_access(interaction.user, meta["panel_key"], meta["type_key"]):
            return await interaction.response.send_message("You do not have staff access here.", ephemeral=True)

        file = await create_transcript_file(interaction.channel)
        await interaction.response.send_message(file=file, ephemeral=True)

def themed_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=HELP_COLOR,
        timestamp=now_utc()
    )
    embed.set_footer(text="FusionCollab")
    return embed


async def close_ticket_channel(channel: discord.TextChannel, actor: discord.Member):
    meta = get_ticket_meta(channel.id)
    if not meta or not channel.guild:
        return

    panel_key = meta["panel_key"]
    type_key = meta["type_key"]

    transcript = await create_transcript_file(channel)
    await send_type_log(
        channel.guild,
        panel_key,
        type_key,
        f"📁 Closed: #{channel.name} | By: {actor.mention}",
        file=transcript
    )

    delete_ticket_meta(channel.id)
    await channel.delete(reason=f"Closed by {actor}")


class ConfirmCloseView(discord.ui.View):
    def __init__(self, requester_id: int, panel_key: Optional[str] = None, type_key: Optional[str] = None):
        super().__init__(timeout=120)
        self.requester_id = requester_id

        ticket_type = deep_copy(DEFAULT_TYPE)
        if panel_key and type_key:
            panel = get_panel(panel_key)
            if panel:
                panel = panel_with_defaults(panel)
                configured_type = panel.get("types", {}).get(type_key.lower())
                if configured_type:
                    ticket_type = ticket_type_with_defaults(configured_type)

        self.confirm_close_button.emoji = parse_button_emoji(ticket_type.get("confirm_close_button_emoji"))
        self.cancel_button.emoji = parse_button_emoji(ticket_type.get("cancel_button_emoji"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This close confirmation is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Close", emoji="🔒", style=discord.ButtonStyle.danger, row=0)
    async def confirm_close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        if not is_ticket_channel(interaction.channel):
            return await interaction.response.send_message("This is not a managed ticket.", ephemeral=True)

        meta = get_ticket_meta(interaction.channel.id)
        if not meta:
            return await interaction.response.send_message("Ticket data not found.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)

        owner_id = int(meta["owner_id"])
        panel_key = meta["panel_key"]
        type_key = meta["type_key"]

        if interaction.user.id != owner_id and not member_has_staff_access(interaction.user, panel_key, type_key):
            return await interaction.response.send_message("You cannot close this ticket.", ephemeral=True)

        panel = get_panel(panel_key)
        ticket_type = ticket_type_with_defaults((panel or {}).get("types", {}).get(type_key, {}))
        delay = int(ticket_type.get("close_delay", 3))

        close_embed = themed_embed(
            "Ticket Closing",
            f"This ticket will close in **{delay} seconds**.\nA transcript will be sent to the configured log channel if one is set."
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=close_embed, view=self)
        owner = interaction.guild.get_member(owner_id)
        if owner is not None:
            await interaction.channel.set_permissions(
                owner,
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                attach_files=False,
                embed_links=False
            )

        closed_embed = themed_embed(
            "Ticket Closed",
            f"This ticket was closed by {interaction.user.mention}.\n\nStaff can reopen or delete this ticket using the buttons below."
        )

        await asyncio.sleep(delay)
        await interaction.channel.send(embed=closed_embed, view=ClosedTicketView(panel_key, type_key))

        await send_type_log(
            interaction.guild,
            panel_key,
            type_key,
            f"🔒 Closed: #{interaction.channel.name} | By: {interaction.user.mention}"
        )

    @discord.ui.button(label="Cancel", emoji="↩️", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cancel_embed = themed_embed(
            "Close Cancelled",
            "This ticket will remain open."
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=cancel_embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ClosedTicketView(discord.ui.View):
    def __init__(self, panel_key: Optional[str] = None, type_key: Optional[str] = None):
        super().__init__(timeout=None)

        ticket_type = deep_copy(DEFAULT_TYPE)
        if panel_key and type_key:
            panel = get_panel(panel_key)
            if panel:
                panel = panel_with_defaults(panel)
                configured_type = panel.get("types", {}).get(type_key.lower())
                if configured_type:
                    ticket_type = ticket_type_with_defaults(configured_type)

        self.reopen_button.emoji = parse_button_emoji(ticket_type.get("reopen_button_emoji"))
        self.delete_button.emoji = parse_button_emoji(ticket_type.get("delete_button_emoji"))

    @discord.ui.button(label="Reopen", emoji=None, style=discord.ButtonStyle.success, custom_id="fusioncollab_ticket_reopen", row=0)
    async def reopen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        if not is_ticket_channel(interaction.channel):
            return await interaction.response.send_message("This is not a managed ticket.", ephemeral=True)

        meta = get_ticket_meta(interaction.channel.id)
        if not meta:
            return await interaction.response.send_message("Ticket data not found.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)

        if not member_has_staff_access(interaction.user, meta["panel_key"], meta["type_key"]):
            return await interaction.response.send_message("Only staff can reopen this ticket.", ephemeral=True)

        owner_id = int(meta["owner_id"])
        owner = interaction.guild.get_member(owner_id)
        if owner is not None:
            await interaction.channel.set_permissions(
                owner,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

        reopened_embed = themed_embed(
            "Ticket Reopened",
            f"This ticket was reopened by {interaction.user.mention}."
        )

        await interaction.response.send_message(embed=reopened_embed)
        await send_type_log(
            interaction.guild,
            meta["panel_key"],
            meta["type_key"],
            f"🔓 Reopened: #{interaction.channel.name} | By: {interaction.user.mention}"
        )
        await send_type_log(
            interaction.guild,
            meta["panel_key"],
            meta["type_key"],
            f"🔓 Reopened: #{interaction.channel.name} | By: {interaction.user.mention}"
        )

    @discord.ui.button(label="Delete", emoji=None, style=discord.ButtonStyle.danger, custom_id="fusioncollab_ticket_delete_closed", row=0)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This only works in a server.", ephemeral=True)

        if not is_ticket_channel(interaction.channel):
            return await interaction.response.send_message("This is not a managed ticket.", ephemeral=True)

        meta = get_ticket_meta(interaction.channel.id)
        if not meta:
            return await interaction.response.send_message("Ticket data not found.", ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)

        if not member_has_staff_access(interaction.user, meta["panel_key"], meta["type_key"]):
            return await interaction.response.send_message("Only staff can delete this ticket.", ephemeral=True)

        delete_embed = themed_embed(
            "Ticket Deleting",
            f"This ticket will now be permanently deleted by {interaction.user.mention}."
        )

        await interaction.response.send_message(embed=delete_embed)

        transcript_file = await create_transcript_file(interaction.channel)
        await send_type_log(
            interaction.guild,
            meta["panel_key"],
            meta["type_key"],
            f"🗑️ Deleted: #{interaction.channel.name} | By: {interaction.user.mention}",
            file=transcript_file
        )

        delete_ticket_meta(interaction.channel.id)
        await asyncio.sleep(2)
        await interaction.channel.delete(reason=f"Deleted by {interaction.user}")



# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.competing,
            name="fusioncollab.in"
        ),
        status=discord.Status.online
    )


    bot.add_view(TicketControlsView())
    bot.add_view(ClosedTicketView(None, None))

    for panel_key, panel in data["panels"].items():
        try:
            bot.add_view(PanelOpenView(panel_key, panel))
        except Exception as e:
            print(f"Failed to register panel view for {panel_key}: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} global app commands.")
    except Exception as e:
        print(f"Global sync failed: {e}")


# =========================================================
# CHECKS
# =========================================================

def admin_only():
    async def predicate(ctx: commands.Context):
        if not isinstance(ctx.author, discord.Member):
            raise commands.CheckFailure("Server only.")
        if not ctx.author.guild_permissions.administrator:
            raise commands.CheckFailure("Administrator permission required.")
        return True
    return commands.check(predicate)


def staff_ticket_check():
    async def predicate(ctx: commands.Context):
        if not isinstance(ctx.channel, discord.TextChannel) or not is_ticket_channel(ctx.channel):
            raise commands.CheckFailure("This is not a managed ticket.")
        meta = get_ticket_meta(ctx.channel.id)
        if not meta:
            raise commands.CheckFailure("Ticket data not found.")
        if not isinstance(ctx.author, discord.Member):
            raise commands.CheckFailure("Server only.")
        if not member_has_staff_access(ctx.author, meta["panel_key"], meta["type_key"]):
            raise commands.CheckFailure("You do not have staff access here.")
        return True
    return commands.check(predicate)


# =========================================================
# HELP / GENERAL
# =========================================================


@bot.hybrid_command(name="ping", description="Check bot latency.")
async def ping(ctx: commands.Context):
    await ctx.send(f"Pong: `{round(bot.latency * 1000)}ms`")


@bot.hybrid_command(name="setprefix", description="Change the bot prefix.")
@admin_only()
async def setprefix(ctx: commands.Context, prefix: str):
    if len(prefix) > 10:
        return await ctx.send("Prefix is too long.")
    data["prefix"] = prefix
    save_data()
    await ctx.send(f"Prefix updated to `{prefix}`")


# =========================================================
# PANEL COMMANDS
# =========================================================

@bot.hybrid_command(name="panelcreate", description="Create a new main panel.")
@admin_only()
async def panelcreate(ctx: commands.Context, key: str):
    key = key.lower()
    if get_panel(key):
        return await ctx.send("That panel already exists.")

    panel = deep_copy(DEFAULT_PANEL)
    panel["types"] = {}
    set_panel(key, panel)

    bot.add_view(PanelOpenView(key, panel))
    await ctx.send(f"Panel `{key}` created.")


@bot.hybrid_command(name="paneldelete", description="Delete a main panel.")
@admin_only()
async def paneldelete(ctx: commands.Context, key: str):
    key = key.lower()
    if not get_panel(key):
        return await ctx.send("Panel not found.")

    delete_panel(key)
    await ctx.send(f"Deleted panel `{key}`.")


@bot.hybrid_command(name="panelsend", description="Send a panel into a channel.")
@admin_only()
async def panelsend(ctx: commands.Context, key: str, channel: discord.TextChannel):
    key = key.lower()
    panel = get_panel(key)
    if not panel:
        return await ctx.send("Panel not found.")

    view = PanelOpenView(key, panel)
    await channel.send(embed=panel_embed(panel), view=view)
    await ctx.send(f"Sent panel `{key}` in {channel.mention}")


@bot.hybrid_command(name="panelset", description="Edit a panel field.")
@admin_only()
async def panelset(ctx: commands.Context, key: str, field: str, *, value: str):
    key = key.lower()
    field = field.lower()

    panel = get_panel(key)
    if not panel:
        return await ctx.send("Panel not found.")

    panel = panel_with_defaults(panel)
    value = value.strip()

    try:
        if field == "embed_color":
            panel[field] = parse_hex_color(value)
        elif field == "button_emoji":
            panel[field] = None if value.lower() == "none" else value
        elif field == "thumbnail":
            panel[field] = None if value.lower() == "none" else value
        elif field == "button_style":
            if value.lower() not in ("primary", "secondary", "success", "danger"):
                return await ctx.send("button_style must be primary, secondary, success, or danger.")
            panel[field] = value.lower()
        elif field in ("title", "description", "button_label", "footer"):
            panel[field] = normalize_newlines(value)
        else:
            return await ctx.send("Unknown panel field.")
    except ValueError:
        return await ctx.send("Invalid value for that field.")

    set_panel(key, panel)
    bot.add_view(PanelOpenView(key, panel))
    await ctx.send(f"Updated panel `{key}` field `{field}`.")


# =========================================================
# TYPE COMMANDS
# =========================================================

@bot.hybrid_command(name="typeadd", description="Add a ticket type to a panel.")
@admin_only()
async def typeadd(ctx: commands.Context, panel_key: str, type_key: str):
    panel_key = panel_key.lower()
    type_key = type_key.lower()

    panel = get_panel(panel_key)
    if not panel:
        return await ctx.send("Panel not found.")

    panel = panel_with_defaults(panel)
    if type_key in panel["types"]:
        return await ctx.send("That ticket type already exists.")

    new_type = deep_copy(DEFAULT_TYPE)
    new_type["label"] = type_key.title()
    panel["types"][type_key] = new_type

    set_panel(panel_key, panel)
    bot.add_view(PanelOpenView(panel_key, panel))
    await ctx.send(f"Added ticket type `{type_key}` to panel `{panel_key}`.")


@bot.hybrid_command(name="typedelete", description="Delete a ticket type from a panel.")
@admin_only()
async def typedelete(ctx: commands.Context, panel_key: str, type_key: str):
    panel_key = panel_key.lower()
    type_key = type_key.lower()

    panel = get_panel(panel_key)
    if not panel:
        return await ctx.send("Panel not found.")

    panel = panel_with_defaults(panel)
    if type_key not in panel["types"]:
        return await ctx.send("Ticket type not found.")

    del panel["types"][type_key]
    set_panel(panel_key, panel)
    bot.add_view(PanelOpenView(panel_key, panel))
    await ctx.send(f"Deleted ticket type `{type_key}` from panel `{panel_key}`.")


@bot.hybrid_command(name="typeset", description="Edit a ticket type field.")
@admin_only()
async def typeset(ctx: commands.Context, panel_key: str, type_key: str, field: str, *, value: str):
    panel_key = panel_key.lower()
    type_key = type_key.lower()
    field = field.lower()

    panel = get_panel(panel_key)
    if not panel:
        return await ctx.send("Panel not found.")

    panel = panel_with_defaults(panel)
    ticket_type = panel["types"].get(type_key)
    if not ticket_type:
        return await ctx.send("Ticket type not found.")

    ticket_type = ticket_type_with_defaults(ticket_type)
    value = value.strip()

    button_style_fields = {
        "claim_button_style",
        "close_button_style",
        "transcript_button_style",
    }

    button_emoji_fields = {
        "claim_button_emoji",
        "close_button_emoji",
        "transcript_button_emoji",
        "reopen_button_emoji",
        "delete_button_emoji",
        "confirm_close_button_emoji",
        "cancel_button_emoji",
    }

    button_label_fields = {
        "claim_button_label",
        "close_button_label",
        "transcript_button_label",
    }

    try:
        if field == "embed_color":
            ticket_type[field] = parse_hex_color(value)
        elif field in ("category_id", "log_channel_id"):
            found = extract_id(value)
            if not found:
                return await ctx.send(f"`{field}` must be an ID or mention.")
            ticket_type[field] = found
        elif field in ("max_open_per_user", "close_delay"):
            ticket_type[field] = int(value)
        elif field in ("staff_roles", "viewer_roles"):
            ticket_type[field] = extract_many_ids(value)
        elif field == "emoji":
            ticket_type[field] = None if value.lower() == "none" else value
        elif field in button_emoji_fields:
            ticket_type[field] = None if value.lower() == "none" else value
        elif field in button_style_fields:
            if value.lower() not in ("primary", "secondary", "success", "danger"):
                return await ctx.send(f"`{field}` must be primary, secondary, success, or danger.")
            ticket_type[field] = value.lower()
        elif field in button_label_fields:
            ticket_type[field] = normalize_newlines(value)
        elif field in ("label", "description", "ticket_prefix", "ticket_title", "ticket_message"):
            ticket_type[field] = normalize_newlines(value)
        else:
            return await ctx.send("Unknown ticket type field.")
    except ValueError:
        return await ctx.send("Invalid value for that field.")

    panel["types"][type_key] = ticket_type
    set_panel(panel_key, panel)
    bot.add_view(PanelOpenView(panel_key, panel))
    await ctx.send(f"Updated type `{type_key}` field `{field}` in panel `{panel_key}`.")


@bot.hybrid_command(name="typelist", description="List ticket types in a panel.")
@admin_only()
async def typelist(ctx: commands.Context, panel_key: str):
    panel_key = panel_key.lower()
    panel = get_panel(panel_key)
    if not panel:
        return await ctx.send("Panel not found.")

    panel = panel_with_defaults(panel)
    if not panel["types"]:
        return await ctx.send("This panel has no ticket types.")

    lines = []
    for type_key, type_data in panel["types"].items():
        type_data = ticket_type_with_defaults(type_data)
        lines.append(f"• `{type_key}` → {type_data.get('label', type_key)}")

    embed = discord.Embed(
        title=f"Ticket Types • {panel_key}",
        description="\n".join(lines),
        color=HELP_COLOR,
        timestamp=now_utc()
    )
    embed.set_footer(text="FusionCollab")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="setupcheck", description="Audit a panel or ticket type setup.")
@admin_only()
async def setupcheck(ctx: commands.Context, panel_key: str, type_key: Optional[str] = None):
    panel_key = panel_key.lower()
    panel = get_panel(panel_key)

    if not panel:
        embed = discord.Embed(
            title="FusionCollab Setup Check",
            description=f"Panel `{panel_key}` was not found.",
            color=HELP_COLOR,
            timestamp=now_utc()
        )
        embed.set_author(name="FusionCollab Admin Guide")
        embed.set_footer(text="Setup Audit")
        return await ctx.send(embed=embed)

    if not ctx.guild:
        embed = discord.Embed(
            title="FusionCollab Setup Check",
            description="This command only works in a server.",
            color=HELP_COLOR,
            timestamp=now_utc()
        )
        embed.set_author(name="FusionCollab Admin Guide")
        embed.set_footer(text="Setup Audit")
        return await ctx.send(embed=embed)

    panel = panel_with_defaults(panel)

    if type_key is None:
        pages = build_setupcheck_panel_pages(ctx.guild, panel_key, panel)
        view = SetupCheckView(ctx.author.id, pages)
        return await ctx.send(embed=pages[0], view=view)

    type_key = type_key.lower()
    ticket_type = panel.get("types", {}).get(type_key)
    if not ticket_type:
        embed = discord.Embed(
            title="FusionCollab Setup Check",
            description=f"Ticket type `{type_key}` was not found in panel `{panel_key}`.",
            color=HELP_COLOR,
            timestamp=now_utc()
        )
        embed.set_author(name="FusionCollab Admin Guide")
        embed.set_footer(text="Setup Audit")
        return await ctx.send(embed=embed)

    pages = build_setupcheck_type_pages(ctx.guild, panel_key, type_key, panel, ticket_type)
    view = SetupCheckView(ctx.author.id, pages)
    await ctx.send(embed=pages[0], view=view)

@bot.hybrid_command(name="ticketstats", description="View open ticket statistics.")
@admin_only()
async def ticketstats(ctx: commands.Context):
    if not ctx.guild:
        embed = themed_embed("FusionCollab", "This command only works in a server.")
        return await ctx.send(embed=embed)

    pages = build_ticketstats_pages(ctx.guild)
    view = TicketStatsView(ctx.author.id, pages)
    await ctx.send(embed=pages[0], view=view)



# =========================================================
# USER TICKET COMMANDS
# =========================================================

@bot.hybrid_command(name="new", description="Open a ticket directly.")
async def new(ctx: commands.Context, panel_key: str, type_key: str):
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.send("This only works in a server.")

    channel, error = await open_ticket_for_member(ctx.guild, ctx.author, panel_key.lower(), type_key.lower())
    if error:
        return await ctx.send(error)

    await ctx.send(f"Created {channel.mention}")


@bot.hybrid_command(name="close", description="Close the current ticket.")
async def close(ctx: commands.Context):
    if not isinstance(ctx.channel, discord.TextChannel) or not is_ticket_channel(ctx.channel):
        embed = themed_embed("FusionCollab", "This is not a managed ticket.")
        return await ctx.send(embed=embed)

    meta = get_ticket_meta(ctx.channel.id)
    if not meta:
        embed = themed_embed("FusionCollab", "Ticket data not found.")
        return await ctx.send(embed=embed)

    if not isinstance(ctx.author, discord.Member):
        embed = themed_embed("FusionCollab", "Server only.")
        return await ctx.send(embed=embed)

    owner_id = int(meta["owner_id"])
    panel_key = meta["panel_key"]
    type_key = meta["type_key"]

    if ctx.author.id != owner_id and not member_has_staff_access(ctx.author, panel_key, type_key):
        embed = themed_embed("FusionCollab", "You cannot close this ticket.")
        return await ctx.send(embed=embed)

    confirm_embed = themed_embed(
        "Confirm Close",
        "Use the ticket close button for the confirmation flow.\n\nIf you do not see it, scroll to the main ticket message."
    )
    await ctx.send(embed=confirm_embed)



# =========================================================
# STAFF COMMANDS
# =========================================================

@bot.hybrid_command(name="add", description="Add a member to this ticket.")
@staff_ticket_check()
async def add(ctx: commands.Context, member: discord.Member):
    await ctx.channel.set_permissions(
        member,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        embed_links=True
    )
    await ctx.send(f"Added {member.mention}")


@bot.hybrid_command(name="remove", description="Remove a member from this ticket.")
@staff_ticket_check()
async def remove(ctx: commands.Context, member: discord.Member):
    owner_id = ticket_owner_id(ctx.channel.id)
    if owner_id == member.id:
        return await ctx.send("You cannot remove the ticket owner.")

    await ctx.channel.set_permissions(member, overwrite=None)
    await ctx.send(f"Removed {member.mention}")


@bot.hybrid_command(name="rename", description="Rename this ticket.")
@staff_ticket_check()
async def rename(ctx: commands.Context, *, new_name: str):
    cleaned = sanitize_channel_name(new_name)
    await ctx.channel.edit(name=cleaned)
    await ctx.send(f"Renamed to `{cleaned}`")


@bot.hybrid_command(name="claim", description="Claim this ticket.")
@staff_ticket_check()
async def claim(ctx: commands.Context):
    current = get_claim(ctx.channel.id)
    if current == ctx.author.id:
        return await ctx.send("You already claimed this ticket.")
    if current is not None:
        member = ctx.guild.get_member(current)
        if member:
            return await ctx.send(f"This ticket is already claimed by {member.mention}.")
        return await ctx.send("This ticket is already claimed.")

    set_claim(ctx.channel.id, ctx.author.id)
    await ctx.send(f"{ctx.author.mention} claimed this ticket.")


@bot.hybrid_command(name="unclaim", description="Unclaim this ticket.")
@staff_ticket_check()
async def unclaim(ctx: commands.Context):
    current = get_claim(ctx.channel.id)
    if current is None:
        return await ctx.send("This ticket is not claimed.")

    set_claim(ctx.channel.id, None)
    await ctx.send("Ticket unclaimed.")


@bot.hybrid_command(name="lock", description="Lock this ticket for the owner.")
@staff_ticket_check()
async def lock(ctx: commands.Context):
    owner_id = ticket_owner_id(ctx.channel.id)
    if owner_id is None:
        return await ctx.send("Owner not found.")

    owner = ctx.guild.get_member(owner_id)
    if owner is None:
        return await ctx.send("Owner not found in server.")

    await ctx.channel.set_permissions(
        owner,
        view_channel=True,
        send_messages=False,
        read_message_history=True
    )
    await ctx.send("Ticket locked.")


@bot.hybrid_command(name="unlock", description="Unlock this ticket for the owner.")
@staff_ticket_check()
async def unlock(ctx: commands.Context):
    owner_id = ticket_owner_id(ctx.channel.id)
    if owner_id is None:
        return await ctx.send("Owner not found.")

    owner = ctx.guild.get_member(owner_id)
    if owner is None:
        return await ctx.send("Owner not found in server.")

    await ctx.channel.set_permissions(
        owner,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        embed_links=True
    )
    await ctx.send("Ticket unlocked.")


@bot.hybrid_command(name="transcript", description="Export a transcript of this ticket.")
@staff_ticket_check()
async def transcript(ctx: commands.Context):
    file = await create_transcript_file(ctx.channel)
    await ctx.send(file=file)


@bot.hybrid_command(name="delete", description="Delete this ticket immediately.")
@staff_ticket_check()
async def delete(ctx: commands.Context):
    meta = get_ticket_meta(ctx.channel.id)
    if not meta:
        return await ctx.send("Ticket data not found.")

    panel_key = meta["panel_key"]
    type_key = meta["type_key"]
    transcript_file = await create_transcript_file(ctx.channel)

    await send_type_log(
        ctx.guild,
        panel_key,
        type_key,
        f"🗑️ Deleted: #{ctx.channel.name} | By: {ctx.author.mention}",
        file=transcript_file
    )

    delete_ticket_meta(ctx.channel.id)
    await ctx.send("Deleting...")
    await asyncio.sleep(2)
    await ctx.channel.delete(reason=f"Deleted by {ctx.author}")

MENTION_HELP_COLOR = 0xF2F3F5


def build_mention_prefix_embed(member: discord.Member, prefix: str) -> discord.Embed:
    embed = discord.Embed(
        description=(
            f"<:WHITETICK:1495855082426728488> {member.mention}: **FusionCollab's prefix** for this server is `{prefix}`\n"
            f"<:WHITESPARKLE:1495855063623536681> Use `{prefix}help` to view commands"
        ),
        color=MENTION_HELP_COLOR,
        timestamp=now_utc()
    )
    embed.set_footer(text="FusionCollab")
    return embed

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if bot.user and message.guild:
        content = (message.content or "").strip()
        if content in {bot.user.mention, f"<@!{bot.user.id}>"}:
            prefix = data.get("prefix", ".")
            if isinstance(message.author, discord.Member):
                embed = build_mention_prefix_embed(message.author, prefix)
                await message.channel.send(embed=embed)
                return

    await bot.process_commands(message)




# =========================================================
# ERRORS
# =========================================================

def is_admin_member(member) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def get_help_suggestion_for_message(content: str, prefix: str) -> Optional[str]:
    lowered = str(content or "").lower().strip()

    hints = {
        f"{prefix}panel": f"Use `{prefix}help panel` for the panel guide, or `{prefix}help setup` for the full admin walkthrough.",
        f"{prefix}panelset": f"Use `{prefix}help panel` to see panel creation and panel customization.",
        f"{prefix}panelsend": f"Use `{prefix}help test` to see panel sending and testing steps.",
        f"{prefix}type": f"Use `{prefix}help type` for the ticket type guide.",
        f"{prefix}typeadd": f"Use `{prefix}help type` to learn how to add and structure ticket types.",
        f"{prefix}typedelete": f"Use `{prefix}help type` to manage ticket types cleanly.",
        f"{prefix}typeset": f"Use `{prefix}help buttons`, `{prefix}help messages`, `{prefix}help roles`, or `{prefix}help setup` to configure ticket types properly.",
    }

    for trigger, response in hints.items():
        if lowered == trigger or lowered.startswith(trigger + " "):
            return response

    return None

@bot.event
async def on_command_error(ctx: commands.Context, error):
    prefix = data.get("prefix", ".")

    if isinstance(error, commands.CommandNotFound):
        if is_admin_member(ctx.author):
            suggestion = get_help_suggestion_for_message(ctx.message.content, prefix)
            if suggestion:
                embed = discord.Embed(
                    title="FusionCollab Guide",
                    description=suggestion,
                    color=HELP_COLOR,
                    timestamp=now_utc()
                )
                if HELP_THUMBNAIL:
                    embed.set_thumbnail(url=HELP_THUMBNAIL)
                embed.set_footer(text="FusionCollab • Admin Guidance")
                return await ctx.send(embed=embed)
        return

    if isinstance(error, commands.CheckFailure):
        return await ctx.send(str(error))

    if isinstance(error, commands.MissingRequiredArgument):
        if is_admin_member(ctx.author):
            first_part = ctx.message.content.split(" ")[0]
            suggestion = get_help_suggestion_for_message(first_part, prefix)
            if suggestion:
                embed = discord.Embed(
                    title="FusionCollab Guide",
                    description=suggestion,
                    color=HELP_COLOR,
                    timestamp=now_utc()
                )
                if HELP_THUMBNAIL:
                    embed.set_thumbnail(url=HELP_THUMBNAIL)
                embed.set_footer(text="FusionCollab • Admin Guidance")
                return await ctx.send(embed=embed)
        return await ctx.send("Missing required argument.")

    if isinstance(error, commands.BadArgument):
        return await ctx.send("Invalid argument.")

    if isinstance(error, commands.CommandInvokeError):
        original = getattr(error, "original", error)
        print("Command error:", repr(original))
        return await ctx.send("An internal error occurred.")

    print("Unhandled command error:", repr(error))
    await ctx.send("An error occurred.")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    try:
        print("App command error:", repr(error))
        await safe_send(interaction, "An error occurred.", ephemeral=True)
    except Exception:
        pass


# =========================================================
# RUN
# =========================================================

bot.run(TOKEN)
