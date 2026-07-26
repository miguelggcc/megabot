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

        carpeta_padre = os.path.dirname(file_path)
        file_path = os.path.abspath(file_path)
        logging.info(file_path)
        # 1. Escaneamos la carpeta
        resultados = self.request(
            f"manualimport?folder={urllib.parse.quote(carpeta_padre)}&filterExistingFiles=false")
        archivo_a_importar = next(
            (r for r in resultados if r['path'] == file_path), None)

        if not archivo_a_importar:
            logging.info("Radarr aún no ve este archivo.")
            return
        movie_id = None

        # 2. Si ya reconoce la peli, usamos su ID
        if archivo_a_importar.get('movie'):
            logging.info(archivo_a_importar['movie'])
            movie_id = archivo_a_importar['movie']['id']
        else:
            # 3. SI NO LA CONOCE: Buscamos en TMDB y la creamos!
            # os.path.basename(carpeta_padre)
            file_name = os.path.basename(file_path)
            logging.info(
                f"Buscando info para crear '{file_name}' en Radarr...")
            busqueda = self.search_movie(file_name)

            if busqueda:
                pelicula_encontrada = busqueda[0]

                nombre_oficial = f"{pelicula_encontrada['title']} ({pelicula_encontrada['year']})"
                base_dir = os.path.dirname(os.path.normpath(file_path))
                target_dir = os.path.join(save_to, nombre_oficial)
                logging.info(target_dir)
                try:
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir, exist_ok=True)
                        logging.info(f"Carpeta creada: {target_dir}")
                    else:
                        logging.info(f"La carpeta ya existe, continuando...")
                except Exception as e:
                    logging.info(
                        f"❌ Error crítico creando carpeta {target_dir}: {e}")
                # Si ya existe, movemos el contenido dentro (y luego borramos la vacía)
                for item in os.listdir(carpeta_padre):
                    shutil.move(os.path.join(carpeta_padre, item), target_dir)

                nueva_peli = self.add_movie(
                    pelicula_encontrada['title'], pelicula_encontrada['year'],
                    pelicula_encontrada['tmdbId'], save_to)

                '''# Creamos la peli en Radarr
                nueva_peli = radarr_request("movie", method='POST', data={
                    "title": pelicula_encontrada['title'],
                    "tmdbId": pelicula_encontrada['tmdbId'],
                    "year": pelicula_encontrada['year'],
                    "qualityProfileId": 1,
                    "rootFolderPath": save_to,
                    "monitored": True,
                    "addOptions": {"searchForMovie": False}
                })'''
                movie_id = nueva_peli['id']
                nuevo_path = os.path.join(target_dir, file_name)

                '''# 3.6. Forzamos un re-escaneo de la nueva carpeta para que Radarr la vea
                radarr_request("command", method='POST', data={
                    "name": "RescanFolder",
                    "folder": target_dir
                })
                # Damos tiempo a Radarr para que procese el nuevo path
                import time
                time.sleep(3) '''

                # 4. Importamos usando el nuevo path y el movie_id
                if movie_id:
                    import_payload = [{
                        "path": nuevo_path,  # <--- USAMOS LA RUTA NUEVA
                        "movieId": movie_id,
                        "quality": archivo_a_importar['quality'],
                        "importMode": "move"
                    }]
                    self.request(
                        "manualimport", method='POST', data=import_payload)
                    logging.info(
                        f"✅ Película importada a Radarr desde: {nuevo_path}")

                # movie_id = nueva_peli['id']
                logging.info(
                    f"Película '{pelicula_encontrada['title']}' creada con éxito.")


class FilesOrganizer:

    def __init__(self, radarr_api, downloads_dir):
        self.radarr_api = radarr_api
        self.downloads_dir = downloads_dir

    def organize_file(self, file_path):
        if not os.path.isfile(file_path):
            logging.error(f"Not found: {file_path}")
            return False, None

        file_name = os.path.basename(file_path)
        file_base = os.path.splitext(file_name)[0]

        logging.info(f"Searching '{file_base}'...")
        search = self.radarr_api.search_movie(file_base)

        if not search:
            logging.error(f"Not found")
            return False, None

        movie = search[0]
        title = f"{movie['title']} ({movie['year']})"
        tmdb_id = movie['tmdbId']
        movie_id = None

        all_movies = self.radarr_api.get_all_movies()
        already_exists = any(p['tmdbId'] == tmdb_id for p in all_movies)

        if already_exists:
            movie_id = next(p['id'] for p in all_movies if p['tmdbId'] == tmdb_id)
            logging.info(f"{title} already exists")
        else:
            new_movie = self.radarr_api.add_movie(
                movie['title'],
                movie['year'],
                tmdb_id,
                self.downloads_dir
            )

            if not new_movie:
                return False, None

            movie_id = new_movie['id']

        target_dir = os.path.join(self.downloads_dir, title)

        try:
            if not os.path.exists(target_dir):
                os.makedirs(target_dir, mode=0o775, exist_ok=True)

            target_file = os.path.join(target_dir, file_name)
            shutil.move(file_path, target_file)
        except Exception as e:
            logging.error(f"Error: {e}")
            return False, None

        try:
            self.radarr_api.refresh_movie(movie_id)
        except Exception as e:
            logging.error(f"Error refrescando: {e}")

        return True, title


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
        self.organizer = FilesOrganizer(
            self.radarr_api, os.getenv("DOWNLOADS_DIR"))
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
    
    @commands.command(name='status')
    async def status(self, ctx):
        """Ver estado de la cola"""
        queue = self.queue.load()
        pending = len([q for q in queue if q['status'] == 'pending'])
        completed = len([q for q in queue if q['status'] == 'completed'])
        errors = len([q for q in queue if q['status'] == 'error'])

        msg = f"📋 **Queue:** {len(queue)} total | ⏳ {pending} pending | ✅ {completed} completed | ❌ {errors} errors"
        await ctx.send(msg)
