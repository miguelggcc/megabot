import discord
from discord.ext import commands
import os
import shlex
import asyncio
import logging
import math
import urllib.request
import urllib.parse
import json
import shutil
from requestlistener import RequestListener
from transferlistener import TransferListener
from mega import (MegaApi, MegaNode, MegaTransfer)

BOT_TOKEN = os.getenv("TOKEN")
API_KEY = os.getenv("API_KEY")
SIZE_NAME = ("B", "KB", "MB", "GB", "TB", "PB")

logging.basicConfig(level=logging.INFO,
                    # filename='runner.log',
                    format='%(levelname)s\t%(asctime)s %(message)s')


            
class MegaSession():

    def __init__(self, api, listener):
        self._api = api
        self._listener = listener
        self.backlog = []
        self.current_dls = []
        os.umask(0o0002)
    def ls(self, path, files, depth=0):

        if path == None:
            return 'INFO: Not logged in'
        if path.getType() == MegaNode.TYPE_FILE:
            size = f'\u001b[0;41m{convert_size(path.getSize())}\u001b[0;0m'
            files.append({"name": '\t'*depth+path.getName() +
                         '\t'+size, "handle": path.getHandle()})
        else:
            name = '\u001b[0;34m' + '\t'*depth+'./' + \
                path.getName()+'\t' + '\u001b[0;0m'
            files.append({"name": name, "handle": path.getHandle()})
            children = self._api.getChildren(path)

            for i in range(children.size()):
                self.ls(children.get(i), files, depth+1)

    def cd(self, arg):
        """Usage: cd [path]"""
        args = arg.split()
        if len(args) > 1:
            print(self.cd.__doc__)
            return
        if self._listener.cwd == None:
            logging.info('Not logged in')
            return
        if len(args) == 0:
            self._listener.cwd = self._api.getRootNode()
            return

        node = self._api.getNodeByPath(args[0], self._listener.cwd)
        if node == None:
            logging.error('{}: No such file or directory'.format(args[0]))
            return
        if node.getType() == MegaNode.TYPE_FILE:
            logging.error('{}: Not a directory'.format(args[0]))
            return
        self._listener.cwd = node

    def download(self, node, save_to):
        """Usage: get remotefile"""

        if self._listener.cwd == None:
            logging.info('Not logged in')
            return

        transfer_listener = TransferListener()
        #auto_import_radarr(save_to+'/'+node.getName(),'/downloads/films')
        
        # node = self._api.authorizeNode(node)
        if node == None:
            logging.error('Node not found')
            return
        # , MegaTransfer.COLLISION_CHECK_FINGERPRINT, MegaTransfer.COLLISION_RESOLUTION_NEW_WITH_N)
        # pass it through the configuration API handler.
        logging.info("--- AVAILABLE METHODS ---")
        logging.info([attr for attr in dir(self._api) if "connection" in attr.lower() or "thread" in attr.lower() or "download" in attr.lower()])
        self._api.setMaxConnections(6)
        self.current_dls.append(transfer_listener)
        self._api.startDownload(
            node, save_to+'/'+node.getName(), transfer_listener)
        transfer_listener = None

    def pwd(self):
        """Usage: pwd"""
        if self._listener.cwd == None:
            logging.info('Not logged in')
            return

        return self._listener.cwd.getName()

    def wait(self):
        self._listener.event.wait()

    def quit(self):
        del self._listener
        del self._api
        logging.info('Bye!')
        return True


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, SIZE_NAME[i])

def expand_ranges(msg):
    output = set()
    for item in msg.split(','):
        if '-' in item:
            start, end = map(int, item.split('-'))
            output.update(range(start, end + 1))
        else:
            output.add(int(item))
    return output
                   
class MegaBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mega = None

    @commands.command()
    @commands.is_owner()  # Restrict this command to the bot owner
    async def quit(self, ctx):
        logging.info("Shutting down bot...")
        await ctx.send('Shutting down...')
        if self.mega:
            self.mega.quit()
        await self.bot.close()

    def status_text(self):
        return 'Current downloads:\n```ansi\n' + \
            os.linesep.join([tl.getStatus()
                             for tl in self.mega.current_dls])+'\n```'

    async def update_status_task(self, status_message):
        period = 1
        while True:
            if any([dl.over_quota for dl in self.mega.current_dls]):
                period = min(2*period,256)
                await status_message.edit(content=self.status_text()+f'Retrying connection in {period} s')
                await asyncio.sleep(period)
                continue
            if any([not dl.is_finished for dl in self.mega.current_dls]):
                await status_message.edit(content=self.status_text())
                await asyncio.sleep(1)  # Update every second
            else:
                break

    async def pause_button_task(self, ctx, status_message):
        def check(reaction, user): return reaction.message.id == status_message.id and user == ctx.message.author and str(
            reaction.emoji) in ['▶', '⏸']
        pause = False
        while True:
            reaction, user = await bot.wait_for('reaction_add', check=check)
            pause = not pause
            await status_message.clear_reactions()
            self.mega._api.pauseTransfers(pause)
            if pause:
                await status_message.add_reaction('▶')
            else:
                await status_message.add_reaction('⏸')

    async def status_message_task(self, ctx):
        status_message = await ctx.send("Starting downloads...")
        await status_message.add_reaction('⏸')
        update_status_task = asyncio.create_task(
            self.update_status_task(status_message))
        pause_button_task = asyncio.create_task(
            self.pause_button_task(ctx, status_message))
        await update_status_task
        pause_button_task.cancel()
        await status_message.edit(content=self.status_text())
        await status_message.clear_reactions()
        if self.mega:
            self.mega.current_dls.clear()

    @commands.command()
    async def ping(self, ctx):
        """
        Check the availability of the bot
        """
        await ctx.send(f"Pong!      Latency:  {round(self.bot.latency * 1000)}ms")

    @commands.command()
    async def dl(self, ctx,
                 link=commands.parameter(
                     default=None, description="Mega link"), *,
                 flags: str = commands.parameter(default='', description="Optional flags: -dir, -f, -s")):
        """
        Download file or files from Mega.nz 
        Flags:
            -dir: Add cutstom directory,
            -f: Download to \\films\\dir,
            -s: Download to \\shows\\dir
        """
        if not link:  # or not link.startswith('https://mega.nz/'):
            await ctx.send('❌ Invalid Mega Link')
            return
        try:
            split_flags = shlex.split(flags)
        except:
            await ctx.send("Command is not correct")
            return
        if '-f' in split_flags:
            dir = '/downloads/films.tmp'
        elif '-s' in split_flags:
            dir = '/downloads/shows.tmp'
        else:
            dir = '/downloads'
        olddir = dir
        if '-dir' in split_flags:
            dir += '/'+split_flags[split_flags.index('-dir')+1].strip()

        api = MegaApi(API_KEY, None, None, 'megabot session')
        listener = RequestListener()
        self.mega = MegaSession(api,  listener)
        if any(f in link for f in ["folder", "#F!"]):
            api.loginToFolder(link.strip(), listener)
        else:
            api.getPublicNode(link.strip(), listener)
        self.mega.wait()
        api = None
        listener = None
        if any(f in link for f in ["folder", "#F!"]):
            await ctx.send(f"Opened  folder `{self.mega.pwd()}`")
            try:
                files = []
                self.mega.ls(self.mega._listener.cwd, files)
            except:
                await ctx.send("Couldn't open `" + link + '`')
                self.mega = None
                return
            
            self.mega._api.authorizeNode(self.mega._listener.cwd)
            
            while True:
                filelist = '```ansi'+os.linesep + \
                    os.linesep.join(str(i)+n["name"]
                                    for i, n in enumerate(files)) + '```'
                await ctx.send(filelist)
                await ctx.send(f'Choose files to download in `{dir}`')
                try:
                    def check(
                        m): return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id
                    msg = await bot.wait_for('message', timeout=60.0, check=check)
                    # self.mega._api.authorizeNode(self.mega._listener.cwd)
                except asyncio.TimeoutError:
                    await ctx.send('You took too long to respond! Please try again.')
                    return
                if msg.content.startswith("-dir"):
                        dir = olddir + '/' + shlex.split(msg.content)[1]
                        continue
                 
                try:
                    os.makedirs(dir, exist_ok=True)
                    break
                except:
                    await ctx.send(f"`{dir}` is not a correct directory")
                    return

            for n in expand_ranges(msg.content):
                node = self.mega._api.getNodeByHandle(files[n]["handle"])
                node = self.mega._api.authorizeNode(node)

                self.mega.download(node, dir)
                # If this is the first download, start the status updates
                if len(self.mega.current_dls) == 1:
                    asyncio.create_task(self.status_message_task(ctx))
        else:

            files = []
            self.mega.ls(self.mega._listener.cwd, files)

            if len(files) < 1:
                await ctx.send('❌ Error: No files found')

            question = await ctx.send("Found file:\n```ansi\n " + files[0]["name"] +
                                      f"``` Do you want to download in `{dir}` ?")
            await question.add_reaction('✅')
            await question.add_reaction('❌')

            def check(reaction, user): return reaction.message.id == question.id and user == ctx.message.author and str(
                reaction.emoji) in ['✅', '❌']
            try:
                reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
                match str(reaction.emoji):

                    case '✅':
                        try:
                            os.makedirs(dir, exist_ok=True)
                        except:
                            await ctx.send(f"`{dir}` is not a correct directory")
                            return
                        self.mega.download(self.mega._listener.cwd, dir)
                        # If this is the first download, start the status updates
                        if len(self.mega.current_dls) == 1:
                            asyncio.create_task(self.status_message_task(ctx))

                    case _:
                        await self.cancel(ctx)
            except asyncio.TimeoutError:
                await ctx.send('You took too long to respond! Please try again.')
                return
            except Exception as e:
                logging.error(f"Error downloding: {e}")
                return

    @commands.command()
    async def ls(self, ctx):
        """
        List all files in current session
        """

        if self.mega != None:
            files = []
            self.mega.ls(self.mega._listener.cwd, files)
            output = '```ansi'+os.linesep + \
                os.linesep.join(str(i)+' '+n["name"]
                                for i, n in enumerate(files)) + '```'
            await ctx.send(output)
        else:
            await ctx.send("Start a session")
            return
    
    @commands.command()
    async def cancel(self, ctx):
        """
        Cancel and close current session
        """
        if self.mega:
            self.mega._api.cancelTransfers(MegaTransfer.TYPE_DOWNLOAD)
            await ctx.send(f"Cancelling the download of `{self.mega.pwd()}`")
            self.mega.current_dls.clear()
            await asyncio.sleep(1)
            self.mega = None
        else:
            await ctx.send("No session open")


bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())


@bot.event
async def on_ready():
    logging.info("Starting bot...")
    try:
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    await channel.send("Megabot is running")
    except:
        logging.error("Error starting the bot")


async def main():
    async with bot:
        await bot.add_cog(MegaBot(bot))
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
