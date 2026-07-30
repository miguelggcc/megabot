from discord.ext import commands
import discord
import json
import os
import logging
import urllib.request
import urllib.parse
import shutil
import time
from aiohttp import web
import asyncio

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


class RadarrAPI:

    def __init__(self):
        self.base_url = os.getenv("RADARR_BASE_URL")
        self.api_key = os.getenv("RADARR_API_KEY")

    def request(self, endpoint, method='GET', data=None):
        url = f"{self.base_url}/{endpoint}"

        body = json.dumps(data).encode('utf-8') if data else None

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('Content-Type', 'application/json')
        req.add_header('X-Api-Key', self.api_key)

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            logging.error(f"Error HTTP {e.code}")
            return None
        except Exception as e:
            logging.error(f"Error: {e}")
            return None

    def search_movie(self, titulo):
        return self.request(f"movie/lookup?term={urllib.parse.quote(titulo)}")

    def get_all_movies(self):
        return self.request("movie") or []

    def add_movie(self, titulo, year, tmdb_id, root_folder, quality_profile=1, search=False):
        return self.request("movie", method='POST', data={
            "title": titulo,
            "year": year,
            "tmdbId": tmdb_id,
            "qualityProfileId": quality_profile,
            "rootFolderPath": root_folder,
            "monitored": True,
            "addOptions": {"searchForMovie": search}
        })

    def refresh_movie(self, movie_id):
        return self.request("command", method='POST', data={
            "name": "RefreshMovie",
            "movieId": int(movie_id)
        })
        
    def get_quality_profiles(self):
        return self.request("qualityProfile")
    
    def auto_import_radarr(self, file_path, save_to):

        father_dir = os.path.dirname(file_path)
        file_path = os.path.abspath(file_path)
        logging.info(file_path)
        # 1. Scan directory
        res = self.request(
            f"manualimport?folder={urllib.parse.quote(father_dir)}&filterExistingFiles=false")
        files = next(
            (r for r in res if r['path'] == file_path), None)

        if not files:
            logging.error("Radarr can't see file.")
            return
        movie_id = None

        # Movie already in the library
        if files.get('movie'):
            logging.info(files['movie'])
            movie_id = files['movie']['id']
        else:
            # If not in library, search and create
            # os.path.basename(carpeta_padre)
            file_name = os.path.basename(file_path)
            logging.info(
                f"Seraching info of '{file_name}' in Radarr...")
            search = self.search_movie(file_name)

            if search:
                found_movie = search[0]

                title = f"{found_movie['title']} ({found_movie['year']})"
                base_dir = os.path.dirname(os.path.normpath(file_path))
                target_dir = os.path.join(save_to, title)
                logging.info(target_dir)
                try:
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir, exist_ok=True)
                        logging.info(f"Directory created: {target_dir}")
                    else:
                        logging.info(f"Directory already exists...")
                except Exception as e:
                    logging.error(
                        f"Error craeting directory {target_dir}: {e}")
                # If it already exists, move the content and delete directory once empty
                for item in os.listdir(father_dir):
                    shutil.move(os.path.join(father_dir, item), target_dir)

                new_movie = self.add_movie(
                    found_movie['title'], found_movie['year'],
                    found_movie['tmdbId'], save_to)

                movie_id = new_movie['id']
                new_path = os.path.join(target_dir, file_name)

                # Import from the new path
                if movie_id:
                    import_payload = [{
                        "path": new_path,  # <--- NEW PATH
                        "movieId": movie_id,
                        "quality": files['quality'],
                        "importMode": "move"
                    }]
                    self.request(
                        "manualimport", method='POST', data=import_payload)
                    logging.info(
                        f"Movie imported to Radarr from: {new_path}")

                logging.info(
                    f"Movie '{found_movie['title']}' created successfully.")

class PersistentQueue:

    def __init__(self, queue_file='queue.json'):
        self.queue_file = queue_file

    def load(self):
        if not os.path.exists(self.queue_file):
            return []
        try:
            with open(self.queue_file) as f:
                return json.load(f)
        except:
            return []

    def save(self, queue):
        with open(self.queue_file, 'w') as f:
            json.dump(queue, f)

    def add(self, file_path):
        queue = self.load()
        queue.append({
            "file_path": file_path,
            "timestamp": time.time(),
            "status": "pending"
        })
        self.save(queue)

    def get_pending(self):
        return [item for item in self.load() if item['status'] == 'pending']

    def mark_completed(self, file_path):
        queue = self.load()
        for item in queue:
            if item['file_path'] == file_path:
                item['status'] = 'completed'
        self.save(queue)

    def mark_error(self, file_path):
        queue = self.load()
        for item in queue:
            if item['file_path'] == file_path:
                item['status'] = 'error'
        self.save(queue)


