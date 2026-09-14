#!/usr/bin/env python3
"""
Google Drive Audio Player - Web Version with Multi-User OAuth
"""

import os
import sys
import json
import secrets
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, redirect, session, url_for
from functools import wraps

# Google API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

VERSION = "2.0.0"

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

APP_DIR = Path(__file__).parent
CREDENTIALS_FILE = APP_DIR / 'credentials_web.json'
TOKENS_DIR = APP_DIR / 'tokens'

AUDIO_MIMETYPES = [
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/ogg', 'audio/flac', 'audio/aac', 'audio/m4a', 'audio/x-m4a',
]

app = Flask(__name__, static_folder='static', static_url_path='/static')

# Use persistent secret key (create once, reuse)
SECRET_KEY_FILE = APP_DIR / '.secret_key'
if SECRET_KEY_FILE.exists():
    app.secret_key = SECRET_KEY_FILE.read_text().strip()
else:
    app.secret_key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(app.secret_key)
    os.chmod(SECRET_KEY_FILE, 0o600)  # Restrict permissions

# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# Ensure tokens directory exists
TOKENS_DIR.mkdir(exist_ok=True)

# Playlists directory
PLAYLISTS_DIR = APP_DIR / 'playlists'
PLAYLISTS_DIR.mkdir(exist_ok=True)

def get_user_playlists_file():
    """Get the playlists file for the current user."""
    if 'user_email' not in session:
        return None
    # Use email hash for filename
    import hashlib
    email_hash = hashlib.md5(session['user_email'].encode()).hexdigest()
    return PLAYLISTS_DIR / f'{email_hash}.json'

def load_user_playlists():
    """Load playlists for current user."""
    pfile = get_user_playlists_file()
    if pfile and pfile.exists():
        return json.loads(pfile.read_text())
    return {}

def save_user_playlists(playlists):
    """Save playlists for current user."""
    pfile = get_user_playlists_file()
    if pfile:
        pfile.write_text(json.dumps(playlists, indent=2))

def get_user_favorites_file():
    """Get the favorites file for the current user."""
    if 'user_email' not in session:
        return None
    import hashlib
    email_hash = hashlib.md5(session['user_email'].encode()).hexdigest()
    return PLAYLISTS_DIR / f'{email_hash}_favorites.json'

def load_user_favorites():
    """Load favorites for current user."""
    ffile = get_user_favorites_file()
    if ffile and ffile.exists():
        return json.loads(ffile.read_text())
    return []

def save_user_favorites(favorites):
    """Save favorites for current user."""
    ffile = get_user_favorites_file()
    if ffile:
        ffile.write_text(json.dumps(favorites, indent=2))

# Stream tokens for VLC/external players (token -> credentials data)
import time
STREAM_TOKENS = {}
STREAM_TOKENS_FILE = APP_DIR / '.stream_tokens.json'

def load_stream_tokens():
    """Load stream tokens from file."""
    global STREAM_TOKENS
    if STREAM_TOKENS_FILE.exists():
        try:
            STREAM_TOKENS = json.loads(STREAM_TOKENS_FILE.read_text())
            # Clean expired tokens
            now = time.time()
            STREAM_TOKENS = {k: v for k, v in STREAM_TOKENS.items() if v.get('expires', 0) > now}
        except:
            STREAM_TOKENS = {}

def save_stream_tokens():
    """Save stream tokens to file."""
    STREAM_TOKENS_FILE.write_text(json.dumps(STREAM_TOKENS))
    os.chmod(STREAM_TOKENS_FILE, 0o600)  # Restrict permissions

def create_stream_token(credentials_data):
    """Create a token for streaming without session auth (valid for 24 hours)."""
    token = secrets.token_urlsafe(32)
    STREAM_TOKENS[token] = {
        'credentials': credentials_data,
        'expires': time.time() + 86400  # 24 hours
    }
    save_stream_tokens()
    return token

def get_credentials_from_token(token):
    """Get credentials from a stream token."""
    load_stream_tokens()
    if token in STREAM_TOKENS:
        data = STREAM_TOKENS[token]
        if data.get('expires', 0) > time.time():
            return data.get('credentials')
    return None

# Load tokens on startup
load_stream_tokens()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_csrf_token():
    """Get or create CSRF token for current session."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def csrf_protected(f):
    """Decorator to require valid CSRF token for POST/DELETE requests."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method in ['POST', 'DELETE']:
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            if not token or token != session.get('csrf_token'):
                return jsonify({'error': 'Invalid CSRF token'}), 403
        return f(*args, **kwargs)
    return decorated_function

