#!/usr/bin/env python3
"""
Google Drive Audio Player
Browse audio files in Google Drive, create playlists, and play in VLC.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path

# Google API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
APP_DIR = Path(__file__).parent
CREDENTIALS_FILE = APP_DIR / 'credentials.json'

# Store user-specific data in their home directory
USER_DATA_DIR = Path.home() / '.gdrive-player'
TOKEN_FILE = USER_DATA_DIR / 'token.json'
DOWNLOAD_DIR = USER_DATA_DIR / 'downloads'

AUDIO_MIMETYPES = [
    'audio/mpeg',
    'audio/mp3',
    'audio/wav',
    'audio/x-wav',
    'audio/ogg',
    'audio/flac',
    'audio/aac',
    'audio/m4a',
    'audio/x-m4a',
]


def authenticate():
    """Authenticate with Google Drive API."""
    creds = None

    # Ensure user data directory exists
    USER_DATA_DIR.mkdir(exist_ok=True)

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print("\n❌ Missing credentials.json file!")
                print("\nTo set up Google Drive API access:")
                print("1. Go to https://console.cloud.google.com/")
                print("2. Create a new project (or select existing)")
                print("3. Enable the Google Drive API")
                print("4. Go to Credentials → Create Credentials → OAuth client ID")
                print("5. Choose 'Desktop app' as application type")
                print("6. Download the JSON and save it as 'credentials.json' in this folder")
                print(f"\n   Save to: {CREDENTIALS_FILE}")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())

    return build('drive', 'v3', credentials=creds)


def list_audio_files(service, folder_id=None):
    """List audio files in Google Drive."""
    mime_query = " or ".join([f"mimeType='{m}'" for m in AUDIO_MIMETYPES])
    query = f"({mime_query}) and trashed=false"

    if folder_id:
        query += f" and '{folder_id}' in parents"

    results = service.files().list(
        q=query,
        pageSize=100,
        fields="files(id, name, mimeType, size, parents)",
        orderBy="name"
    ).execute()

    return results.get('files', [])


def list_folders(service, parent_id=None):
    """List folders in Google Drive."""
    query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(
        q=query,
        pageSize=50,
        fields="files(id, name)",
        orderBy="name"
    ).execute()

    return results.get('files', [])


def format_size(size_bytes):
    """Format file size for display."""
    if not size_bytes:
        return "?"
    size = int(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def browse_and_select(service):
    """Interactive browser for selecting audio files."""
    selected_files = []
    current_folder = None
    folder_stack = []  # (id, name) tuples

    while True:
        print("\n" + "=" * 60)

        # Show current path
        if folder_stack:
            path = " / ".join([f[1] for f in folder_stack])
            print(f"📁 {path}")
        else:
            print("📁 My Drive (root)")

        print("=" * 60)

        # Get folders and files
        folders = list_folders(service, current_folder)
        files = list_audio_files(service, current_folder)

        # Display folders
        idx = 1
        folder_indices = {}
        if folders:
            print("\n📂 Folders:")
            for folder in folders:
                print(f"  [{idx}] 📁 {folder['name']}")
                folder_indices[idx] = folder
                idx += 1

        # Display audio files
        file_indices = {}
        if files:
            print("\n🎵 Audio Files:")
            for f in files:
                size = format_size(f.get('size'))
                selected_mark = "✓" if f['id'] in [s['id'] for s in selected_files] else " "
                print(f"  [{idx}] {selected_mark} {f['name']} ({size})")
                file_indices[idx] = f
                idx += 1

        if not folders and not files:
            print("\n  (empty)")

        # Show selected count
        print(f"\n📋 Selected: {len(selected_files)} files")

        # Navigation options
        print("\nCommands:")
        print("  [number]  - Enter folder or toggle file selection")
        print("  [a]       - Select all audio files in current folder")
        print("  [c]       - Clear all selections")
        if folder_stack:
            print("  [b]       - Go back to parent folder")
        print("  [d]       - Done selecting → Play")
        print("  [q]       - Quit")

        choice = input("\n> ").strip().lower()

        if choice == 'q':
            print("Goodbye!")
            sys.exit(0)

        elif choice == 'b' and folder_stack:
            folder_stack.pop()
            current_folder = folder_stack[-1][0] if folder_stack else None

        elif choice == 'a':
            for f in files:
                if f['id'] not in [s['id'] for s in selected_files]:
                    selected_files.append(f)
            print(f"Added {len(files)} files to selection")

        elif choice == 'c':
            selected_files.clear()
            print("Selection cleared")

        elif choice == 'd':
            if not selected_files:
                print("No files selected!")
                continue
            return selected_files

        elif choice.isdigit():
            num = int(choice)
            if num in folder_indices:
                folder = folder_indices[num]
                folder_stack.append((folder['id'], folder['name']))
                current_folder = folder['id']
            elif num in file_indices:
                f = file_indices[num]
                # Toggle selection
                existing = [s for s in selected_files if s['id'] == f['id']]
                if existing:
                    selected_files.remove(existing[0])
                    print(f"Removed: {f['name']}")
                else:
                    selected_files.append(f)
                    print(f"Added: {f['name']}")


def download_file(service, file_info, dest_dir):
    """Download a file from Google Drive."""
    dest_path = dest_dir / file_info['name']

    if dest_path.exists():
        print(f"  ⏭️  Skipping (exists): {file_info['name']}")
        return dest_path

    print(f"  ⬇️  Downloading: {file_info['name']}...", end='', flush=True)

    request = service.files().get_media(fileId=file_info['id'])

    with open(dest_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

    print(" Done!")
    return dest_path


def get_stream_url(file_id):
    """Get a streamable URL for a Google Drive file."""
    # This URL format allows direct streaming for files with appropriate sharing
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def create_playlist(files, is_stream=False, local_paths=None):
    """Create an M3U playlist file."""
    playlist_path = Path(tempfile.gettempdir()) / "gdrive_playlist.m3u"

    with open(playlist_path, 'w') as f:
        f.write("#EXTM3U\n")
        for i, file_info in enumerate(files):
            f.write(f"#EXTINF:-1,{file_info['name']}\n")
            if is_stream:
                f.write(f"{get_stream_url(file_info['id'])}\n")
            else:
                f.write(f"{local_paths[i]}\n")

    return playlist_path


def play_with_vlc(playlist_path):
    """Open VLC with the playlist on repeat."""
    vlc_paths = [
        '/Applications/VLC.app/Contents/MacOS/VLC',
        '/usr/bin/vlc',
        'vlc'
    ]

    vlc_cmd = None
    for path in vlc_paths:
        if path == 'vlc' or os.path.exists(path):
            vlc_cmd = path
            break

    if not vlc_cmd:
        print("\n❌ VLC not found!")
        print("Please install VLC from https://www.videolan.org/vlc/")
        print(f"\nPlaylist saved to: {playlist_path}")
        return

    print(f"\n🎶 Opening VLC with playlist (repeat mode)...")
    subprocess.Popen([vlc_cmd, '--loop', str(playlist_path)])


def main():
    print("=" * 60)
    print("   🎵 Google Drive Audio Player")
    print("=" * 60)

    # Authenticate
    print("\n🔐 Authenticating with Google Drive...")
    service = authenticate()
    print("✅ Connected!")

    # Browse and select files
    selected_files = browse_and_select(service)

    print(f"\n📋 Selected {len(selected_files)} files:")
    for f in selected_files:
        print(f"   • {f['name']}")

    # Choose playback mode
    print("\n🎧 Playback mode:")
    print("  [1] Stream directly (requires internet)")
    print("  [2] Download first (works offline)")

    while True:
        choice = input("\n> ").strip()
        if choice in ['1', '2']:
            break
        print("Please enter 1 or 2")

    if choice == '2':
        # Download mode
        DOWNLOAD_DIR.mkdir(exist_ok=True)
        print(f"\n⬇️  Downloading to: {DOWNLOAD_DIR}")

        local_paths = []
        for f in selected_files:
            path = download_file(service, f, DOWNLOAD_DIR)
            local_paths.append(path)

        playlist = create_playlist(selected_files, is_stream=False, local_paths=local_paths)
    else:
        # Stream mode
        print("\n⚠️  Note: Streaming requires files to be accessible.")
        print("   If playback fails, try downloading instead or check sharing settings.")
        playlist = create_playlist(selected_files, is_stream=True)

    # Play with VLC
    play_with_vlc(playlist)
    print("\n✅ Enjoy your music! Press Ctrl+C to exit.")


if __name__ == '__main__':
    main()
