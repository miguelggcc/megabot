# Mega Downloader Discord Bot

This Discord bot makes it possible to download files or folders from mega.nz using [**Mega SDK**](https://github.com/meganz/sdk). It supports single-file downloads as well as batch downloads of specified items from folder links. The bot is designed for Docker deployment.
<p align="center">
<img src="https://github.com/user-attachments/assets/9f72abf6-8c3b-4f6f-b38f-e1bfbf38550f" width="70%"/>
</p>
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
   - **`!dl [mega link]`**: Download a single file from the link. If the link is for a folder, the user can choose which to download.
   - **`!ls`**: List files from current session.
   - **`!cancel`**: Close current session.

---

## License

This project is licensed under the MIT License. 
- [discord.py](https://discordpy.readthedocs.io/)
