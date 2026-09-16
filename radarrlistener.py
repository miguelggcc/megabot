import datetime

from discord.ext import commands, tasks
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
from letterboxdparser import LetterboxdParser

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class RadarrAPI:

    def __init__(self):
        self.base_url = os.getenv("RADARR_BASE_URL")
        self.api_key = os.getenv("RADARR_API_KEY")
        self.timeout = 30

    def request(self, endpoint, method="GET", data=None):
        url = f"{self.base_url}/{endpoint}"

        body = json.dumps(data).encode("utf-8") if data else None

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Api-Key", self.api_key)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logging.error(f"Error HTTP {e.code}")
            return None
        except Exception as e:
            logging.error(f"Error: {e}")
            return None

    def search_movie(self, title):
        return self.request(f"movie/lookup?term={urllib.parse.quote(title)}")

    def get_movie(self, movie_id):
        return self.request(f"movie/{movie_id}")

    def get_all_movies(self):
        return self.request("movie") or []

    def add_movie(
        self, title, year, tmdb_id, root_folder, quality_profile=1, search=False
    ):
        return self.request(
            "movie",
            method="POST",
            data={
                "title": title,
                "year": year,
                "tmdbId": tmdb_id,
                "qualityProfileId": quality_profile,
                "rootFolderPath": root_folder,
                "monitored": True,
                "addOptions": {"searchForMovie": search},
            },
        )

    def refresh_movie(self, movie_id):
        return self.request(
            "command",
            method="POST",
            data={"name": "RefreshMovie", "movieId": int(movie_id)},
        )

    def get_quality_profiles(self):
        return self.request("qualityProfile")

    def get_queue(self):
        """Get current download queue"""
        return self.request("queue") or []

    def auto_import_radarr(self, file_path, save_to):

        parent_dir = os.path.dirname(file_path)
        file_path = os.path.abspath(file_path)

        # Scan directory
        res = self.request(
            f"manualimport?folder={urllib.parse.quote(parent_dir)}&filterExistingFiles=false"
        )
        files = next((r for r in res if r["path"] == file_path), None)

        if not files:
            logging.error("Radarr can't see file.")
            return
        movie_id = None

        # Movie already in the library
        if files.get("movie"):
            logging.info(f"Movie already exists in library: {files['movie']['title']}")
            '''files["rejections"] = [] 
            files["importApproved"] = True
            import_payload = [
                                {
                                    "files": [files],
                                    "quality": files["quality"],
                                    "importMode": "move",
                                }
                            ]

            try:
                self.request("manualimport", method="POST", data=import_payload)
            except Exception as e:
                logging.error(f"Error in webhook: {e}")
                
            logging.info(f"Existing movie imported successfully via Radarr API.")
            return'''
            radarr_movie_folder = files["movie"].get("path") # e.g., "/media/Movies/The Matrix (1999)"
    
            if radarr_movie_folder and os.path.exists(radarr_movie_folder):
                file_name = os.path.basename(file_path)
                name_part, ext_part = os.path.splitext(file_name)
                
                # 2. Append an edition tag to prevent overwriting your existing file
                # This format ensures Plex / Jellyfin treats it as an additional version
                new_file_name = f"{name_part} - WEB-DL{ext_part}"
                final_destination       = os.path.join(radarr_movie_folder, new_file_name)
                
                try:
                    logging.info(f"Bypassing Radarr API. Moving secondary version to: {final_destination}")
                    shutil.move(file_path, final_destination)
                    logging.info("Multi-version file safely imported via Python.")
                    return
                except Exception as e:
                    logging.error(f"Failed to manually move file: {e}")
                    return
            else:
                logging.error("Could not locate Radarr's target library directory to manually place file.")
                
        else:
            # If not in library, search and create
            # os.path.basename(carpeta_padre)
            file_name = os.path.basename(file_path)
            logging.info(f"Searching info of '{file_name}' in Radarr...")
            search = self.search_movie(file_name)

            if not search:
                logging.error(f"Could not find matching movie metadata for {file_name}")
                return
            
            found_movie = search[0]
            title = f"{found_movie['title']} ({found_movie['year']})"
            target_dir = os.path.join(save_to, title)
            logging.info(target_dir)
            try:
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir, exist_ok=True)
                    logging.info(f"Directory created: {target_dir}")
                else:
                    logging.info(f"Directory already exists...")
            except Exception as e:
                logging.error(f"Error creating directory {target_dir}: {e}")
            # If it already exists, move the content and delete directory once empty
            for item in os.listdir(parent_dir):
                shutil.move(os.path.join(parent_dir, item), target_dir)

            new_movie = self.add_movie(
                found_movie["title"],
                found_movie["year"],
                found_movie["tmdbId"],
                save_to,
            )

            movie_id = new_movie["id"]
            new_path = os.path.join(target_dir, file_name)

            # Import from the new path
            if movie_id:
                import_payload = [
                    {
                        "path": new_path,  # <--- NEW PATH
                        "movieId": movie_id,
                        "quality": files["quality"],
                        "importMode": "move",
                    }
                ]
                self.request("manualimport", method="POST", data=import_payload)
                logging.info(f"Movie imported to Radarr from: {new_path}")
            else:
                logging.error("Failed to add new movie entry to Radarr library.")


