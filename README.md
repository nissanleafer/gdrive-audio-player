# Google Drive Audio Player

A web-based app to browse audio files from Google Drive and play them in VLC.

## Features

- Browse your Google Drive folders and shared files
- Search for audio files
- Create and save playlists
- **Stream** - Play directly from Google Drive
- **Download** - Download files for offline playback
- Favorites for quick access to folders
- Export playlists to Google Drive for mobile access

## Requirements

- Python 3.9+
- VLC media player
- Google account

## Setup

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set up Google Cloud credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the **Google Drive API**:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Drive API" and enable it
4. Configure OAuth consent screen:
   - Go to "APIs & Services" > "OAuth consent screen"
   - Choose "External" user type
   - Fill in app name and your email
   - Add scopes: `drive`, `userinfo.email`, `openid`
   - Add your email as a test user
5. Create credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app"
   - Download the JSON file
   - Rename it to `credentials.json` and place it in this folder

### 3. Run the app

```bash
python gdrive_player_ui.py
```

The app will open in your browser at http://localhost:5050

## Usage

1. **Browse**: Navigate your Google Drive folders
2. **Search**: Type to search for files, or paste a Google Drive folder URL
3. **Select**: Check the files you want to play
4. **Play**:
   - **Stream** - Plays directly (requires internet)
   - **Download** - Downloads files first (works offline)
5. **Save Playlist**: Save your selection for later
6. **Export to Drive**: Save playlist to Google Drive for mobile VLC

## File Locations

- **Playlists & Downloads**: `~/Music/GDrive Playlists/`
- **Auth tokens**: `~/.gdrive-player/token.json`

## Troubleshooting

### "Access blocked" error
Add your Google account email as a test user in the OAuth consent screen settings.

### Port 5050 in use
Edit `gdrive_player_ui.py` and change the port number at the bottom of the file.

### VLC not found
Install VLC from https://www.videolan.org/vlc/