class RadarrManager(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.radarr_api = RadarrAPI()
        self.queue = PersistentQueue()
        self.radarr_channel = None
        self.events = {
            'Import': ('✅', 'Imported movie', 0x00ff00),
            'Grab': ('🔎', 'Grabbed movie', 0x00ff99),
            'Download': ('🎬', 'Downloaded movie', 0x0099ff),
            'Rename': ('📝', 'Renamed movie', 0xffff00),
            'MovieAdded': ('➕', 'Added movie', 0x00ff00),
            'MovieDelete': ('❌', 'Deleted movie', 0xff0000),
        }
        # Webhook
        self.webhook_app = None
        self.webhook_runner = None
        self.webhook_site = None

        # self.procesar_cola_task.start()

    @commands.Cog.listener()
    async def on_ready(self):

        try:
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).send_messages:
                        self.radarr_channel = channel
        except:
            logging.error("Error starting the bot")
            logging.info("✅ RadarrManage ready!")

        await self._start_webhook_server()

    # ==========================================

    async def _start_webhook_server(self):

        async def radarr_webhook_handler(request):
            try:
                data = await request.json()
                event = data.get('eventType', 'Unknown')
                movie = data.get('movie', {})
                title = f"{movie.get('title', 'Unknown')} ({movie.get('year', 'Unknown')})"
                await self.send_webhook_message(event, title)

                return web.Response(text='{"status": "ok"}', content_type='application/json')
            except Exception as e:
                logging.error(f"Error in webhook: {e}")
                return web.Response(text='{"status": "error"}', content_type='application/json', status=500)

        self.webhook_app = web.Application()
        self.webhook_app.router.add_post(
            '/radarr-webhook', radarr_webhook_handler)

        self.webhook_runner = web.AppRunner(self.webhook_app)
        await self.webhook_runner.setup()
        self.webhook_site = web.TCPSite(self.webhook_runner, '0.0.0.0', 5001)
        await self.webhook_site.start()

        await self.radarr_channel.send("Radarr manager is running!")
        logging.info("✅ Webhook listening port 5001")

    async def on_cog_unload(self):
        if self.webhook_runner:
            await self.webhook_runner.cleanup()

    # ===========================================

    def add_to_queue(self, file_path):
        self.queue.add(file_path)

    async def send_webhook_message(self, event_type, movie_title):
        if not self.radarr_channel:
            logging.warning("Radarr channel not configured")
            return False

        emoji, action, color = self.events.get(
            event_type, ('📌', str(event_type), 0x808080))

        embed = discord.Embed(
            title=f"{emoji} {action}",
            description=f"`{movie_title}`",
            color=color
        )
        embed.set_footer(text="Radarr")

        await self.radarr_channel.send(embed=embed)
        logging.info(f"Webhook: {event_type} - {movie_title}")
        return True

    # ============= TASKS =============

    '''@tasks.loop(seconds=30)
    async def procesar_cola_task(self):
        """Procesar cola cada 30 segundos"""
        try:
            pendientes = self.queue.get_pending()

            if not pendientes:
                return

            logging.info(f"Procesando {len(pendientes)} archivo(s)...")

            for item in pendientes:
                file_path = item['file_path']
                success, nombre = self.organizer.organize_file(file_path)

                if success:
                    self.queue.mark_completed(file_path)
                    mensaje = f"✅ Importada: **{nombre}**"
                else:
                    self.queue.mark_error(file_path)
                    mensaje = f"❌ Error: {os.path.basename(file_path)}"

                if self.radarr_channel:
                    await self.radarr_channel.send(mensaje)

            self._notify_plex()

        except Exception as e:
            logging.error(f"Error: {e}")

    def _notify_plex(self):
        """Notificar a Plex"""
        try:
            url = f"{self.config['plex_url']}/library/sections/{self.config['plex_lib_id']}/refresh?X-Plex-Token={self.config['plex_token']}"
            urllib.request.urlopen(url, timeout=10)
            logging.info("Plex notificado")
        except Exception as e:
            logging.error(f"Error Plex: {e}")'''

    # ============= COMANDOS =============
    @commands.command()
    async def add(self, ctx, title=commands.parameter(
            default=None, description="Movie title")):
        search = self.radarr_api.search_movie(title)

        if search:
            movie = search[0]
        title = movie['title']
        year = movie['year']
        tmdb_id = movie['tmdbId']

        # Verificar si existe
        if any(p['tmdbId'] == tmdb_id for p in self.radarr_api.get_all_movies()):
            await ctx.send(f"`{title} ({year})` already exists")
            return

        question = await ctx.send(f"Do you want to download the movie `{title} ({year})`?")
        await question.add_reaction('✅')
        await question.add_reaction('❌')

        def check(reaction, user): return reaction.message.id == question.id and user == ctx.message.author and str(
            reaction.emoji) in ['✅', '❌']
        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
            match str(reaction.emoji):
                case '✅':
                    await ctx.send(f"➕ Adding: **{title} ({year})**...")
                    self.radarr_api.add_movie(
                        titulo=title,
                        year=year,
                        tmdb_id=tmdb_id,
                        root_folder="/downloads/films/",
                        quality_profile=4,
                        search=True
                    )
                case _:
                    await self.cancel(ctx)
        except asyncio.TimeoutError:
            await ctx.send('You took too long to respond! Please try again.')
            return
        except Exception as e:
            logging.error(f"Error downloding: {e}")
            return

    @commands.command(name='quality_profiles')
    async def list_quality_profiles(self, ctx):

        profiles = self.radarr_api.get_quality_profiles()

        if not profiles:
            await ctx.send("❌ No profiles found")
            return

        msg = "📊 **Quality Profiles:**\n"
        for profile in profiles:
            msg += f"• ID `{profile['id']}`: {profile['name']}\n"

        await ctx.send(msg)
    
    @commands.command()
    async def status(self, ctx):
        """Stuts of queue"""
        queue = self.queue.load()
        pending = len([q for q in queue if q['status'] == 'pending'])
        completed = len([q for q in queue if q['status'] == 'completed'])
        errors = len([q for q in queue if q['status'] == 'error'])

        msg = f"📋 **Queue:** {len(queue)} total | ⏳ {pending} pending | ✅ {completed} completed | ❌ {errors} errors"
        await ctx.send(msg)
        
    @commands.command()
    async def health(self, ctx):
        """Radarr health status with size and downloading movies"""
        try:
            
            all_movies = self.radarr_api.get_all_movies()
            downloaded = [m for m in all_movies if m.get('hasFile')]
            monitored = [m for m in all_movies if m.get('monitored')]
            missing = [m for m in monitored if not m.get('hasFile')]

            # Calculate total size (in bytes)
            total_size_bytes = sum(m.get('sizeOnDisk', 0) for m in downloaded)

            size_gb = round(total_size_bytes/ (1024**3), 2)

            # Create embed
            embed = discord.Embed(
                title="📊 Radarr Health Status",
                color=0x00ff00 if missing == [] else 0xffaa00
            )

            # General summary
            embed.add_field(
                name="📈 Summary",
                value=f"Total: `{len(all_movies)}`\n"
                    f"Downloaded: `{len(downloaded)}`\n"
                    f"Monitored: `{len(monitored)}`\n"
                    f"Missing: `{len(missing)}`",
                inline=False
            )

            # Library size
            embed.add_field(
                name="💾 Library Size",
                value=f"`{size_gb:.2f} GB` ({len(downloaded)} movies)",
                inline=False
            )

            if missing:
                # Show maximum 15 movies to avoid clutter
                searching_list = ""
                for i, movie in enumerate(missing[:15], 1):
                    searching_list += f"{i}. **{movie['title']}** ({movie['year']})\n"

                if len(missing) > 15:
                    searching_list += f"\n... and {len(missing) - 15} more"

                embed.add_field(
                    name=f"🔎 Searching for downloads ({len(missing)})",
                    value=searching_list,
                    inline=False
                )
            else:
                embed.add_field(
                    name="🔎 Searching for downloads",
                    value="✅ None",
                    inline=False
                )

            # Footer with timestamp
            since = min(all_movies, key=lambda x: x['added'])['added'][:10] if all_movies else "N/A"
            embed.set_footer(text=f"Since: {since}")

            await ctx.send(embed=embed)

        except Exception as e:
            logging.error(f"Error in Radarr: {e}")
            await ctx.send(f"❌ Error: {e}")