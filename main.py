import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio
from dotenv import load_dotenv
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from urllib.parse import urlparse

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

music_queues = {}  # {guild_id: [{"source": YTDLSource, "channel": TextChannel}, ...]}
loop_status = {}   # {guild_id: bool}
idle_timers = {}   # {guild_id: asyncio.Task}  <-- เพิ่มตัวแปรนี้

load_dotenv()
discord_token = os.getenv("DISCORD_TOKEN")
sp_client_id = os.getenv("SPOTIPY_CLIENT_ID")
sp_client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
sp_auth = SpotifyClientCredentials(client_id=sp_client_id, client_secret=sp_client_secret)
sp = spotipy.Spotify(auth_manager=sp_auth)

ytdl_format_options = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
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
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

def is_spotify_url(url):
    return "open.spotify.com" in url

def extract_spotify_id(url):
    parsed = urlparse(url)
    return parsed.path.split("/")[-1]

async def get_spotify_titles(url):
    titles = []
    if "track" in url:
        track = sp.track(url)
        titles.append(f"{track['name']} {track['artists'][0]['name']}")
    elif "playlist" in url:
        playlist_id = extract_spotify_id(url)
        results = sp.playlist_tracks(playlist_id)
        for item in results["items"]:
            track = item["track"]
            titles.append(f"{track['name']} {track['artists'][0]['name']}")
    return titles

async def start_idle_timer(guild_id, voice_client):
    await asyncio.sleep(300)  # 5 นาที
    if not voice_client.is_playing() and not music_queues.get(guild_id):
        await voice_client.disconnect()
        loop_status[guild_id] = False
        print(f"🕒 บอทออกจากห้องเสียงในเซิร์ฟเวอร์ {guild_id} เนื่องจากไม่มีการใช้งาน")
        channel = music_queues.get(guild_id, [{}])[0].get("channel")
        if channel:
            await channel.send("🕒 ไม่มีการใช้งานเกิน 5 นาที บอทจึงออกจากห้องเสียงแล้ว")
    idle_timers.pop(guild_id, None)

def cancel_idle_timer(guild_id):
    task = idle_timers.get(guild_id)
    if task and not task.done():
        task.cancel()
    idle_timers.pop(guild_id, None)

def after_error_callback(future):
    try:
        future.result()
    except Exception as e:
        print(f"[ERROR in after callback] {e}")

def play_next_song(error, guild_id):
    if error:
        print(f"[ERROR in after callback] {error}")
    coro = play_next(guild_id)
    fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    fut.add_done_callback(after_error_callback)

async def play_next(guild_id):
    queue = music_queues.get(guild_id, [])
    voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)

    if not voice_client or not voice_client.is_connected():
        music_queues[guild_id] = []
        loop_status[guild_id] = False
        return

    if loop_status.get(guild_id, False) and queue:
        original_source = queue[0]["source"]
        try:
            # โหลดใหม่ทุกครั้งเพื่อให้เล่นได้ซ้ำจริง
            new_source = await YTDLSource.from_url(original_source.url, loop=bot.loop, stream=True)
            queue[0]["source"] = new_source
            voice_client.play(new_source, after=lambda e: play_next_song(e, guild_id))
            # ไม่แสดงข้อความ "กำลังเล่นซ้ำ"
        except Exception as e:
            print(f"[ERROR in loop playback] {e}")
            queue.pop(0)
            await play_next(guild_id)
    else:
        if queue:
            queue.pop(0)
        music_queues[guild_id] = queue

        if queue:
            source = queue[0]["source"]
            voice_client.play(source, after=lambda e: play_next_song(e, guild_id))
            await queue[0]["channel"].send(f"🎶 กำลังเล่น: **{source.title}**")
        else:
            loop_status[guild_id] = False
            idle_timers[guild_id] = asyncio.create_task(start_idle_timer(guild_id, voice_client))

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

@bot.tree.command(name="play", description="เล่นเพลงจาก YouTube หรือ Spotify")
@app_commands.describe(query="ชื่อเพลงหรือ URL YouTube/Spotify ที่ต้องการเล่น")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    voice_channel = interaction.user.voice.channel if interaction.user.voice else None
    if not voice_channel:
        await interaction.followup.send("❌ คุณต้องอยู่ในห้องเสียงก่อนสั่งเล่นเพลง")
        return

    guild_id = interaction.guild.id
    cancel_idle_timer(guild_id)  # ยกเลิกตัวจับเวลาหากกำลังนับ

    voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    if not voice_client or not voice_client.is_connected():
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    if is_spotify_url(query):
        try:
            titles = await get_spotify_titles(query)
        except Exception as e:
            await interaction.followup.send(f"❌ ดึงข้อมูลจาก Spotify ไม่สำเร็จ: {e}")
            return
    else:
        titles = [query]

    if guild_id not in music_queues:
        music_queues[guild_id] = []

    added_titles = []

    for title in titles:
        try:
            source = await YTDLSource.from_url(title, loop=bot.loop, stream=True)
            music_queues[guild_id].append({"source": source, "channel": interaction.channel})
            added_titles.append(source.title)
        except Exception as e:
            await interaction.followup.send(f"❌ ไม่สามารถเล่นเพลง: `{title}` - {e}")

    if not voice_client.is_playing() and music_queues[guild_id]:
        try:
            voice_client.play(
                music_queues[guild_id][0]["source"],
                after=lambda e: play_next_song(e, guild_id)
            )
            await interaction.followup.send(f"🎶 เริ่มเล่น: **{music_queues[guild_id][0]['source'].title}**")
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดขณะเล่นเพลง: {e}")
    else:
        if added_titles:
            await interaction.followup.send(f"➕ เพิ่ม {len(added_titles)} เพลงจาก Spotify ลงคิวแล้ว")

@bot.tree.command(name="skip", description="ข้ามเพลงที่กำลังเล่นและปิด loop")
async def skip(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    cancel_idle_timer(guild_id)  # ยกเลิกตัวจับเวลาหากมี

    voice_client = discord.utils.get(bot.voice_clients, guild__id=guild_id)
    if not voice_client or not voice_client.is_connected():
        await interaction.response.send_message("❌ บอทไม่ได้อยู่ในห้องเสียง")
        return

    loop_status[guild_id] = False
    if voice_client.is_playing():
        voice_client.stop()

    await play_next(guild_id)
    await interaction.response.send_message("⏭️ เพลงได้ถูกข้ามแล้ว")

@bot.tree.command(name="stop", description="หยุดเล่นเพลงทั้งหมดและออกจากห้องเสียง")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    cancel_idle_timer(guild_id)

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
        "▶️ `/play <ชื่อเพลงหรือ URL>` - เล่นเพลงจาก YouTube หรือ Spotify\n"
        "⏭️ `/skip` - ข้ามเพลงที่กำลังเล่น และปิด loop\n"
        "⏹️ `/stop` - หยุดเล่นเพลงทั้งหมดและออกจากห้องเสียง\n"
        "🔁 `/loop` - เปิด/ปิดการเล่นเพลงซ้ำ (toggle)\n"
        "📃 `/queue` - แสดงคิวเพลงที่รอเล่น\n"
        "ℹ️ `/help` - แสดงรายการคำสั่งทั้งหมดนี้"
    )
    await interaction.response.send_message(help_text)

bot.run(discord_token)
