#!/usr/bin/env python3
"""
Cog RadarrManager para gestión de Radarr.
"""

from discord.ext import commands, tasks
import json
import os
import logging
import urllib.request
import urllib.parse
import shutil
import time
from aiohttp import web
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RadarrAPI:

    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key

    def radarr_request(self,endpoint, method='GET', data=None):

        self.api_key = os.getenv("RADARR_API_KEY")
        self.base_url = os.getenv("RADARR_BASE_URL")
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

    def add_movie(self, titulo, year, tmdb_id, root_folder, quality_profile=1):
        return self.request("movie", method='POST', data={
            "title": titulo,
            "year": year,
            "tmdbId": tmdb_id,
            "qualityProfileId": quality_profile,
            "rootFolderPath": root_folder,
            "monitored": True,
            "addOptions": {"searchForMovie": False}
        })

    def refresh_movie(self, movie_id):
        return self.request("command", method='POST', data={
            "name": "RefreshMovie",
            "movieId": int(movie_id)
        })

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
        busqueda = self.radarr_api.search_movie(file_base)

        if not busqueda:
            logging.error(f"Not found")
            return False, None

        pelicula = busqueda[0]
        nombre_oficial = f"{pelicula['title']} ({pelicula['year']})"
        tmdb_id = pelicula['tmdbId']
        movie_id = None

        todas = self.radarr_api.get_all_movies()
        existe = any(p['tmdbId'] == tmdb_id for p in todas)

        if existe:
            movie_id = next(p['id'] for p in todas if p['tmdbId'] == tmdb_id)
            logging.info(f"Ya existe: {nombre_oficial}")
        else:
            nueva_peli = self.radarr_api.add_movie(
                pelicula['title'], 
                pelicula['year'], 
                tmdb_id, 
                self.downloads_dir
            )

            if not nueva_peli:
                return False, None

            movie_id = nueva_peli['id']

        target_dir = os.path.join(self.downloads_dir, nombre_oficial)

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

        return True, nombre_oficial

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

class RadarrManagerCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        with open('config.json') as f:
            config = json.load(f)

        self.radarr_api = RadarrAPI(config['radarr_url'], config['radarr_api_key'])
        self.organizer = FilesOrganizer(self.radarr_api, config['downloads_dir'])
        self.queue = PersistentQueue()
        self.config = config
        self.radarr_channel = None

        # Webhook
        self.webhook_app = None
        self.webhook_runner = None
        self.webhook_site = None

        self.procesar_cola_task.start()

    @commands.Cog.listener()
    async def on_ready(self):
        self.radarr_channel = self.bot.get_channel(self.config['discord_channel_id'])
        logging.info("✅ RadarrManage ready!")

        await self._start_webhook_server()

    # ==========================================

    async def _start_webhook_server(self):

        async def radarr_webhook_handler(request):
            try:
                data = await request.json()
                event = data.get('eventType', 'Unknown')
                titulo = data.get('movie', {}).get('title', 'Desconocida')
                await self.send_webhook_message(event, titulo)

                return web.Response(text='{"status": "ok"}', content_type='application/json')
            except Exception as e:
                logging.error(f"Error en webhook: {e}")
                return web.Response(text='{"status": "error"}', content_type='application/json', status=500)

        self.webhook_app = web.Application()
        self.webhook_app.router.add_post('/radarr-webhook', radarr_webhook_handler)

        self.webhook_runner = web.AppRunner(self.webhook_app)
        await self.webhook_runner.setup()
        self.webhook_site = web.TCPSite(self.webhook_runner, '0.0.0.0', 5000)
        await self.webhook_site.start()

        logging.info("✅ Webhook listening port 5000")

    async def on_cog_unload(self):
        if self.webhook_runner:
            await self.webhook_runner.cleanup()

    # ===========================================

    def add_to_queue(self, file_path):
        self.queue.add(file_path)

    def format_webhook_message(self, event_type, movie_title):

        emojis = {
            'Import': '✅',
            'Download': '🎬',
            'Rename': '📝',
            'MovieAdded': '➕',
            'MovieDelete': '❌'
        }
        emoji = emojis.get(event_type, '📌')
        return f"{emoji} **[Radarr]** {event_type}: **{movie_title}**"

    async def send_webhook_message(self, event_type, movie_title):
        if not self.radarr_channel:
            logging.warning("Radarr channel not configured")
            return False

        mensaje = self.format_webhook_message(event_type, movie_title)
        await self.radarr_channel.send(mensaje)
        logging.info(f"Webhook sent: {event_type} - {movie_title}")
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

    @commands.command(name='status')
    async def status(self, ctx):
        """Ver estado de la cola"""
        queue = self.queue.load()
        pending = len([q for q in queue if q['status'] == 'pending'])
        completed = len([q for q in queue if q['status'] == 'completed'])
        errors = len([q for q in queue if q['status'] == 'error'])

        msg = f"📋 **Queue:** {len(queue)} total | ⏳ {pending} pending | ✅ {completed} completed | ❌ {errors} errors"
        await ctx.send(msg)