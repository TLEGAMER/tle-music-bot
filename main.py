import discord
import os
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio

intents = discord.Intents.default()
intents.message_content = True  # ปิดถ้าไม่ต้องใช้
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

music_queues = {}
loop_status = {}

ytdl_format_options = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if not data:
            raise ValueError("ไม่สามารถดึงข้อมูลจาก URL หรือคำค้นนี้ได้")

        if 'entries' in data:
            if not data['entries']:
                raise ValueError("ไม่พบวิดีโอในรายการ")
            data = data['entries'][0]

        if stream:
            filename = data['url']
        else:
            filename = ytdl.prepare_filename(data)

        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)




def after_error_callback(future):
    try:
        future.result()
    except Exception as e:
        print(f"[ERROR in after callback] {e}")


async def play_next(guild_id):
    queue = music_queues.get(guild_id)
    if not queue or len(queue) == 0:
        voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
        music_queues[guild_id] = []
        loop_status[guild_id] = False
        return

    voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    if not voice_client or not voice_client.is_connected():
        return

    try:
        voice_client.play(
            queue[0]["source"],
            after=lambda e: asyncio.run_coroutine_threadsafe(after_song(guild_id), bot.loop).add_done_callback(after_error_callback)
        )
    except Exception as e:
        print(f"[ERROR] play_next: {e}")
        music_queues[guild_id].pop(0)
        await play_next(guild_id)


async def after_song(guild_id):
    current_loop = loop_status.get(guild_id, False)
    queue = music_queues.get(guild_id)
    print(f"[DEBUG] after_song triggered | loop={current_loop}, queue length={len(queue) if queue else 0}")

    if not queue or len(queue) == 0:
        return

    if current_loop:
        voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
        if voice_client and voice_client.is_connected():
            try:
                voice_client.play(
                    queue[0]["source"],
                    after=lambda e: asyncio.run_coroutine_threadsafe(after_song(guild_id), bot.loop).add_done_callback(after_error_callback)
                )
                channel = queue[0]["channel"]
                await channel.send(f"🔁 กำลังเพลงเล่นซ้ำ: **{queue[0]['source'].title}**")
            except Exception as e:
                print(f"[ERROR] loop play: {e}")
    else:
        music_queues[guild_id].pop(0)

        if len(music_queues[guild_id]) > 0:
            next_song = music_queues[guild_id][0]
            voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
            if voice_client and voice_client.is_connected():
                try:
                    voice_client.play(
                        next_song["source"],
                        after=lambda e: asyncio.run_coroutine_threadsafe(after_song(guild_id), bot.loop).add_done_callback(after_error_callback)
                    )
                    await next_song["channel"].send(f"🎶 กำลังเล่น: **{next_song['source'].title}**")
                except Exception as e:
                    print(f"[ERROR] play next song: {e}")
        else:
            await play_next(guild_id)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"❌ Sync failed: {e}")


@bot.tree.command(name="play", description="เล่นเพลงจาก YouTube หรือชื่อเพลง")
@app_commands.describe(query="ชื่อเพลงหรือ URL YouTube ที่ต้องการเล่น")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    voice_channel = interaction.user.voice.channel if interaction.user.voice else None
    if not voice_channel:
        await interaction.followup.send("❌ คุณต้องอยู่ในห้องเสียงก่อนสั่งเล่นเพลง")
        return

    guild_id = interaction.guild.id

    voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    if not voice_client or not voice_client.is_connected():
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    try:
        source = await YTDLSource.from_url(query, loop=bot.loop, stream=False)
    except Exception as e:
        await interaction.followup.send(f"❌ ไม่สามารถเล่นเพลงได้: {e}")
        return

    if guild_id not in music_queues:
        music_queues[guild_id] = []
    music_queues[guild_id].append({"source": source, "channel": interaction.channel})

    if not voice_client.is_playing():
        try:
            voice_client.play(
                music_queues[guild_id][0]["source"],
                after=lambda e: asyncio.run_coroutine_threadsafe(after_song(guild_id), bot.loop).add_done_callback(after_error_callback)
            )
            await interaction.followup.send(f"🎶 เริ่มเล่น: **{source.title}**")
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดขณะเล่นเพลง: {e}")
    else:
        await interaction.followup.send(f"➕ เพิ่มเพลงในคิว: **{source.title}**")


@bot.tree.command(name="skip", description="ข้ามเพลงที่กำลังเล่นและปิด loop")
async def skip(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    if not voice_client or not voice_client.is_connected():
        await interaction.response.send_message("❌ บอทไม่ได้อยู่ในห้องเสียง")
        return  

    loop_status[guild_id] = False
    if voice_client.is_playing():
        voice_client.stop()

    await interaction.response.send_message("⏭️ เพลงได้ถูกข้ามแล้ว")


@bot.tree.command(name="stop", description="หยุดเล่นเพลงทั้งหมดและออกจากห้องเสียง")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    if not voice_client or not voice_client.is_connected():
        await interaction.response.send_message("❌ บอทไม่ได้อยู่ในห้องเสียง")
        return

    music_queues[guild_id] = []
    loop_status[guild_id] = False

    if voice_client.is_playing():
        voice_client.stop()
    await voice_client.disconnect()

    await interaction.response.send_message("⏹️ หยุดเล่นเพลงทั้งหมดและออกจากห้องเสียงแล้ว")


@bot.tree.command(name="loop", description="เปิด/ปิดการเล่นเพลงซ้ำ (toggle)")
async def loop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    current = loop_status.get(guild_id, False)
    loop_status[guild_id] = not current
    status_text = "เปิด" if loop_status[guild_id] else "ปิด"
    await interaction.response.send_message(f"🔁 loop ได้ถูก: {status_text}")


@bot.tree.command(name="queue", description="ดูรายการเพลงที่รอเล่น")
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    queue = music_queues.get(guild_id, [])
    if not queue:
        await interaction.response.send_message("📃 ยังไม่มีเพลงในคิว")
        return

    msg = "📃 รายการเพลงในคิว:\n"
    for i, item in enumerate(queue, 1):
        msg += f"{i}. {item['source'].title}\n"

    await interaction.response.send_message(msg)


@bot.tree.command(name="help", description="แสดงรายการคำสั่งทั้งหมดของบอท")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "📖 **รายการคำสั่งของบอทเพลง:**\n\n"
        "▶️ `/play <ชื่อเพลงหรือ URL>` - เล่นเพลงจาก YouTube\n"
        "⏭️ `/skip` - ข้ามเพลงที่กำลังเล่น และปิด loop\n"
        "⏹️ `/stop` - หยุดเล่นเพลงทั้งหมดและออกจากห้องเสียง\n"
        "🔁 `/loop` - เปิด/ปิดการเล่นเพลงซ้ำ (toggle)\n"
        "📃 `/queue` - แสดงคิวเพลงที่รอเล่น\n"
        "ℹ️ `/help` - แสดงรายการคำสั่งทั้งหมดนี้"
    )
    await interaction.response.send_message(help_text)


# อ่าน TOKEN จาก Environment Variable
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    print("❌ กรุณาตั้งค่า environment variable: TOKEN")
    exit(1)

bot.run(TOKEN)