def get_drive_service():
    """Get Drive service for current user."""
    if 'credentials' not in session:
        return None

    creds_data = session['credentials']
    creds = Credentials(
        token=creds_data['token'],
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data['token_uri'],
        client_id=creds_data['client_id'],
        client_secret=creds_data['client_secret'],
        scopes=creds_data['scopes']
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        session['credentials'] = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': list(creds.scopes)
        }

    return build('drive', 'v3', credentials=creds)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Google Drive Audio Player</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png">
    <link rel="apple-touch-icon" href="/static/icon-128.png">
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a2e;
            color: #eee;
        }
        h1 { color: #fff; margin-bottom: 5px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        .user-info {
            background: #16213e;
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 0.9em;
            color: #aaa;
        }
        .user-info a { color: #4285f4; margin-left: 10px; text-decoration: none; }
        .subtitle { color: #888; margin-bottom: 10px; }
        .search-box {
            width: 100%;
            padding: 12px 15px;
            font-size: 16px;
            border: 2px solid #16213e;
            border-radius: 8px;
            margin-bottom: 15px;
            background: #16213e;
            color: #fff;
        }
        .search-box:focus { outline: none; border-color: #4285f4; }
        .file-list {
            background: #16213e;
            border-radius: 8px;
            max-height: 400px;
            overflow-y: auto;
        }
        .file-item {
            padding: 12px 15px;
            border-bottom: 1px solid #1a1a2e;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .file-item:hover { background: #1a1a2e; }
        .file-item:last-child { border-bottom: none; }
        .file-icon { font-size: 1.2em; }
        .file-name { flex: 1; min-width: 0; }
        .file-name span { display: block; }
        .file-name .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .file-name .meta { font-size: 0.8em; color: #888; }
        .folder { color: #ffd700; }
        .audio { color: #4285f4; }
        .btn {
            background: #4285f4;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        .btn:hover { background: #3367d6; }
        .btn-play { background: #34a853; }
        .btn-play:hover { background: #2d8f47; }
        .playlist {
            background: #16213e;
            border-radius: 8px;
            padding: 15px;
            margin-top: 20px;
        }
        .playlist h3 { margin-top: 0; color: #fff; }
        .playlist-item {
            padding: 8px;
            background: #1a1a2e;
            margin: 5px 0;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .playlist-item button {
            background: #e74c3c;
            border: none;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            cursor: pointer;
        }
        .audio-player {
            width: 100%;
            margin-top: 15px;
        }
        .now-playing {
            background: #34a853;
            color: white;
            padding: 10px 15px;
            border-radius: 8px;
            margin-top: 15px;
            text-align: center;
        }
        .breadcrumb {
            background: #16213e;
            padding: 10px 15px;
            border-radius: 8px;
            margin-bottom: 15px;
        }
        .breadcrumb a { color: #4285f4; text-decoration: none; }
        .breadcrumb a:hover { text-decoration: underline; }
        .loading { text-align: center; padding: 40px; color: #888; }

        /* Mobile responsive styles */
        @media (max-width: 600px) {
            body { padding: 10px; }
            .header { flex-direction: column; align-items: flex-start; }
            .header > div:first-child { width: 100%; }
            .header > div:first-child img { width: 48px; height: 48px; }
            .header > div:first-child h1 { font-size: 1.3em; }
            .user-info { width: 100%; text-align: center; margin-top: 10px; }
            .file-item { padding: 10px; gap: 8px; }
            .file-item .btn { padding: 8px 10px; font-size: 12px; }
            .file-name .name { font-size: 0.95em; }
            .file-name .meta { font-size: 0.75em; }
            .btn { padding: 8px 12px; font-size: 13px; }
            .playlist { padding: 10px; }
            .playlist h3 { font-size: 1em; }
            .playlist > div:first-child { flex-direction: column; gap: 10px; }
            .playlist > div:first-child > div { width: 100%; display: flex; }
            .playlist > div:first-child input { flex: 1; }
            .playlist-item { padding: 10px 8px; font-size: 0.9em; }
            .playlist-item span { word-break: break-word; }
            #nowPlaying > div:nth-child(2) { flex-wrap: wrap; justify-content: center; }
            #nowPlaying > div:nth-child(2) .btn { padding: 8px 12px; margin: 2px; }
            .breadcrumb { font-size: 0.9em; padding: 8px 12px; overflow-x: auto; white-space: nowrap; }
            #savedPlaylists { margin-top: 10px; }
        }

        /* Touch-friendly buttons */
        @media (hover: none) {
            .btn { min-height: 44px; min-width: 44px; }
            .file-item:hover { background: transparent; }
            .file-item:active { background: #1a1a2e; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div style="display: flex; align-items: center; gap: 15px;">
            <img src="/static/icon-128.png" alt="GDrive Player" style="width: 64px; height: 64px;">
            <div>
                <h1 style="margin: 0;">Google Drive Audio Player</h1>
                <div class="subtitle">v{{ version }}</div>
            </div>
        </div>
        <div class="user-info">
            {{ user_email }}
            <a href="/logout">Logout</a>
        </div>
    </div>

    <input type="text" class="search-box" id="search" placeholder="Search for audio files..." oninput="searchFiles(this.value)">

    <div style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
        <button class="btn" id="btnMyDrive" onclick="switchToMyDrive()" style="background: #34a853;">📁 My Drive</button>
        <button class="btn" id="btnShared" onclick="switchToShared()">🔗 Shared with me</button>
        <button class="btn" onclick="toggleFavorites()">⭐ Favorites</button>
        <button class="btn" onclick="toggleGoToFolder()">🔗 Go to Folder</button>
        <button class="btn" onclick="addCurrentToFavorites()" id="btnAddFav" style="display:none;">➕ Add to Favorites</button>
    </div>

    <div id="goToFolderPanel" style="display: none; background: #16213e; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
        <h3 style="margin: 0 0 10px 0;">🔗 Go to Folder</h3>
        <p style="color: #888; font-size: 0.9em; margin: 0 0 10px 0;">Paste a Google Drive folder URL or folder ID:</p>
        <div style="display: flex; gap: 10px;">
            <input type="text" id="folderUrlInput" placeholder="https://drive.google.com/drive/folders/... or folder ID" style="flex: 1; padding: 10px; border-radius: 4px; border: 1px solid #333; background: #1a1a2e; color: #fff;">
            <button class="btn" onclick="goToFolderUrl()">Go</button>
        </div>
    </div>

    <div id="favoritesPanel" style="display: none; background: #16213e; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
        <h3 style="margin: 0 0 10px 0;">⭐ Favorite Folders</h3>
        <div id="favoritesList"><div class="loading">No favorites yet</div></div>
    </div>

    <div class="breadcrumb" id="breadcrumb">
        <a href="#" onclick="loadFolder('root'); return false;">My Drive</a>
    </div>

    <div class="file-list" id="fileList">
        <div class="loading">Loading...</div>
    </div>

    <div class="playlist" id="playlist">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h3 style="margin: 0;">🎶 Current Playlist (<span id="playlistCount">0</span>)</h3>
            <div style="display: flex; gap: 5px;">
                <input type="text" id="playlistName" placeholder="Playlist name..." style="padding: 6px 10px; border-radius: 4px; border: 1px solid #333; background: #1a1a2e; color: #fff; width: 150px;">
                <button class="btn" onclick="savePlaylist()" style="padding: 6px 12px;">💾 Save</button>
            </div>
        </div>
        <div id="playlistItems"></div>
        <div style="margin-top: 15px; display: flex; gap: 10px; flex-wrap: wrap;">
            <button class="btn btn-play" onclick="playPlaylist()">▶️ Play All</button>
            <button class="btn" onclick="downloadPlaylist()">📥 M3U</button>
            <button class="btn" onclick="downloadPublicPlaylist()">🌐 Public M3U</button>
            <button class="btn" onclick="downloadAllFiles()">⬇️ Download All</button>
            <button class="btn" onclick="downloadPublicZip(event)">📦 Public ZIP</button>
            <button class="btn" onclick="clearPlaylist()">🗑️ Clear</button>
        </div>
    </div>

    <div class="playlist" id="savedPlaylists" style="margin-top: 15px;">
        <h3 style="margin: 0 0 10px 0;">📚 Saved Playlists</h3>
        <div id="savedPlaylistItems"><div class="loading">Loading...</div></div>
    </div>

    <div id="nowPlaying" style="display: none;" class="now-playing">
        <div id="nowPlayingText">Now Playing: </div>
        <div style="display: flex; justify-content: center; gap: 10px; margin: 10px 0;">
            <button class="btn" onclick="prevTrack()" title="Previous track">⏮️</button>
            <button class="btn" onclick="rewind()" title="Rewind 10s">⏪ 10s</button>
            <button class="btn" onclick="forward()" title="Forward 10s">10s ⏩</button>
            <button class="btn" onclick="nextTrack()" title="Next track">⏭️</button>
        </div>
        <audio id="audioPlayer" class="audio-player" controls></audio>
    </div>

    <script>
        let currentFolder = 'root';
        let playlist = [];
        let folderStack = [{id: 'root', name: 'My Drive'}];
        let currentTrackIndex = 0;
        let currentMode = 'mydrive';  // 'mydrive' or 'shared'
        let favorites = [];
        const csrfToken = '{{ csrf_token }}';

        // Helper for fetch with CSRF token
        function fetchWithCsrf(url, options = {}) {
            options.headers = options.headers || {};
            options.headers['X-CSRF-Token'] = csrfToken;
            return fetch(url, options);
        }

        // HTML escape function to prevent XSS
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Escape for use in JS string literals within HTML attributes
        function escapeJs(text) {
            return text.replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\\\'").replace(/"/g, '\\\\"');
        }

        function loadFolder(folderId, folderName) {
            currentFolder = folderId;
            if (folderName && folderId !== 'root') {
                const idx = folderStack.findIndex(f => f.id === folderId);
                if (idx >= 0) {
                    folderStack = folderStack.slice(0, idx + 1);
                } else {
                    folderStack.push({id: folderId, name: folderName});
                }
            } else if (folderId === 'root') {
                folderStack = [{id: 'root', name: 'My Drive'}];
            }
            updateBreadcrumb();

            document.getElementById('fileList').innerHTML = '<div class="loading">Loading...</div>';
            fetch('/api/files?folder=' + folderId)
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        document.getElementById('fileList').innerHTML = '<div class="loading" style="color:#e74c3c;">Error: ' + data.error + '</div>';
                    } else {
                        renderFiles(data.files || []);
                    }
                })
                .catch(err => {
                    document.getElementById('fileList').innerHTML = '<div class="loading" style="color:#e74c3c;">Error: ' + err + '</div>';
                });
        }

        function updateBreadcrumb() {
            const bc = document.getElementById('breadcrumb');
            bc.innerHTML = folderStack.map((f, i) =>
                `<a href="#" onclick="loadFolder('${escapeJs(f.id)}'); return false;">${escapeHtml(f.name)}</a>`
            ).join(' / ');
        }

        function searchFiles(query) {
            if (query.length < 2) {
                loadFolder(currentFolder);
                return;
            }
            document.getElementById('fileList').innerHTML = '<div class="loading">Searching...</div>';
            let searchUrl = '/api/search?q=' + encodeURIComponent(query);
            if (currentFolder && currentFolder !== 'root' && currentFolder !== 'shared') {
                searchUrl += '&folder=' + encodeURIComponent(currentFolder);
            }
            fetch(searchUrl)
                .then(r => r.json())
                .then(data => {
                    renderFiles(data.files || []);
                });
        }

        function formatSize(bytes) {
            if (!bytes) return '';
            bytes = parseInt(bytes);
            const units = ['B', 'KB', 'MB', 'GB'];
            let i = 0;
            while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
            return bytes.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
        }

        function formatDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            return d.toLocaleDateString();
        }

        function renderFiles(files) {
            const list = document.getElementById('fileList');
            if (files.length === 0) {
                list.innerHTML = '<div class="loading">No files found</div>';
                return;
            }
            list.innerHTML = files.map(f => {
                const isFolder = f.mimeType === 'application/vnd.google-apps.folder';
                const isAudio = f.mimeType && f.mimeType.startsWith('audio/');
                const meta = isAudio ? [formatSize(f.size), formatDate(f.modifiedTime)].filter(x => x).join(' • ') : '';
                const safeName = escapeHtml(f.name);
                const safeNameJs = escapeJs(f.name);
                const safeId = escapeJs(f.id);
                return `<div class="file-item" onclick="${isFolder ? `loadFolder('${safeId}', '${safeNameJs}')` : isAudio ? `addToPlaylist('${safeId}', '${safeNameJs}')` : ''}">
                    <span class="file-icon ${isFolder ? 'folder' : isAudio ? 'audio' : ''}">${isFolder ? '📁' : isAudio ? '🎵' : '📄'}</span>
                    <span class="file-name"><span class="name">${safeName}</span>${meta ? '<span class="meta">' + meta + '</span>' : ''}</span>
                    ${isAudio ? '<button class="btn" onclick="event.stopPropagation(); downloadFile(\\''+safeId+'\\')">⬇️</button><button class="btn" onclick="event.stopPropagation(); addToPlaylist(\\''+safeId+'\\', \\''+safeNameJs+'\\')"">+ Add</button>' : ''}
                </div>`;
            }).join('');
        }

        function downloadFile(id) {
            window.location.href = '/api/download/' + id;
        }

        function downloadAllFiles() {
            if (playlist.length === 0) {
                alert('Playlist is empty');
                return;
            }
            const name = document.getElementById('playlistName').value || 'playlist';
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = '⏳ Downloading...';

            fetchWithCsrf('/api/download-playlist', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name, tracks: playlist})
            })
            .then(r => {
                if (!r.ok) {
                    return r.json().then(data => { throw new Error(data.error || 'Download failed'); });
                }
                return r.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = name + '.zip';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                alert('✅ Download complete: ' + name + '.zip');
            })
            .catch(err => {
                alert('Download error: ' + err.message);
            })
            .finally(() => {
                btn.disabled = false;
                btn.textContent = '⬇️ Download All';
            });
        }

        function addToPlaylist(id, name) {
            if (!playlist.find(p => p.id === id)) {
                playlist.push({id, name});
                updatePlaylistUI();
            }
        }

        function removeFromPlaylist(id) {
            playlist = playlist.filter(p => p.id !== id);
            updatePlaylistUI();
        }

        function clearPlaylist() {
            playlist = [];
            updatePlaylistUI();
        }

        function downloadPlaylist() {
            if (playlist.length === 0) {
                alert('Playlist is empty');
                return;
            }
            // Get a stream token first
            fetch('/api/stream-token')
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        alert('Error: ' + data.error);
                        return;
                    }
                    const token = data.token;
                    const baseUrl = window.location.origin;
                    const name = document.getElementById('playlistName').value || 'playlist';
                    let m3u = '#EXTM3U\\n';
                    playlist.forEach(p => {
                        m3u += '#EXTINF:-1,' + p.name + '\\n';
                        m3u += baseUrl + '/api/stream/' + p.id + '?token=' + token + '\\n';
                    });
                    const blob = new Blob([m3u], {type: 'audio/x-mpegurl'});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = name + '.m3u';
                    a.click();
                    URL.revokeObjectURL(url);
                });
        }

        function downloadPublicZip(event) {
            if (playlist.length === 0) {
                alert('Playlist is empty');
                return;
            }
            const name = document.getElementById('playlistName').value || 'playlist';
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = '⏳ Downloading...';

            fetch('/api/public-zip', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name, tracks: playlist})
            })
            .then(r => {
                if (!r.ok) {
                    return r.json().then(data => { throw new Error(data.error || 'Download failed'); });
                }
                return r.blob();
            })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = name + '-public.zip';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                alert('✅ Download complete: ' + name + '-public.zip');
            })
            .catch(err => {
                alert('Download error: ' + err.message);
            })
            .finally(() => {
                btn.disabled = false;
                btn.textContent = '📦 Public ZIP';
            });
        }

        function downloadPublicPlaylist() {
            if (playlist.length === 0) {
                alert('Playlist is empty');
                return;
            }
            const name = document.getElementById('playlistName').value || 'playlist';
            let m3u = '#EXTM3U\\n';
            playlist.forEach(p => {
                m3u += '#EXTINF:-1,' + p.name + '\\n';
                m3u += 'https://drive.google.com/uc?id=' + p.id + '\\n';
            });
            const blob = new Blob([m3u], {type: 'audio/x-mpegurl'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = name + '-public.m3u';
            a.click();
            URL.revokeObjectURL(url);
        }

        function savePlaylist() {
            const name = document.getElementById('playlistName').value.trim();
            if (!name) {
                alert('Please enter a playlist name');
                return;
            }
            if (playlist.length === 0) {
                alert('Playlist is empty');
                return;
            }
            fetchWithCsrf('/api/playlists', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name, tracks: playlist})
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    alert('Error: ' + data.error);
                } else {
                    document.getElementById('playlistName').value = '';
                    loadSavedPlaylists();
                }
            });
        }

        function loadSavedPlaylists() {
            fetch('/api/playlists')
                .then(r => r.json())
                .then(data => {
                    renderSavedPlaylists(data.playlists || {});
                });
        }

        function renderSavedPlaylists(playlists) {
            const container = document.getElementById('savedPlaylistItems');
            const names = Object.keys(playlists);
            if (names.length === 0) {
                container.innerHTML = '<div style="color: #888; padding: 10px;">No saved playlists</div>';
                return;
            }
            container.innerHTML = names.map(name => {
                const count = playlists[name].length;
                const safeName = escapeHtml(name);
                const safeNameJs = escapeJs(name);
                return `<div class="playlist-item">
                    <span onclick="loadPlaylist('${safeNameJs}');" style="cursor:pointer; flex:1;">📋 ${safeName} (${count} tracks)</span>
                    <button onclick="deletePlaylist('${safeNameJs}')">✕</button>
                </div>`;
            }).join('');
        }

        function loadPlaylist(name) {
            fetch('/api/playlists/' + encodeURIComponent(name))
                .then(r => r.json())
                .then(data => {
                    if (data.tracks) {
                        playlist = data.tracks;
                        document.getElementById('playlistName').value = name;
                        updatePlaylistUI();
                    }
                });
        }

        function deletePlaylist(name) {
            if (!confirm('Delete playlist "' + name + '"?')) return;
            fetchWithCsrf('/api/playlists/' + encodeURIComponent(name), {method: 'DELETE'})
                .then(r => r.json())
                .then(() => loadSavedPlaylists());
        }

        function updatePlaylistUI() {
            document.getElementById('playlistCount').textContent = playlist.length;
            document.getElementById('playlistItems').innerHTML = playlist.map(p =>
                `<div class="playlist-item">
                    <span>🎵 ${escapeHtml(p.name)}</span>
                    <button onclick="removeFromPlaylist('${escapeJs(p.id)}')">✕</button>
                </div>`
            ).join('');
        }

        function playPlaylist() {
            if (playlist.length === 0) return;
            currentTrackIndex = 0;
            playTrack(currentTrackIndex);
        }

        function playTrack(index) {
            if (index >= playlist.length) {
                document.getElementById('nowPlaying').style.display = 'none';
                return;
            }
            const track = playlist[index];
            document.getElementById('nowPlaying').style.display = 'block';
            document.getElementById('nowPlayingText').textContent = 'Now Playing: ' + track.name;  // textContent is safe

            const audio = document.getElementById('audioPlayer');
            audio.src = '/api/stream/' + track.id;
            audio.play();

            audio.onended = function() {
                currentTrackIndex++;
                playTrack(currentTrackIndex);
            };
        }

        function rewind() {
            const audio = document.getElementById('audioPlayer');
            audio.currentTime = Math.max(0, audio.currentTime - 10);
        }

        function forward() {
            const audio = document.getElementById('audioPlayer');
            audio.currentTime = Math.min(audio.duration, audio.currentTime + 10);
        }

        function prevTrack() {
            if (currentTrackIndex > 0) {
                currentTrackIndex--;
                playTrack(currentTrackIndex);
            }
        }

        function nextTrack() {
            if (currentTrackIndex < playlist.length - 1) {
                currentTrackIndex++;
                playTrack(currentTrackIndex);
            }
        }

        // Favorites functions
        function loadFavorites() {
            fetch('/api/favorites')
                .then(r => r.json())
                .then(data => {
                    favorites = data.favorites || [];
                    renderFavorites();
                });
        }

        function renderFavorites() {
            const container = document.getElementById('favoritesList');
            if (favorites.length === 0) {
                container.innerHTML = '<div style="color: #888; padding: 10px;">No favorites yet. Navigate to a folder and click "Add to Favorites".</div>';
                return;
            }
            container.innerHTML = favorites.map((f, idx) =>
                `<div class="playlist-item">
                    <span onclick="goToFavorite('${escapeJs(f.id)}', '${escapeJs(f.name)}', '${escapeJs(f.mode || 'mydrive')}');" style="cursor:pointer; flex:1;">📁 ${escapeHtml(f.name)}</span>
                    <button onclick="removeFavorite(${idx})">✕</button>
                </div>`
            ).join('');
        }

        function toggleFavorites() {
            const panel = document.getElementById('favoritesPanel');
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        }

        function addCurrentToFavorites() {
            if (currentFolder === 'root' || currentFolder === 'shared') {
                alert('Cannot add root folders to favorites');
                return;
            }
            const currentName = folderStack[folderStack.length - 1]?.name || 'Unknown';
            if (favorites.find(f => f.id === currentFolder)) {
                alert('Already in favorites');
                return;
            }
            favorites.push({id: currentFolder, name: currentName, mode: currentMode});
            fetchWithCsrf('/api/favorites', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({favorites: favorites})
            }).then(() => {
                renderFavorites();
                alert('Added to favorites!');
            });
        }

        function removeFavorite(idx) {
            favorites.splice(idx, 1);
            fetchWithCsrf('/api/favorites', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({favorites: favorites})
            }).then(() => renderFavorites());
        }

        function goToFavorite(id, name, mode) {
            if (mode === 'shared') {
                switchToShared();
            } else {
                switchToMyDrive();
            }
            folderStack = [{id: mode === 'shared' ? 'shared' : 'root', name: mode === 'shared' ? 'Shared with me' : 'My Drive'}, {id: id, name: name}];
            loadFolder(id, name);
            document.getElementById('favoritesPanel').style.display = 'none';
        }

        function toggleGoToFolder() {
            const panel = document.getElementById('goToFolderPanel');
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        }

        function goToFolderUrl() {
            const input = document.getElementById('folderUrlInput').value.trim();
            if (!input) {
                alert('Please enter a folder URL or ID');
                return;
            }

            // Extract folder ID from URL or use as-is
            let folderId = input;
            const urlMatch = input.match(/folders\/([a-zA-Z0-9_-]+)/);
            if (urlMatch) {
                folderId = urlMatch[1];
            }

            console.log('Going to folder:', folderId);

            // Fetch folder info to get its name
            fetch('/api/folder-info/' + encodeURIComponent(folderId))
                .then(r => {
                    console.log('Response status:', r.status);
                    return r.json();
                })
                .then(data => {
                    console.log('Folder data:', data);
                    if (data.error) {
                        alert('Error: ' + data.error);
                        return;
                    }
                    const folderName = data.name || 'Shared Folder';
                    currentMode = 'shared';
                    document.getElementById('btnShared').style.background = '#34a853';
                    document.getElementById('btnMyDrive').style.background = '#4285f4';
                    folderStack = [{id: 'shared', name: 'Shared'}, {id: folderId, name: folderName}];
                    loadFolder(folderId, folderName);
                    document.getElementById('goToFolderPanel').style.display = 'none';
                    document.getElementById('folderUrlInput').value = '';
                })
                .catch(err => {
                    console.error('Error:', err);
                    alert('Error accessing folder: ' + err);
                });
        }

        function switchToMyDrive() {
            currentMode = 'mydrive';
            document.getElementById('btnMyDrive').style.background = '#34a853';
            document.getElementById('btnShared').style.background = '#4285f4';
            folderStack = [{id: 'root', name: 'My Drive'}];
            loadFolder('root');
        }

        function switchToShared() {
            currentMode = 'shared';
            document.getElementById('btnShared').style.background = '#34a853';
            document.getElementById('btnMyDrive').style.background = '#4285f4';
            folderStack = [{id: 'shared', name: 'Shared with me'}];
            loadSharedFiles();
        }

        function loadSharedFiles() {
            currentFolder = 'shared';
            updateBreadcrumb();
            document.getElementById('fileList').innerHTML = '<div class="loading">Loading...</div>';
            document.getElementById('btnAddFav').style.display = 'none';
            fetch('/api/shared')
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        document.getElementById('fileList').innerHTML = '<div class="loading" style="color:#e74c3c;">Error: ' + data.error + '</div>';
                    } else {
                        renderFiles(data.files || []);
                    }
                });
        }

        // Update loadFolder to show/hide "Add to Favorites" button
        const originalLoadFolder = loadFolder;
        loadFolder = function(folderId, folderName) {
            originalLoadFolder(folderId, folderName);
            document.getElementById('btnAddFav').style.display = (folderId !== 'root' && folderId !== 'shared') ? 'inline-block' : 'none';
        };

        // Load initial data
        loadFolder('root');
        loadSavedPlaylists();
        loadFavorites();
    </script>
