"""Discord approval loop + scheduler.

Monday morning: posts all pending drafts (21 per pipeline) to the channel, each
with Approve / Reject buttons.
  Approve -> mark approved, schedule a publish slot.
  Reject  -> mark rejected, regenerate a NEW proposition, post it for approval.
Cycle completes when every slot per pipeline is approved + scheduled.

Run:  py -m pipelines.approval_bot            (bot + scheduler, posts next Monday)
      py -m pipelines.approval_bot --post-now (generate + post immediately, for testing)
"""
from __future__ import annotations
import asyncio, logging, argparse, datetime as dt
from pathlib import Path
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .common import config, db
from . import batch

log = logging.getLogger("bot")
PUBLISH_HOUR = 9  # local hour to schedule approved reels through the week

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ----------------------------------------------------------- scheduling slots
def _next_slot(week: str, taken: int) -> dt.datetime:
    """Spread approved reels across the week, one per day at PUBLISH_HOUR."""
    year, wnum = int(week[:4]), int(week[6:])
    monday = dt.date.fromisocalendar(year, wnum, 1)
    base = dt.datetime(monday.year, monday.month, monday.day, PUBLISH_HOUR, 0)
    return base + dt.timedelta(days=taken % 7, hours=taken // 7)


# ----------------------------------------------------------- UI
class ReviewView(discord.ui.View):
    def __init__(self, draft_id: int):
        super().__init__(timeout=None)
        self.draft_id = draft_id

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success,
                       custom_id="approve")
    async def approve(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        d = db.get_draft(self.draft_id)
        if not d:
            return await interaction.response.send_message("Draft not found.", ephemeral=True)
        taken = db.count_status(d["pipeline"], "approved", d["week"])
        slot = _next_slot(d["week"], taken)
        db.update_draft(self.draft_id, status="approved", scheduled_for=slot.isoformat())
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **Approved** — scheduled for {slot:%a %d %b %H:%M}", view=self)
        await _check_cycle(interaction.channel, d["pipeline"], d["week"])

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger,
                       custom_id="reject")
    async def reject(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        d = db.get_draft(self.draft_id)
        if not d:
            return await interaction.response.send_message("Draft not found.", ephemeral=True)
        db.update_draft(self.draft_id, status="rejected")
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="❌ **Rejected** — generating a new proposition…",
                                                view=self)
        # Reject loop: new proposition -> new draft -> post for approval
        res = await asyncio.to_thread(batch.regenerate_one, d["pipeline"], d["topic"], d["week"])
        await _post_draft(interaction.channel, res["draft_id"],
                          prefix=f"🔄 Replacement for rejected *{d['title']}* — new topic: **{res['topic']}**")


async def _post_draft(channel, draft_id: int, prefix: str = ""):
    d = db.get_draft(draft_id)
    files = []
    thumb = d.get("thumb_path")
    if thumb and Path(thumb).exists():
        files.append(discord.File(thumb))
    embed = discord.Embed(title=f"[{d['pipeline']}] {d['title']}",
                          description=(d["script"] or "")[:300])
    embed.add_field(name="Topic", value=d["topic"][:200], inline=False)
    embed.add_field(name="Category", value=d.get("category") or "default")
    vid = d.get("video_path")
    if vid and Path(vid).exists() and Path(vid).stat().st_size < 8 * 1024 * 1024:
        files.append(discord.File(vid))  # attach short reel if small enough
    msg = await channel.send(content=prefix or None, embed=embed, files=files,
                             view=ReviewView(draft_id))
    db.update_draft(draft_id, discord_msg=msg.id)


async def _check_cycle(channel, pipeline: str, week: str):
    approved = db.count_status(pipeline, "approved", week)
    if approved >= config.DRAFTS_PER_PIPELINE:
        await channel.send(f"🎉 Pipeline **{pipeline}** cycle complete for {week}: "
                           f"{approved} reels approved & scheduled.")


async def post_week(channel=None):
    """Ensure 21 pending drafts per pipeline exist, then post them all."""
    channel = channel or bot.get_channel(config.DISCORD_CHANNEL_ID)
    week = batch.iso_week()
    for p in ("A", "B"):
        pending = db.drafts_by_status(p, "pending", week)
        need = config.DRAFTS_PER_PIPELINE - len(pending)
        if need > 0:
            await channel.send(f"⏳ Generating {need} drafts for pipeline {p} ({week})…")
            ids = await asyncio.to_thread(batch.generate_week, p, need, week)
            pending += [db.get_draft(i) for i in ids]
        await channel.send(f"📋 **Monday review — Pipeline {p}** · {len(pending)} drafts ({week})")
        for d in pending[:config.DRAFTS_PER_PIPELINE]:
            await _post_draft(channel, d["id"])


@bot.event
async def on_ready():
    db.init()
    log.info("Bot online as %s", bot.user)
    # Re-register persistent views for all pending drafts so buttons remain interactive after restart
    for d in db.drafts_by_status("A", "pending") + db.drafts_by_status("B", "pending"):
        bot.add_view(ReviewView(d["id"]))
    sched = AsyncIOScheduler()
    # Monday 08:00 local: deliver the weekly review
    sched.add_job(lambda: asyncio.create_task(post_week()),
                  "cron", day_of_week="mon", hour=8, minute=0)
    sched.start()
    if getattr(bot, "_post_now", False):
        await post_week()


def main():
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--post-now", action="store_true",
                    help="generate + post immediately instead of waiting for Monday")
    args = ap.parse_args()
    if not config.DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN not set in .env")
    bot._post_now = args.post_now
    bot.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