class RadarrManager(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.radarr_api = RadarrAPI()
        letterboxd_user = os.getenv("LETTERBOXD_USER")

        if letterboxd_user:
            self.letterboxd = LetterboxdParser(letterboxd_user)

        self.root_folder = os.getenv("DOWNLOADS_DIR")

        self.radarr_channel = None
        self.default_quality_profile = 13
        self.events = {
            "Import": ("✅", "Imported movie", 0x00FF00),
            "Grab": ("🔎", "Grabbed movie", 0x5CFFBD),
            "Download": ("🎬", "Downloaded movie", 0x0099FF),
            "Rename": ("📝", "Renamed movie", 0xFFFF00),
            "MovieAdded": ("➕", "Added movie", 0x00FF00),
            "MovieDelete": ("❌", "Deleted movie", 0xFF0000),
        }

        # Webhook
        self.webhook_app = None
        self.webhook_runner = None
        self.webhook_site = None

    @commands.Cog.listener()
    async def on_ready(self):

        try:
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).send_messages:
                        self.radarr_channel = channel
        except:
            logging.error("Error starting the bot")
            logging.info("✅ RadarrManager ready!")

        await self._start_webhook_server()
        if self.letterboxd and not self.add_from_letterboxd_watchlist.is_running():
            self.add_from_letterboxd_watchlist.start()

    # ==========================================

    async def _start_webhook_server(self):

        async def radarr_webhook_handler(request):
            try:
                data = await request.json()
                event = data.get("eventType", "Unknown")
                await self.send_webhook_message(event, data)

                return web.Response(
                    text='{"status": "ok"}', content_type="application/json"
                )
            except Exception as e:
                logging.error(f"Error in webhook: {e}")
                return web.Response(
                    text='{"status": "error"}',
                    content_type="application/json",
                    status=500,
                )

        self.webhook_app = web.Application()
        self.webhook_app.router.add_post("/radarr-webhook", radarr_webhook_handler)

        self.webhook_runner = web.AppRunner(self.webhook_app)
        await self.webhook_runner.setup()
        self.webhook_site = web.TCPSite(self.webhook_runner, "0.0.0.0", 5001)
        await self.webhook_site.start()

        await self.radarr_channel.send("Radarr manager is running!")
        logging.info("✅ Webhook listening port 5001")

    async def on_cog_unload(self):
        if self.webhook_runner:
            await self.webhook_runner.cleanup()

    # ===========================================

    def add_to_queue(self, file_path):
        self.queue.add(file_path)

    async def send_webhook_message(self, event_type, data):
        if not self.radarr_channel:
            logging.warning("Radarr channel not configured")
            return False

        emoji, action, color = self.events.get(
            event_type, ("📌", str(event_type), 0x808080)
        )

        movie = data.get("movie", {})

        movie_title = (
            f"{movie.get('title', 'Unknown')} ({movie.get('year', 'Unknown')})"
        )

        embed = discord.Embed(
            title=f"{emoji} {action}", description=f"`{movie_title}`", color=color
        )

        if event_type == "Grab" and data:
            release_info = data.get("release", {})

            try:
                release = data.get("release", {})

                if isinstance(release, dict):
                    # Release name
                    release_title = release.get("releaseTitle")
                    if release_title:
                        embed.add_field(
                            name="📦 Release", value=f"`{release_title}`", inline=False
                        )

                    # Size and bitrate
                    size_bytes = release.get("size")

                    movie_id = movie.get("id")
                    runtime_minutes = None
                    if movie_id:
                        movie_details = self.radarr_api.get_movie(movie_id)
                        if movie_details:
                            runtime_minutes = movie_details.get("runtime")

                    if size_bytes:
                        size_gb = round(size_bytes / 1e9, 2)

                        # Calcular bitrate si tenemos runtime
                        size_str = f"`{size_gb} GB`"

                        if runtime_minutes and runtime_minutes > 0:
                            bitrate_mbps = (
                                (size_bytes * 8) / (runtime_minutes * 60) / 1e6
                            )
                            size_str += f" (`{bitrate_mbps:.1f} Mbps`)"

                        embed.add_field(name="💾 Size", value=size_str, inline=False)

                    quality = release.get("quality")
                    if quality:
                        embed.add_field(
                            name="📹 Quality", value=f"`{quality}`", inline=True
                        )

                    indexer = release.get("indexer")
                    if indexer:
                        embed.add_field(
                            name="🔗 Indexer", value=f"`{indexer}`", inline=True
                        )

                    release_group = release.get("releaseGroup")
                    if release_group:
                        embed.add_field(
                            name="👥 Release Group",
                            value=f"`{release_group}`",
                            inline=True,
                        )

                    custom_formats = release.get("customFormats", [])
                    if custom_formats:
                        formats_str = ", ".join(custom_formats)
                        embed.add_field(
                            name="🎯 Custom Formats",
                            value=f"`{formats_str}`",
                            inline=False,
                        )

                    """indexer_flags = release.get('indexerFlags', [])
                    if indexer_flags:
                        flags_str = ", ".join(indexer_flags)
                        embed.add_field(
                            name="🚩 Flags",
                            value=f"`{flags_str}`",
                            inline=False
                        )"""
            except Exception as e:
                logging.warning(f"Could not parse release info: {e}")

        embed.set_footer(text="Radarr")

        await self.radarr_channel.send(embed=embed)
        logging.info(f"Webhook: {event_type} - {movie_title}")
        return True

    # ============= COMMANDS =============
    @commands.command()
    async def add(
        self,
        ctx,
        input_title=commands.parameter(default=None, description="Movie title"),
        quality_profile_id: int = commands.parameter(
            default=None, description="Quality profile ID"
        ),
    ):

        if not quality_profile_id:
            quality_profile_id = self.default_quality_profile
        profiles = self.radarr_api.get_quality_profiles()
        if profiles:
            quality_profile = (
                profiles[quality_profile_id - 1]
                if 0 < quality_profile_id < len(profiles) + 1
                else None
            )
            if not quality_profile:
                await ctx.send(f"❌ No profile {quality_profile_id} found")
                return

        search = self.radarr_api.search_movie(input_title)

        if search:
            movie = search[0]
        else:
            await ctx.send(f"❌ No movie `{input_title}` found")
            return
        title = movie["title"]
        year = movie["year"]
        tmdb_id = movie["tmdbId"]

        # Check if it already exists
        if any(p["tmdbId"] == tmdb_id for p in self.radarr_api.get_all_movies()):
            await ctx.send(f"`{title} ({year})` already exists")
            return

        question = await ctx.send(
            f"Do you want to download the movie `{title} ({year})` in `{quality_profile['name']}`?"
        )
        await question.add_reaction("✅")
        await question.add_reaction("❌")

        def check(reaction, user):
            return (
                reaction.message.id == question.id
                and user == ctx.message.author
                and str(reaction.emoji) in ["✅", "❌"]
            )

        try:
            reaction, user = await self.bot.wait_for(
                "reaction_add", timeout=60.0, check=check
            )

            if str(reaction.emoji) == "✅":
                self.radarr_api.add_movie(
                    title=title,
                    year=year,
                    tmdb_id=tmdb_id,
                    root_folder=self.root_folder,
                    quality_profile=quality_profile["id"],
                    search=True,
                )

        except asyncio.TimeoutError:
            await ctx.send("You took too long to respond! Please try again.")
            return
        except Exception as e:
            logging.error(f"Error downloding: {e}")
            return

    @commands.command(name="quality_profiles")
    async def list_quality_profiles(self, ctx):

        profiles = self.radarr_api.get_quality_profiles()

        if not profiles:
            await ctx.send("❌ No profiles found")
            return

        msg = "📊 **Quality Profiles:**\n"
        for profile in profiles:
            msg += f"• ID `{profile['id']}`: {profile['name']}\n"

        await ctx.send(msg)

    def cog_unload(self):
        self.add_from_letterboxd_watchlist.cancel()

    @tasks.loop(time=datetime.time(hour=8, minute=30, tzinfo=datetime.timezone.utc))
    async def add_from_letterboxd_watchlist(self):

        if not self.letterboxd:
            return

        logging.info(f"Doing scan of {self.letterboxd.user}'s watchlist")
        new_movies =  await self.letterboxd.watchlist_new_films()
        if new_movies is None:
            logging.error(f"Can't connect to Letterboxd")
            await self.radarr_channel.send(f"Can't connect to Letterboxd")
            return
        if not new_movies: logging.info("No new movies found in watchlist")
        
        for movie_title in new_movies:
            logging.info(f"New movie in watchlist: '{movie_title}'")
            search = await asyncio.to_thread(self.radarr_api.search_movie, movie_title)
            if search:
                movie = search[0]
            else:
                await self.radarr_channel.send(f"❌ No movie `{movie_title}` found")
                await asyncio.sleep(1)
                continue

            title = movie["title"]
            year = movie["year"]
            tmdb_id = movie["tmdbId"]

            # Check if it already exists
            if any(m["tmdbId"] == tmdb_id for m in self.radarr_api.get_all_movies()):
                await self.radarr_channel.send(f"`{title} ({year})` already exists")
            else:
                await asyncio.to_thread(
                    self.radarr_api.add_movie,
                    title=title,
                    year=year,
                    tmdb_id=tmdb_id,
                    root_folder=self.root_folder,
                    quality_profile=self.default_quality_profile,
                    search=True,
                )
            self.letterboxd.add_to_cache(movie_title)
            await asyncio.sleep(1)

    @commands.command()
    async def change_time(self, ctx, hour, minutes):
        if self.add_from_letterboxd_watchlist.is_running():
            self.add_from_letterboxd_watchlist.change_interval(
                time=datetime.time(
                    hour=int(hour), minute=int(minutes), tzinfo=datetime.timezone.utc
                )
            )
            self.add_from_letterboxd_watchlist.restart() 
            await ctx.send(f"⏰ Scan time changed to " + self.add_from_letterboxd_watchlist.time[0].isoformat())

    @commands.command()
    async def downloads(self, ctx):
        try:
            embed = discord.Embed(title="⬇️ Current downloads", color=0x0099FF)
            queue_response = self.radarr_api.get_queue()
            if isinstance(queue_response, dict):
                queue = queue_response.get("records", [])
            elif isinstance(queue_response, list):
                queue = queue_response
            else:
                queue = []

                # Currently downloading
            if queue:
                downloading_list = ""
                for i, item in enumerate(queue[:10], 1):
                    if not isinstance(item, dict):
                        continue

                    movie_title = item.get("title", "Unknown")

                    # Progress
                    sizeleft = item.get("sizeleft", 0)
                    size = item.get("size", 1)

                    if size > 0:
                        progress_percent = round(((size - sizeleft) / size) * 100, 1)
                    else:
                        progress_percent = 0

                    # Timeleft
                    timeleft = item.get("timeleft")

                    time_str = f"`{str(timeleft)}`" if timeleft else "∞"
                    if timeleft:
                        movie_title = f"**{movie_title}**"
                    downloading_list += (
                        f"{i}. {movie_title}\n"
                        f"   `{progress_percent}%` | "
                        f"Time left: `{time_str}`\n"
                    )

                if len(queue) > 10:
                    downloading_list += f"\n... and {len(queue) - 10} more"

                embed.add_field(
                    name="Downloading "
                    + ("1 movie" if len(queue) == 1 else f"{len(queue)} movies"),
                    value=downloading_list,
                    inline=False,
                )
            else:
                embed.add_field(name="No active downloads", value="-", inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            logging.error(f"Error in Radarr: {e}")
            await ctx.send(f"❌ Error: {e}")

    @commands.command()
    async def status(self, ctx):
        """Radarr status with size and downloading movies"""
        try:

            all_movies = self.radarr_api.get_all_movies()
            downloaded = [m for m in all_movies if m.get("hasFile")]
            monitored = [m for m in all_movies if m.get("monitored")]

            queue_response = self.radarr_api.get_queue()
            if isinstance(queue_response, dict):
                queue = queue_response.get("records", [])
            elif isinstance(queue_response, list):
                queue = queue_response
            else:
                queue = []
            downloading_movie_ids = [item.get("movieId") for item in queue]
            missing = [
                m
                for m in monitored
                if not m.get("hasFile") and m["id"] not in downloading_movie_ids
            ]

            # Calculate total size (in bytes)
            total_size_bytes = sum(m.get("sizeOnDisk", 0) for m in downloaded)

            size_gb = round(total_size_bytes / 1e9, 2)

            # Create embed
            embed = discord.Embed(
                title="📊 Radarr Health Status",
                color=0x00FF00 if missing == [] else 0xFFAA00,
            )

            # General summary
            embed.add_field(
                name="📈 Summary",
                value=f"Total: `{len(all_movies)}`\n"
                f"Downloaded: `{len(downloaded)}`\n"
                f"Monitored: `{len(monitored)}`\n"
                f"Missing: `{len(missing)}`",
                inline=False,
            )

            # Library size
            embed.add_field(
                name="💾 Library Size",
                value=f"`{size_gb:.2f} GB` ({len(downloaded)} movies)",
                inline=False,
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
                    inline=False,
                )
            else:
                embed.add_field(
                    name="🔎 Searching for downloads", value="✅ None", inline=False
                )

            if queue:
                embed.add_field(
                    name=f"⬇️ Downloading",
                    value="1 movie" if len(queue) == 1 else f"{len(queue)} movies",
                    inline=False,
                )
            else:
                embed.add_field(
                    name=f"⬇️ Downloading", value="No active downloads", inline=False
                )

            if self.add_from_letterboxd_watchlist.is_running():
                next_time = "Next scan at " + self.add_from_letterboxd_watchlist.next_iteration.isoformat()
                embed.add_field(
                    name=f"📽 Letterboxd watcher", value=next_time, inline=False
                )
            # Footer with timestamp
            since = (
                min(all_movies, key=lambda x: x["added"])["added"][:10]
                if all_movies
                else "N/A"
            )
            embed.set_footer(text=f"Since: {since}")

            await ctx.send(embed=embed)

        except Exception as e:
            logging.error(f"Error in Radarr: {e}")
            await ctx.send(f"❌ Error: {e}")