</body>
</html>
"""

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Login - Google Drive Audio Player</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png">
    <link rel="apple-touch-icon" href="/static/icon-128.png">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #fff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .login-box {
            background: #16213e;
            padding: 40px;
            border-radius: 12px;
            text-align: center;
            max-width: 400px;
        }
        h1 { margin-bottom: 10px; }
        p { color: #888; margin-bottom: 30px; }
        .btn-google {
            background: #4285f4;
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
        .btn-google:hover { background: #3367d6; }
        @media (max-width: 480px) {
            .login-box { margin: 20px; padding: 30px 20px; }
            h1 { font-size: 1.4em; }
            .btn-google { padding: 12px 24px; font-size: 15px; width: 100%; }
        }
    </style>
</head>
<body>
    <div class="login-box">
        <img src="/static/icon-128.png" alt="GDrive Player" style="width: 80px; height: 80px; margin-bottom: 15px;">
        <h1>Google Drive Audio Player</h1>
        <p>Stream your audio files from Google Drive</p>
        <a href="/authorize" class="btn-google">🔐 Sign in with Google</a>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    if 'user_email' not in session:
        return redirect(url_for('login'))
    return render_template_string(HTML_TEMPLATE, version=VERSION, user_email=session['user_email'], csrf_token=get_csrf_token())

@app.route('/login')
def login():
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/authorize')
def authorize():
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=url_for('oauth_callback', _external=True, _scheme='https')
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth/callback')
def oauth_callback():
    if 'state' not in session:
        return redirect(url_for('login'))

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        state=session['state'],
        redirect_uri=url_for('oauth_callback', _external=True, _scheme='https')
    )

    flow.fetch_token(authorization_response=request.url.replace('http://', 'https://'))

    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': list(credentials.scopes)
    }

    # Get user email
    from googleapiclient.discovery import build as gbuild
    oauth2_service = gbuild('oauth2', 'v2', credentials=credentials)
    user_info = oauth2_service.userinfo().get().execute()
    session['user_email'] = user_info.get('email', 'Unknown')

    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/files')
@login_required
def api_files():
    try:
        service = get_drive_service()
        if not service:
            return jsonify({'error': 'Not authenticated'}), 401

        folder_id = request.args.get('folder', 'root')

        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(
            q=query,
            pageSize=100,
            fields="files(id, name, mimeType, size, modifiedTime)",
            orderBy="folder,name",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        return jsonify({'files': results.get('files', [])})
    except Exception as e:
        print(f"Error in api_files: {e}", flush=True)
        return jsonify({'error': str(e)}), 500

def get_all_subfolder_ids(service, folder_id, max_depth=10):
    """Recursively get all subfolder IDs within a folder."""
    folder_ids = [folder_id]
    if max_depth <= 0:
        return folder_ids

    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            pageSize=100,
            fields="files(id)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        for folder in results.get('files', []):
            folder_ids.extend(get_all_subfolder_ids(service, folder['id'], max_depth - 1))
    except:
        pass

    return folder_ids

@app.route('/api/search')
@login_required
def api_search():
    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401

    query_text = request.args.get('q', '')
    folder_id = request.args.get('folder', '')
    if not query_text:
        return jsonify({'files': []})

    # Escape single quotes to prevent query injection
    query_text_escaped = query_text.replace("\\", "\\\\").replace("'", "\\'")

    # Search for audio files (including shared drives)
    mime_conditions = " or ".join([f"mimeType='{mt}'" for mt in AUDIO_MIMETYPES])

    # If folder specified, search within that folder and all subfolders
    if folder_id:
        # Get all subfolder IDs recursively
        all_folder_ids = get_all_subfolder_ids(service, folder_id)
        # Build query with all folder IDs (limit to avoid query too long)
        if len(all_folder_ids) > 50:
            all_folder_ids = all_folder_ids[:50]  # Limit to prevent query overflow
        parent_conditions = " or ".join([f"'{fid}' in parents" for fid in all_folder_ids])
        query = f"name contains '{query_text_escaped}' and ({mime_conditions}) and trashed=false and ({parent_conditions})"
    else:
        query = f"name contains '{query_text_escaped}' and ({mime_conditions}) and trashed=false"

    results = service.files().list(
        q=query,
        pageSize=50,
        fields="files(id, name, mimeType, size, modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    return jsonify({'files': results.get('files', [])})

@app.route('/api/stream/<file_id>')
def api_stream(file_id):
    """Stream audio file - supports both session auth and token auth for VLC."""
    from flask import Response
    import io
    from googleapiclient.http import MediaIoBaseDownload

    # Check for token-based auth (for VLC/external players)
    token = request.args.get('token')
    if token:
        creds_data = get_credentials_from_token(token)
        if not creds_data:
            return jsonify({'error': 'Invalid or expired token'}), 401
        creds = Credentials(
            token=creds_data['token'],
            refresh_token=creds_data.get('refresh_token'),
            token_uri=creds_data['token_uri'],
            client_id=creds_data['client_id'],
            client_secret=creds_data['client_secret'],
            scopes=creds_data['scopes']
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        service = build('drive', 'v3', credentials=creds)
    else:
        # Session-based auth
        if 'user_email' not in session:
            return redirect(url_for('login'))
        service = get_drive_service()
        if not service:
            return jsonify({'error': 'Not authenticated'}), 401

    # Get file metadata
    file_meta = service.files().get(fileId=file_id, fields='name,mimeType', supportsAllDrives=True).execute()

    # Download file
    request_media = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request_media)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    return Response(
        fh.read(),
        mimetype=file_meta.get('mimeType', 'audio/mpeg'),
        headers={'Content-Disposition': f'inline; filename="{file_meta["name"]}"'}
    )

@app.route('/api/stream-token')
@login_required
def api_stream_token():
    """Generate a stream token for external players like VLC."""
    if 'credentials' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    token = create_stream_token(session['credentials'])
    return jsonify({'token': token})

@app.route('/api/download/<file_id>')
@login_required
def api_download(file_id):
    """Download a single file."""
    from flask import Response
    import io
    from googleapiclient.http import MediaIoBaseDownload

    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401

    # Get file metadata
    file_meta = service.files().get(fileId=file_id, fields='name,mimeType', supportsAllDrives=True).execute()

    # Download file
    request_media = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request_media)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    return Response(
        fh.read(),
        mimetype=file_meta.get('mimeType', 'audio/mpeg'),
        headers={'Content-Disposition': f'attachment; filename="{file_meta["name"]}"'}
    )

@app.route('/api/download-playlist', methods=['POST'])
@login_required
@csrf_protected
def api_download_playlist():
    """Download all files in a playlist as a ZIP with M3U."""
    from flask import Response
    import io
    import zipfile
    from googleapiclient.http import MediaIoBaseDownload

    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    tracks = data.get('tracks', [])
    playlist_name = data.get('name', 'playlist')

    if not tracks:
        return jsonify({'error': 'No tracks provided'}), 400

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    downloaded_files = []

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for track in tracks:
            try:
                file_id = track.get('id')
                file_name = track.get('name', f'{file_id}.mp3')

                # Download file
                request_media = service.files().get_media(fileId=file_id, supportsAllDrives=True)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request_media)
                done = False
                while not done:
                    status, done = downloader.next_chunk()

                fh.seek(0)
                zf.writestr(file_name, fh.read())
                downloaded_files.append(file_name)
            except Exception as e:
                print(f"Error downloading {track}: {e}", flush=True)

        # Create M3U playlist file with local references
        m3u_content = '#EXTM3U\n'
        for fname in downloaded_files:
            m3u_content += f'#EXTINF:-1,{fname}\n'
            m3u_content += f'{fname}\n'
        zf.writestr(f'{playlist_name}.m3u', m3u_content)

    zip_buffer.seek(0)
    return Response(
        zip_buffer.read(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{playlist_name}.zip"'}
    )

@app.route('/api/public-zip', methods=['POST'])
def api_public_zip():
    """Download publicly shared Google Drive files as a ZIP (no auth required on files)."""
    import io
    import zipfile
    import requests as req

    data = request.get_json()
    tracks = data.get('tracks', [])
    playlist_name = data.get('name', 'playlist')

    if not tracks:
        return jsonify({'error': 'No tracks provided'}), 400

    zip_buffer = io.BytesIO()
    downloaded_files = []

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for track in tracks:
            file_id = track.get('id')
            file_name = track.get('name', f'{file_id}.mp3')
            url = f'https://drive.google.com/uc?export=download&id={file_id}'
            try:
                r = req.get(url, timeout=60, allow_redirects=True)
                r.raise_for_status()
                zf.writestr(file_name, r.content)
                downloaded_files.append(file_name)
            except Exception as e:
                print(f"Error downloading public file {file_id}: {e}", flush=True)

        m3u_content = '#EXTM3U\n'
        for fname in downloaded_files:
            m3u_content += f'#EXTINF:-1,{fname}\n'
            m3u_content += f'{fname}\n'
        zf.writestr(f'{playlist_name}.m3u', m3u_content)

    zip_buffer.seek(0)
    return Response(
        zip_buffer.read(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{playlist_name}-public.zip"'}
    )

@app.route('/api/playlists', methods=['GET'])
@login_required
def api_get_playlists():
    """Get all playlists for current user."""
    playlists = load_user_playlists()
    return jsonify({'playlists': playlists})

@app.route('/api/playlists', methods=['POST'])
@login_required
@csrf_protected
def api_save_playlist():
    """Save a new playlist."""
    data = request.get_json()
    name = data.get('name', '').strip()
    tracks = data.get('tracks', [])

    if not name:
        return jsonify({'error': 'Playlist name required'}), 400

    playlists = load_user_playlists()
    playlists[name] = tracks
    save_user_playlists(playlists)

    return jsonify({'success': True})

@app.route('/api/playlists/<name>', methods=['GET'])
@login_required
def api_get_playlist(name):
    """Get a specific playlist."""
    playlists = load_user_playlists()
    if name not in playlists:
        return jsonify({'error': 'Playlist not found'}), 404
    return jsonify({'name': name, 'tracks': playlists[name]})

@app.route('/api/playlists/<name>', methods=['DELETE'])
@login_required
@csrf_protected
def api_delete_playlist(name):
    """Delete a playlist."""
    playlists = load_user_playlists()
    if name in playlists:
        del playlists[name]
        save_user_playlists(playlists)
    return jsonify({'success': True})

@app.route('/api/folder-info/<folder_id>')
@login_required
def api_folder_info(folder_id):
    """Get folder metadata."""
    try:
        service = get_drive_service()
        if not service:
            return jsonify({'error': 'Not authenticated'}), 401

        file_meta = service.files().get(
            fileId=folder_id,
            fields='id,name,mimeType',
            supportsAllDrives=True
        ).execute()
        return jsonify(file_meta)
    except Exception as e:
        print(f"Error in api_folder_info: {e}", flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/shared')
@login_required
def api_shared():
    """Get files shared with the user."""
    try:
        service = get_drive_service()
        if not service:
            return jsonify({'error': 'Not authenticated'}), 401

        # Query for files shared with user (not owned by user)
        query = "sharedWithMe=true and trashed=false"
        results = service.files().list(
            q=query,
            pageSize=100,
            fields="files(id, name, mimeType, size, modifiedTime)",
            orderBy="folder,name",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        return jsonify({'files': results.get('files', [])})
    except Exception as e:
        print(f"Error in api_shared: {e}", flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/favorites', methods=['GET'])
@login_required
def api_get_favorites():
    """Get favorites for current user."""
    favorites = load_user_favorites()
    return jsonify({'favorites': favorites})

@app.route('/api/favorites', methods=['POST'])
@login_required
@csrf_protected
def api_save_favorites():
    """Save favorites for current user."""
    data = request.get_json()
    favorites = data.get('favorites', [])
    save_user_favorites(favorites)
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False)
