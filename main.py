import os
import discord
from discord.ext import commands
import yt_dlp
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

if not discord.opus.is_loaded():
    discord.opus.load_opus('libopus.so')  # หรือชื่อไฟล์ Opus library ที่ถูกติดตั้ง

class Song:
    def __init__(self, url, title):
        self.url = url
        self.title = title

song_queue = []
loop_song = False  # ตัวแปรสถานะ loop เพลง

def get_info(url):
    ytdl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'noplaylist': True,
        'extract_flat': False,
        'source_address': '0.0.0.0'
    }
    with yt_dlp.YoutubeDL(ytdl_opts) as ytdl:
        info = ytdl.extract_info(url, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        return {
            'url': info['url'],
            'title': info.get('title', 'Unknown Title'),
            'webpage_url': info.get('webpage_url', url)
        }

async def play_next(ctx):
    global loop_song
    if len(song_queue) > 0:
        song = song_queue[0]
        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }
        source = discord.FFmpegPCMAudio(song.url, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: bot.loop.create_task(after_play(ctx, e)))
        await ctx.send(f"🎶 กำลังเล่น: **{song.title}**")
    else:
        # รีเซ็ตสถานะทั้งหมดตอนออกจากช่องเสียง
        song_queue.clear()
        loop_song = False
        await ctx.voice_client.disconnect()
        await ctx.send("หมดคิวเพลงแล้ว บอทออกจากช่องเสียงและรีเซ็ตสถานะทั้งหมด")

async def after_play(ctx, error):
    global loop_song
    if error:
        print(f'Error playing song: {error}')
    try:
        if not loop_song:
            if len(song_queue) > 0:
                song_queue.pop(0)
        if len(song_queue) > 0:
            await play_next(ctx)
        else:
            await ctx.send("คิวเพลงหมดแล้วน้าอยากฟังเพลงอะไรพิมพ์มาได้เลยเบ้บ")
    except Exception as e:
        print(f"Error in after_play: {e}")

@bot.command()
async def play(ctx):
    if ctx.author.voice is None:
        await ctx.send("❌ คุณต้องอยู่ใน voice channel ก่อน.")
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await channel.connect()
    else:
        await ctx.voice_client.move_to(channel)

    await ctx.send("✅ บอทเชื่อมต่อสำเร็จแล้ว!")

    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()
    elif ctx.voice_client.channel != ctx.author.voice.channel:
        await ctx.voice_client.move_to(ctx.author.voice.channel)

    info = get_info(url)
    song = Song(info['url'], info['title'])
    song_queue.append(song)
    await ctx.send(f"✅ เพิ่มเพลง **{song.title}** เข้าในคิวแล้วค่ะ")

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

@bot.command(name='stop')
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        song_queue.clear()
        global loop_song
        loop_song = False
        await ctx.send("⏹️ หยุดเล่นเพลงและออกจากช่องเสียงแล้วนะเบ้บ")
    else:
        await ctx.send("บอทไม่ได้อยู่ในช่องเสียง!")

@bot.command(name='skip')
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ ข้ามเพลงแล้วจ้า")
    else:
        await ctx.send("ไม่มีเพลงเล่นอยู่ตอนนี้")

@bot.command(name='leave')
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        song_queue.clear()
        global loop_song
        loop_song = False
        await ctx.send("👋 บอทได้ออกจากช่องเสียงแล้วไว้ใช้บอทใหม่นะคะ")
    else:
        await ctx.send("บอทไม่ได้อยู่ในช่องเสียงอยู่แล้วนะคะเบ้บ!")

@bot.command(name='queue')
async def queue_(ctx):
    if len(song_queue) == 0:
        await ctx.send("🎵 ไม่มีเพลงในคิวตอนนี้")
    else:
        queue_list = ""
        for i, song in enumerate(song_queue, start=1):
            queue_list += f"{i}. {song.title}\n"
        await ctx.send(f"🎶 **คิวเพลง:**\n{queue_list}")

@bot.command(name='loop')
async def loop(ctx):
    global loop_song
    loop_song = not loop_song
    status = "เปิดแล้วค่ะ" if loop_song else "ปิดแล้วค่ะ"
    await ctx.send(f"🔁 Loop: **{status}**")

@bot.command(name='help')
async def help_command(ctx):
    author = ctx.author.mention
    help_text = f"""
สวัสดี {author} นี่คือคำสั่งที่คุณสามารถใช้ได้:

**!play <url>** - เล่นเพลงจาก YouTube หรือเพิ่มเพลงเข้าในคิว  
**!stop** - หยุดเพลงและออกจากช่องเสียง  
**!skip** - ข้ามเพลงปัจจุบัน  
**!queue** - แสดงคิวเพลงที่รอเล่น  
**!loop** - สลับสถานะเล่นเพลงซ้ำ (loop)  
**!help** - แสดงข้อความช่วยเหลือนี้  

ขอบคุณที่ใช้บอทของเรา 🎶
"""
    await ctx.send(help_text)

keep_alive()
bot.run(os.getenv("TOKEN"))
