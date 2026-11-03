# src/discord_verifier_bot.py
import os
import re
import aiohttp
import discord
from discord.ext import commands

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
PROPSTEIN_VERIFY_URL = os.environ.get(
    "PROPSTEIN_VERIFY_URL",
    os.environ.get("PropWire_VERIFY_URL", "https://propstein.vercel.app/api/v1/verify-receipt"),
)
POST_BETS_CHANNEL_ID = int(os.environ.get("POST_BETS_CHANNEL_ID", "0"))
VERIFIED_EXECUTION_ROLE_NAME = "Receipt Verified"
SHARP_CLV_ROLE_NAME = "CLV Proven (50+ Slips)"

SHA256_REGEX = re.compile(r"\b([a-fA-F0-9]{64})\b")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def build_verification_embed(author: discord.Member, payload: dict) -> discord.Embed:
    integrity = payload["integrity"]
    lifecycle = payload["lifecycle"]
    entry = lifecycle["entry"]
    closing = lifecycle.get("closing")
    settlement = lifecycle.get("settlement")
    stage = integrity["lifecycle_stage"]

    direction_arrow = "↑" if entry["direction"] == "OVER" else "↓"
    price_str = f"+{entry['price']}" if entry["price"] > 0 else f"{entry['price']}"

    stage_badges = {
        "STAGE_1_ENTRY_PROVEN": ("🟢 STAGE 1 · PRE-GAME ENTRY PROVEN", 0x10B981),
        "STAGE_2_CLV_LOCKED": ("🔵 STAGE 2 · T-0 CLOSING LINE LOCKED", 0x3B82F6),
        "STAGE_3_SETTLEMENT_FINALIZED": ("🟣 STAGE 3 · OFFICIAL BOXSCORE SETTLED", 0x8B5CF6),
    }

    badge_text, color_hex = stage_badges.get(stage, ("VERIFIED RECEIPT", 0x10B981))

    embed = discord.Embed(
        title=f"{entry['player']} ({entry['team']}) · {direction_arrow} {entry['line']} ({price_str})",
        description=f"**{badge_text}**\nBook: `{entry['book']}` · Market: `{entry['market']}`",
        color=color_hex,
    )
    embed.set_author(name=f"PropStein Cryptographic Audit · {author.display_name}")

    # Entry Metrics
    embed.add_field(
        name="1. Entry Quote",
        value=(
            f"Line: **{direction_arrow} {entry['line']}** ({price_str})\n"
            f"Fair: `{entry['fair_line_at_entry']:.1f}` (+{entry['edge_pct_at_entry']:.1f}% Edge)\n"
            f"Hash: `#{entry['receipt_hash'][:10]}…`"
        ),
        inline=True,
    )

    # Closing Line Metrics
    if closing:
        embed.add_field(
            name="2. T-0 Closing Lock",
            value=(
                f"Close: **{closing['line']}**\n"
                f"Fair Close: `{closing['fair_line']:.1f}`\n"
                f"Hash: `#{closing['snapshot_hash'][:10]}…`"
            ),
            inline=True,
        )
    else:
        embed.add_field(
            name="2. T-0 Closing Lock",
            value="⧗ *Awaiting Kickoff (T-5m Lock)*",
            inline=True,
        )

    # Settlement & CLV Metrics
    if settlement:
        clv_pct = settlement["clv_no_vig_pct"]
        clv_yards = settlement["clv_delta_yards"]
        sign = "+" if clv_pct >= 0 else ""
        yard_sign = "+" if clv_yards >= 0 else ""
        embed.add_field(
            name="3. Official Settlement",
            value=(
                f"Outcome: **{settlement['outcome']}** (Stat: `{settlement['settled_stat']}`)\n"
                f"CLV: **{sign}{clv_pct:.2f}%** ({yard_sign}{clv_yards}y)\n"
                f"Hash: `#{settlement['settlement_hash'][:10]}…`"
            ),
            inline=True,
        )
    else:
        embed.add_field(
            name="3. Official Settlement",
            value="⧗ *Awaiting Final Gamebook*",
            inline=True,
        )

    embed.set_footer(
        text="RFC-8785 Canonical JSON · Zero Unverified Picks Permitted"
    )
    return embed


@bot.event
async def on_ready():
    print(f"PropStein Discord Gatekeeper Bot active as {bot.user} (ID: {bot.user.id if bot.user else 'N/A'})")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Only police the designated #post-bets channel if configured
    if POST_BETS_CHANNEL_ID and message.channel.id != POST_BETS_CHANNEL_ID:
        await bot.process_commands(message)
        return

    match = SHA256_REGEX.search(message.content)
    if not match:
        # In strict #post-bets mode, non-receipt messages are deleted
        if POST_BETS_CHANNEL_ID and message.channel.id == POST_BETS_CHANNEL_ID:
            await message.delete()
            try:
                await message.author.send(
                    "⚠ **PropStein Gatekeeper:** Unverified picks and screenshots are blocked in `#post-bets`. "
                    "Include your 64-character SHA-256 execution receipt hash from the PropStein terminal."
                )
            except discord.Forbidden:
                pass
        return

    receipt_hash = match.group(1).lower()

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                PROPSTEIN_VERIFY_URL,
                json={"receipt_hash": receipt_hash},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    await message.delete()
                    try:
                        await message.author.send(
                            f"❌ **Receipt Verification Failed ({resp.status}):** Hash `{receipt_hash[:12]}…` "
                            "was not found in the PropStein ledger."
                        )
                    except discord.Forbidden:
                        pass
                    return
                data = await resp.json()
        except Exception as e:
            print(f"[discord-bot] Verification error: {e}")
            return

    integrity = data.get("integrity", {})
    if integrity.get("tamper_detected") or integrity.get("overall_trust") != "CRYPTOGRAPHICALLY_PROVEN":
        await message.delete()
        try:
            await message.author.send(
                f"🚨 **Tamper Alert:** Receipt `{receipt_hash[:12]}…` failed RFC-8785 SHA-256 recalculation."
            )
        except discord.Forbidden:
            pass
        return

    # Valid cryptographic receipt -> Post verified embed & grant execution role
    embed = build_verification_embed(message.author, data)
    await message.reply(embed=embed, mention_author=False)

    if isinstance(message.author, discord.Member) and message.guild:
        role = discord.utils.get(message.guild.roles, name=VERIFIED_EXECUTION_ROLE_NAME)
        if role and role not in message.author.roles:
            await message.author.add_roles(role, reason="Posted valid PropStein SHA-256 receipt")


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise ValueError("DISCORD_BOT_TOKEN environment variable is required.")
    bot.run(DISCORD_BOT_TOKEN)
