# Mega Downloader Discord Bot

This Discord bot makes it possible to download files or folders from mega.nz using [**Mega SDK**](https://github.com/meganz/sdk). It supports single-file downloads and lets users select specific files from folder links for batch downloads. The bot is designed for Docker deployment.

---

## Installation and Deployment

**Set Up Environment Variables**:
   - Create a `.env` file in the project directory.
   - Add your Discord bot token, Mega API key and desired download directory to the `.env` file:

     ```
     TOKEN=your_discord_bot_token
     API_KEY=your_mega_api_key
     DOWNLOADS_DIR=downloads_directory
     ```

**Build the Docker Image**:
   ```bash
   docker-compose up --build
   ```
---

## Usage

1. **Invite the Bot to Your Server**:
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications).
   - Generate an OAuth2 URL for your bot and invite it to your server.

2. **Commands**:
   - **`!dl [mega link]`**: Download a single file from the link. If the link is folder, the user can choose which to download.
   - **`!ls`**: List files from current session
   - **`!cancel`**: Close current session

---

## License

This project is licensed under the MIT License. 
- [discord.py](https://discordpy.readthedocs.io/)
