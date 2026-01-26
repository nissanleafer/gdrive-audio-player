#!/usr/bin/env python3
"""
Google Drive Audio Player - Web UI
Simple browser-based interface for selecting and playing audio files.
"""

import os
import sys
import subprocess
import tempfile
import webbrowser
import threading
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request

# Google API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

VERSION = "1.3.7"

SCOPES = [
    'https://www.googleapis.com/auth/drive',  # Full access to create playlist files
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]
APP_DIR = Path(__file__).parent

USER_DATA_DIR = Path.home() / '.gdrive-player'

# Look for credentials.json in multiple locations
def find_credentials():
    locations = []

    # Check PyInstaller bundle first (for packaged app)
    if getattr(sys, '_MEIPASS', None):
        locations.append(Path(sys._MEIPASS) / 'credentials.json')

    # Then check other locations
    locations.extend([
        USER_DATA_DIR / 'credentials.json',  # ~/.gdrive-player/credentials.json
        APP_DIR / 'credentials.json',         # Next to the script
        Path.cwd() / 'credentials.json',      # Current directory
    ])

    for loc in locations:
        if loc.exists():
            return loc
    return USER_DATA_DIR / 'credentials.json'  # Default location

CREDENTIALS_FILE = find_credentials()
TOKEN_FILE = USER_DATA_DIR / 'token.json'
DOWNLOAD_DIR = USER_DATA_DIR / 'downloads'
PLAYLISTS_DIR = Path.home() / 'Music' / 'GDrive Playlists'

AUDIO_MIMETYPES = [
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/ogg', 'audio/flac', 'audio/aac', 'audio/m4a', 'audio/x-m4a',
]

app = Flask(__name__)
drive_service = None
user_email = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Google Drive Audio Player</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        h1 { color: #333; margin-bottom: 5px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .header-left { }
        .user-info {
            background: #fff;
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 0.9em;
            color: #666;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .user-info a { color: #4285f4; margin-left: 10px; text-decoration: none; cursor: pointer; }
        .user-info a:hover { text-decoration: underline; }
        .subtitle { color: #666; margin-bottom: 10px; }
        .breadcrumb {
            background: #fff;
            padding: 10px 15px;
            border-radius: 8px;
            margin-bottom: 15px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .breadcrumb a { color: #4285f4; text-decoration: none; }
        .breadcrumb a:hover { text-decoration: underline; }
        .file-list {
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .file-item {
            display: flex;
            align-items: center;
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
            transition: background 0.2s;
        }
        .file-item:hover { background: #f8f9fa; }
        .file-item:last-child { border-bottom: none; }
        .file-item.folder { color: #4285f4; }
        .file-item input[type="checkbox"] {
            width: 18px;
            height: 18px;
            margin-right: 12px;
        }
        .file-icon { margin-right: 10px; font-size: 1.2em; }
        .file-name { flex: 1; }
        .file-size { color: #888; font-size: 0.9em; }
        .controls {
            margin-top: 20px;
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        button {
            padding: 12px 24px;
            font-size: 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #4285f4;
            color: white;
        }
        .btn-primary:hover { background: #3367d6; }
        .btn-primary:disabled { background: #ccc; cursor: not-allowed; }
        .btn-secondary {
            background: #fff;
            color: #333;
            border: 1px solid #ddd;
        }
        .btn-secondary:hover { background: #f5f5f5; }
        .selected-count {
            padding: 8px 16px;
            background: #e8f0fe;
            color: #4285f4;
            border-radius: 20px;
            font-weight: 500;
        }
        .mode-toggle {
            display: flex;
            gap: 5px;
            background: #eee;
            padding: 4px;
            border-radius: 8px;
        }
        .mode-toggle button {
            padding: 8px 16px;
            background: transparent;
            border-radius: 6px;
        }
        .mode-toggle button.active {
            background: #fff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .empty {
            text-align: center;
            padding: 40px;
            color: #888;
        }
        .view-toggle {
            display: flex;
            gap: 5px;
            background: #eee;
            padding: 4px;
            border-radius: 8px;
            margin-bottom: 15px;
        }
        .view-toggle button {
            padding: 8px 16px;
            background: transparent;
            border-radius: 6px;
            font-size: 14px;
        }
        .view-toggle button.active {
            background: #fff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .folder-path {
            color: #888;
            font-size: 0.85em;
            margin-left: auto;
        }
        .audio-folder {
            border-left: 3px solid #4285f4;
        }
        .audio-folder .folder-path { display: block; margin-top: 4px; margin-left: 40px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <h1>🎵 Google Drive Audio Player</h1>
            <p class="subtitle">Select audio files and play in your favorite player <span style="color: #999; font-size: 12px;">v{{ version }}</span></p>
        </div>
        <div class="user-info" id="userInfo">Loading...</div>
    </div>

    <input type="text" id="searchBox" placeholder="Search or paste a Google Drive URL..."
           oninput="handleSearch(this.value)"
           style="width: 100%; padding: 12px 15px; font-size: 16px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 15px;">

    <div class="view-toggle">
        <button id="browseBtn" class="active" onclick="setView('browse')">📁 My Drive</button>
        <button id="sharedBtn" onclick="setView('shared')">🤝 Shared</button>
        <button id="favoritesBtn" onclick="setView('favorites')">⭐ Favorites</button>
        <button id="playlistsBtn" onclick="setView('playlists')">🎵 Playlists</button>
        <button id="allAudioBtn" onclick="setView('all')">🎧 All Audio</button>
    </div>

    <div class="controls" id="fileControls">
        <span class="selected-count" id="selectedCount">0 selected</span>
        <div class="mode-toggle">
            <button id="streamBtn" class="active" onclick="setMode('stream')">📡 Stream</button>
            <button id="downloadBtn" onclick="setMode('download')">💾 Download</button>
        </div>
        <button class="btn-primary" id="playBtn" onclick="play()" disabled>
            ▶️ Play
        </button>
        <button class="btn-secondary" id="saveLocalBtn" onclick="savePlaylistLocal()" disabled>
            📋 Save Playlist
        </button>
        <button class="btn-secondary" id="saveBtn" onclick="savePlaylistToDrive()" disabled>
            ☁️ Export to Drive
        </button>
        <button class="btn-secondary" onclick="selectAll()">☑️ Select All</button>
        <button class="btn-secondary" onclick="clearSelection()">✖️ Clear</button>
    </div>

    <div class="breadcrumb" id="breadcrumb">
        <a href="#" onclick="navigate(null)">My Drive</a>
    </div>

    <div class="file-list" id="fileList">
        <div class="loading">Loading...</div>
    </div>

    <div style="text-align: center; margin-top: 10px; font-size: 12px;">
        <a href="#" onclick="openPlaylistsFolder(); return false;" style="color: #666; margin-right: 15px;">📂 Playlists Folder</a>
        <a href="#" onclick="openDownloadsFolder(); return false;" style="color: #666;">📂 Downloads Folder</a>
    </div>

    <script>
        let currentFolder = null;
        let folderStack = [];
        let selectedFiles = new Map();
        let playMode = 'stream';
        let currentView = 'browse';
        let allAudioCache = null;
        let searchTimeout = null;
        let favorites = JSON.parse(localStorage.getItem('gdrive-favorites') || '[]');
        let playlists = JSON.parse(localStorage.getItem('gdrive-playlists') || '[]');

        async function loadUserInfo() {
            const response = await fetch('/api/user');
            const data = await response.json();
            document.getElementById('userInfo').innerHTML = data.email +
                '<a onclick="switchAccount()">Switch Account</a>';
        }

        async function switchAccount() {
            if (confirm('Switch to a different Google account?')) {
                document.getElementById('userInfo').innerHTML = 'Restarting...';
                await fetch('/api/switch-account', {method: 'POST'});
                // Wait for server to restart, then reload
                setTimeout(() => {
                    checkServerAndReload();
                }, 1500);
            }
        }

        function checkServerAndReload() {
            fetch('/api/user')
                .then(() => location.reload())
                .catch(() => setTimeout(checkServerAndReload, 500));
        }

        function setView(view) {
            currentView = view;
            document.getElementById('browseBtn').classList.toggle('active', view === 'browse');
            document.getElementById('sharedBtn').classList.toggle('active', view === 'shared');
            document.getElementById('favoritesBtn').classList.toggle('active', view === 'favorites');
            document.getElementById('playlistsBtn').classList.toggle('active', view === 'playlists');
            document.getElementById('allAudioBtn').classList.toggle('active', view === 'all');
            document.getElementById('breadcrumb').style.display = ['browse', 'shared', 'favorites'].includes(view) ? 'block' : 'none';

            if (view === 'all') {
                document.getElementById('searchBox').placeholder = 'Search all audio files...';
                loadAllAudio();
            } else if (view === 'shared') {
                document.getElementById('searchBox').placeholder = 'Search shared files...';
                document.getElementById('fileControls').style.display = 'flex';
                currentFolder = null;
                folderStack = [];
                updateBreadcrumb();
                loadFiles();
            } else if (view === 'favorites') {
                document.getElementById('searchBox').placeholder = 'Search favorites...';
                document.getElementById('fileControls').style.display = 'flex';
                currentFolder = null;
                folderStack = [];
                updateBreadcrumb();
                loadFavorites();
            } else if (view === 'playlists') {
                document.getElementById('searchBox').placeholder = 'Search playlists...';
                document.getElementById('fileControls').style.display = 'none';
                currentFolder = null;
                folderStack = [];
                loadPlaylists();
            } else {
                document.getElementById('fileControls').style.display = 'flex';
                document.getElementById('searchBox').placeholder = 'Search files and folders...';
                currentFolder = null;
                folderStack = [];
                updateBreadcrumb();
                loadFiles();
            }
        }

        function loadFavorites() {
            if (favorites.length === 0) {
                document.getElementById('fileList').innerHTML = '<div class="empty">No favorites yet.<br><br>Navigate to a folder and click the ⭐ to add it.</div>';
                return;
            }

            let html = '';
            favorites.forEach(fav => {
                html += '<div class="file-item folder" style="position: relative;">' +
                        '<span class="file-icon">📁</span>' +
                        '<span class="file-name" onclick="navigateToFavorite(\\'' + fav.id + '\\', \\'' + fav.name.replace(/'/g, "&#39;") + '\\')" style="cursor: pointer; flex: 1;">' + fav.name + '</span>' +
                        '<span onclick="removeFavorite(\\'' + fav.id + '\\')" style="cursor: pointer; padding: 5px 10px;" title="Remove from favorites">✕</span>' +
                        '</div>';
            });

            document.getElementById('fileList').innerHTML = html;
        }

        function addFavorite(id, name) {
            if (!favorites.find(f => f.id === id)) {
                favorites.push({id: id, name: name, added: Date.now()});
                localStorage.setItem('gdrive-favorites', JSON.stringify(favorites));
                updateFavoriteButton();
                alert('Added to favorites: ' + name);
            }
        }

        function removeFavorite(id) {
            favorites = favorites.filter(f => f.id !== id);
            localStorage.setItem('gdrive-favorites', JSON.stringify(favorites));
            if (currentView === 'favorites') {
                loadFavorites();
            }
            updateFavoriteButton();
        }

        function isFavorite(id) {
            return favorites.some(f => f.id === id);
        }

        function updateFavoriteButton() {
            const btn = document.getElementById('favBtn');
            if (btn && currentFolder) {
                btn.textContent = isFavorite(currentFolder) ? '★' : '☆';
                btn.title = isFavorite(currentFolder) ? 'Remove from favorites' : 'Add to favorites';
            }
        }

        function toggleFavorite() {
            if (!currentFolder || folderStack.length === 0) return;
            const name = folderStack[folderStack.length - 1].name;
            if (isFavorite(currentFolder)) {
                removeFavorite(currentFolder);
            } else {
                addFavorite(currentFolder, name);
            }
        }

        function navigateToFavorite(folderId, folderName) {
            currentView = 'browse';
            document.getElementById('browseBtn').classList.add('active');
            document.getElementById('favoritesBtn').classList.remove('active');
            document.getElementById('breadcrumb').style.display = 'block';
            folderStack = [{id: folderId, name: folderName}];
            currentFolder = folderId;
            updateBreadcrumb();
            loadFiles();
        }

        function loadPlaylists() {
            if (playlists.length === 0) {
                document.getElementById('fileList').innerHTML = '<div class="empty">No playlists yet.<br><br>Select files and click "Save Playlist" to create one.</div>';
                return;
            }

            let html = '';
            playlists.forEach((pl, index) => {
                html += '<div class="file-item" style="position: relative;">' +
                        '<span class="file-icon">🎵</span>' +
                        '<span class="file-name" onclick="loadPlaylistFiles(' + index + ')" style="cursor: pointer; flex: 1;">' + pl.name + ' (' + pl.files.length + ' tracks)</span>' +
                        '<button onclick="playPlaylistMode(' + index + ', \\'stream\\')" style="padding: 3px 8px; margin-right: 5px; cursor: pointer;" title="Stream from cloud">📡</button>' +
                        '<button onclick="playPlaylistMode(' + index + ', \\'download\\')" style="padding: 3px 8px; margin-right: 5px; cursor: pointer;" title="Download and play">💾</button>' +
                        '<span onclick="exportPlaylist(' + index + ')" style="cursor: pointer; padding: 5px 10px;" title="Export to Google Drive">☁️</span>' +
                        '<span onclick="deletePlaylist(' + index + ')" style="cursor: pointer; padding: 5px 10px; color: #e74c3c;" title="Delete playlist">🗑️</span>' +
                        '</div>';
            });

            document.getElementById('fileList').innerHTML = html;
        }

        function savePlaylistLocal() {
            const files = Array.from(selectedFiles.values());
            if (files.length === 0) {
                alert('Select some files first');
                return;
            }

            const name = prompt('Playlist name:');
            if (!name) return;

            playlists.push({
                name: name,
                files: files,
                created: Date.now()
            });
            localStorage.setItem('gdrive-playlists', JSON.stringify(playlists));
            alert('Playlist "' + name + '" saved with ' + files.length + ' tracks');
        }

        function loadPlaylistFiles(index) {
            const pl = playlists[index];
            if (!pl) return;

            selectedFiles.clear();
            pl.files.forEach(f => selectedFiles.set(f.id, f));

            let html = '<div style="padding: 10px 15px; background: #f8f9fa; font-weight: 500; color: #666;">Playlist: ' + pl.name + '</div>';
            pl.files.forEach(file => {
                html += '<div class="file-item" onclick="toggleFile(event, \\'' + file.id + '\\')">' +
                        '<input type="checkbox" checked onclick="toggleFile(event, \\'' + file.id + '\\')" data-file=\\'' + JSON.stringify(file).replace(/'/g, "&#39;") + '\\'>' +
                        '<span class="file-icon">🎵</span>' +
                        '<span class="file-name">' + file.name + '</span>' +
                        '<span class="file-size">' + (file.size || '') + '</span>' +
                        '</div>';
            });

            document.getElementById('fileList').innerHTML = html;
            updateSelectedCount();
        }

        function deletePlaylist(index) {
            if (confirm('Delete playlist "' + playlists[index].name + '"?')) {
                playlists.splice(index, 1);
                localStorage.setItem('gdrive-playlists', JSON.stringify(playlists));
                loadPlaylists();
            }
        }

        async function playPlaylist(index) {
            const pl = playlists[index];
            if (!pl) return;

            const response = await fetch('/api/play', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({files: pl.files, mode: playMode})
            });

            const result = await response.json();
            if (!result.success) {
                alert('Error: ' + result.error);
            }
        }

        async function playPlaylistMode(index, mode) {
            const pl = playlists[index];
            if (!pl) return;

            const response = await fetch('/api/play', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({files: pl.files, mode: mode, name: pl.name})
            });

            const result = await response.json();
            if (!result.success) {
                alert('Error: ' + result.error);
            }
        }

        async function exportPlaylist(index) {
            const pl = playlists[index];
            if (!pl) return;

            const response = await fetch('/api/save-playlist', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({files: pl.files, name: pl.name})
            });

            const result = await response.json();
            if (result.success) {
                alert('Playlist "' + pl.name + '" saved to Google Drive!');
            } else {
                alert('Error: ' + result.error);
            }
        }

        async function loadSharedDrives() {
            document.getElementById('fileList').innerHTML = '<div class="loading">Loading shared drives...</div>';

            const response = await fetch('/api/shared-drives');
            const data = await response.json();

            if (data.drives.length === 0) {
                document.getElementById('fileList').innerHTML = '<div class="empty">No shared drives found</div>';
                return;
            }

            let html = '';
            data.drives.forEach(drive => {
                const safeName = drive.name.replace(/'/g, "&#39;");
                html += '<div class="file-item folder" onclick="navigateToDrive(\\'' + drive.id + '\\', \\'' + safeName + '\\')">' +
                        '<span class="file-icon">🗄️</span>' +
                        '<span class="file-name">' + drive.name + '</span>' +
                        '</div>';
            });

            document.getElementById('fileList').innerHTML = html;
        }

        function navigateToDrive(driveId, driveName) {
            currentView = 'drives';
            folderStack = [{id: driveId, name: driveName, isDrive: true}];
            currentFolder = driveId;
            updateBreadcrumb();
            loadFiles();
        }

        async function loadAllAudio() {
            document.getElementById('fileList').innerHTML = '<div class="loading">Loading all audio files...</div>';

            const response = await fetch('/api/all-audio');
            const data = await response.json();
            allAudioCache = data.files;

            renderAudioFiles(data.files);
        }

        function renderAudioFiles(files) {
            if (files.length === 0) {
                document.getElementById('fileList').innerHTML = '<div class="empty">No audio files found</div>';
                return;
            }

            let html = '';
            files.forEach(file => {
                const checked = selectedFiles.has(file.id) ? 'checked' : '';
                const safeData = JSON.stringify(file).replace(/'/g, "&#39;");
                html += '<div class="file-item audio-folder" onclick="toggleFile(event, \\'' + file.id + '\\')">' +
                        '<input type="checkbox" ' + checked + ' onclick="toggleFile(event, \\'' + file.id + '\\')" data-file=\\'' + safeData + '\\'>' +
                        '<span class="file-icon">🎵</span>' +
                        '<span class="file-name">' + file.name + '</span>' +
                        '<span class="file-size">' + file.size + '</span>' +
                        '<span class="folder-path">' + (file.path || '') + '</span>' +
                        '</div>';
            });

            document.getElementById('fileList').innerHTML = html;
        }

        function handleSearch(query) {
            clearTimeout(searchTimeout);

            // Check if it's a Google Drive URL
            if (query.includes('drive.google.com') || query.includes('docs.google.com')) {
                searchTimeout = setTimeout(() => handleDriveUrl(query), 300);
            } else {
                searchTimeout = setTimeout(() => doSearch(query), 300);
            }
        }

        async function handleDriveUrl(url) {
            const patterns = [
                /\\/folders\\/([a-zA-Z0-9_-]+)/,
                /\\/d\\/([a-zA-Z0-9_-]+)/,
                /id=([a-zA-Z0-9_-]+)/,
                /parent:([a-zA-Z0-9_-]+)/
            ];

            let folderId = null;
            for (const pattern of patterns) {
                const match = url.match(pattern);
                if (match) {
                    folderId = match[1];
                    break;
                }
            }

            if (folderId) {
                try {
                    const response = await fetch('/api/folder-info?id=' + folderId);
                    const data = await response.json();

                    if (!data.error) {
                        document.getElementById('searchBox').value = '';
                        navigateToFolder(folderId, data.name);
                        return;
                    }
                } catch (e) {}
            }

            // Fall back to regular search
            doSearch(url);
        }

        async function doSearch(query) {
            if (!query.trim()) {
                if (currentView === 'all') {
                    if (allAudioCache) renderAudioFiles(allAudioCache);
                    else loadAllAudio();
                } else if (currentView === 'favorites') {
                    loadFavorites();
                } else {
                    loadFiles();
                }
                return;
            }

            document.getElementById('fileList').innerHTML = '<div class="loading">Searching...</div>';

            // If we're in a folder, search within that folder
            let url = '/api/search?q=' + encodeURIComponent(query);
            if (currentFolder) {
                url += '&folder=' + currentFolder;
            }

            const response = await fetch(url);
            const data = await response.json();

            renderSearchResults(data.folders || [], data.files || []);
        }

        function renderSearchResults(folders, files) {
            if (folders.length === 0 && files.length === 0) {
                document.getElementById('fileList').innerHTML = '<div class="empty">No results found</div>';
                return;
            }

            let html = '';

            if (folders.length > 0) {
                html += '<div style="padding: 10px 15px; background: #f8f9fa; font-weight: 500; color: #666;">Folders</div>';
                folders.forEach(folder => {
                    const safeName = folder.name.replace(/'/g, "&#39;");
                    html += '<div class="file-item folder" onclick="navigateToFolder(\\'' + folder.id + '\\', \\'' + safeName + '\\')">' +
                            '<span class="file-icon">📁</span>' +
                            '<span class="file-name">' + folder.name + '</span>' +
                            '<span class="folder-path">' + (folder.path || '') + '</span>' +
                            '</div>';
                });
            }

            if (files.length > 0) {
                html += '<div style="padding: 10px 15px; background: #f8f9fa; font-weight: 500; color: #666;">Audio Files</div>';
                files.forEach(file => {
                    const checked = selectedFiles.has(file.id) ? 'checked' : '';
                    const safeData = JSON.stringify(file).replace(/'/g, "&#39;");
                    html += '<div class="file-item audio-folder" onclick="toggleFile(event, \\'' + file.id + '\\')">' +
                            '<input type="checkbox" ' + checked + ' onclick="toggleFile(event, \\'' + file.id + '\\')" data-file=\\'' + safeData + '\\'>' +
                            '<span class="file-icon">🎵</span>' +
                            '<span class="file-name">' + file.name + '</span>' +
                            '<span class="file-size">' + file.size + '</span>' +
                            '<span class="folder-path">' + (file.path || '') + '</span>' +
                            '</div>';
                });
            }

            document.getElementById('fileList').innerHTML = html;
        }

        function navigateToFolder(folderId, folderName) {
            document.getElementById('searchBox').value = '';
            currentView = 'browse';
            document.getElementById('browseBtn').classList.add('active');
            document.getElementById('sharedBtn').classList.remove('active');
            document.getElementById('allAudioBtn').classList.remove('active');
            document.getElementById('breadcrumb').style.display = 'block';
            folderStack = [{id: folderId, name: folderName}];
            currentFolder = folderId;
            updateBreadcrumb();
            loadFiles();
        }

        async function goToFolder() {
            const input = prompt('Paste a Google Drive folder URL or folder ID:');
            if (!input) return;

            // Extract folder ID from URL or use as-is
            let folderId = input.trim();

            // Handle various Google Drive URL formats
            const patterns = [
                /\\/folders\\/([a-zA-Z0-9_-]+)/,
                /id=([a-zA-Z0-9_-]+)/,
                /parent:([a-zA-Z0-9_-]+)/,
                /^([a-zA-Z0-9_-]{20,})$/
            ];

            for (const pattern of patterns) {
                const match = input.match(pattern);
                if (match) {
                    folderId = match[1];
                    break;
                }
            }

            // Try to get folder name from API
            try {
                const response = await fetch('/api/folder-info?id=' + folderId);
                const data = await response.json();

                if (data.error) {
                    alert('Could not access folder: ' + data.error);
                    return;
                }

                navigateToFolder(folderId, data.name);
            } catch (e) {
                alert('Error accessing folder: ' + e.message);
            }
        }

        function navigate(folderId, folderName) {
            if (folderId === null) {
                currentFolder = null;
                folderStack = [];
            } else {
                folderStack.push({id: folderId, name: folderName});
                currentFolder = folderId;
            }
            loadFiles(currentView === 'shared');
            updateBreadcrumb();
        }

        function goBack(index) {
            if (index < 0) {
                currentFolder = null;
                folderStack = [];
            } else {
                folderStack = folderStack.slice(0, index + 1);
                currentFolder = folderStack[index].id;
            }
            loadFiles();
            updateBreadcrumb();
        }

        function updateBreadcrumb() {
            let html = '<a href="#" onclick="goBack(-1)">My Drive</a>';
            folderStack.forEach((folder, i) => {
                html += ' / <a href="#" onclick="goBack(' + i + ')">' + folder.name + '</a>';
            });
            if (currentFolder && folderStack.length > 0) {
                const isFav = isFavorite(currentFolder);
                html += ' <span id="favBtn" onclick="toggleFavorite()" style="cursor: pointer; margin-left: 10px;" title="' + (isFav ? 'Remove from favorites' : 'Add to favorites') + '">' + (isFav ? '★' : '☆') + '</span>';
            }
            document.getElementById('breadcrumb').innerHTML = html;
        }

        async function loadFiles(shared = false) {
            document.getElementById('fileList').innerHTML = '<div class="loading">Loading...</div>';

            let url = '/api/files?folder=' + (currentFolder || '');
            if (shared || currentView === 'shared') {
                url += '&shared=true';
            }
            const response = await fetch(url);
            const data = await response.json();

            let html = '';

            if (data.folders.length === 0 && data.files.length === 0) {
                html = '<div class="empty">No audio files or folders here</div>';
            }

            data.folders.forEach(folder => {
                const safeName = folder.name.replace(/'/g, "&#39;");
                html += '<div class="file-item folder" onclick="navigate(\\'' + folder.id + '\\', \\'' + safeName + '\\')">' +
                        '<span class="file-icon">📁</span>' +
                        '<span class="file-name">' + folder.name + '</span>' +
                        '</div>';
            });

            data.files.forEach(file => {
                const checked = selectedFiles.has(file.id) ? 'checked' : '';
                const safeData = JSON.stringify(file).replace(/'/g, "&#39;");
                html += '<div class="file-item" onclick="toggleFile(event, \\'' + file.id + '\\')">' +
                        '<input type="checkbox" ' + checked + ' onclick="toggleFile(event, \\'' + file.id + '\\')" data-file=\\'' + safeData + '\\'>' +
                        '<span class="file-icon">🎵</span>' +
                        '<span class="file-name">' + file.name + '</span>' +
                        '<span class="file-size">' + file.size + '</span>' +
                        '</div>';
            });

            document.getElementById('fileList').innerHTML = html;
        }

        function toggleFile(event, fileId) {
            event.stopPropagation();
            let checkbox = event.target;
            const clickedCheckbox = event.target.type === 'checkbox';

            if (!clickedCheckbox) {
                checkbox = event.target.closest('.file-item').querySelector('input[type="checkbox"]');
                checkbox.checked = !checkbox.checked;
            }

            if (checkbox.checked) {
                const fileData = JSON.parse(checkbox.dataset.file.replace(/&#39;/g, "'"));
                selectedFiles.set(fileId, fileData);
            } else {
                selectedFiles.delete(fileId);
            }
            updateSelectedCount();
        }

        function selectAll() {
            document.querySelectorAll('.file-item input[type="checkbox"]').forEach(cb => {
                cb.checked = true;
                const fileData = JSON.parse(cb.dataset.file);
                selectedFiles.set(fileData.id, fileData);
            });
            updateSelectedCount();
        }

        function clearSelection() {
            selectedFiles.clear();
            document.querySelectorAll('.file-item input[type="checkbox"]').forEach(cb => {
                cb.checked = false;
            });
            updateSelectedCount();
        }

        async function openPlaylistsFolder() {
            await fetch('/api/open-playlists-folder');
        }

        async function openDownloadsFolder() {
            await fetch('/api/open-downloads-folder');
        }

        function updateSelectedCount() {
            const count = selectedFiles.size;
            document.getElementById('selectedCount').textContent = count + ' selected';
            document.getElementById('playBtn').disabled = count === 0;
            document.getElementById('saveLocalBtn').disabled = count === 0;
            document.getElementById('saveBtn').disabled = count === 0;
        }

        async function savePlaylistToDrive() {
            const files = Array.from(selectedFiles.values());
            if (files.length === 0) return;

            const name = prompt('Playlist name:', 'My Playlist');
            if (!name) return;

            document.getElementById('saveBtn').textContent = 'Saving...';
            document.getElementById('saveBtn').disabled = true;

            const response = await fetch('/api/save-playlist', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({files: files, name: name})
            });

            const result = await response.json();

            document.getElementById('saveBtn').textContent = 'Save to Drive';
            document.getElementById('saveBtn').disabled = false;

            if (result.success) {
                alert('Playlist saved to Google Drive!\\n\\nOn mobile:\\n1. Open VLC\\n2. Go to Network > Cloud Services > Google Drive\\n3. Find "' + name + '.m3u" and open it');
            } else {
                alert('Error: ' + result.error);
            }
        }

        function setMode(mode) {
            playMode = mode;
            document.getElementById('streamBtn').classList.toggle('active', mode === 'stream');
            document.getElementById('downloadBtn').classList.toggle('active', mode === 'download');
        }

        async function play() {
            const files = Array.from(selectedFiles.values());
            if (files.length === 0) return;

            document.getElementById('playBtn').textContent = 'Starting...';
            document.getElementById('playBtn').disabled = true;

            const response = await fetch('/api/play', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({files: files, mode: playMode})
            });

            const result = await response.json();

            document.getElementById('playBtn').textContent = '▶ Play';
            document.getElementById('playBtn').disabled = false;

            if (!result.success) {
                alert('Error: ' + result.error);
            }
        }

        // Initial load
        loadUserInfo();
        loadFiles();
    </script>
</body>
</html>
"""


def authenticate():
    """Authenticate with Google Drive API."""
    creds = None
    USER_DATA_DIR.mkdir(exist_ok=True)

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print("❌ Missing credentials.json file!")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0, prompt='select_account')

        TOKEN_FILE.write_text(creds.to_json())

    return build('drive', 'v3', credentials=creds)


def format_size(size_bytes):
    """Format file size for display."""
    if not size_bytes:
        return ""
    size = int(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, version=VERSION)


@app.route('/api/files')
def api_files():
    folder_id = request.args.get('folder') or None
    shared = request.args.get('shared') == 'true'

    # Get folders
    folder_query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
    if folder_id:
        folder_query += f" and '{folder_id}' in parents"
    elif shared:
        folder_query += " and sharedWithMe=true"

    folders_result = drive_service.files().list(
        q=folder_query,
        pageSize=50,
        fields="files(id, name)",
        orderBy="name",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    # Get audio files
    mime_query = " or ".join([f"mimeType='{m}'" for m in AUDIO_MIMETYPES])
    file_query = f"({mime_query}) and trashed=false"
    if folder_id:
        file_query += f" and '{folder_id}' in parents"
    elif shared:
        file_query += " and sharedWithMe=true"

    files_result = drive_service.files().list(
        q=file_query,
        pageSize=100,
        fields="files(id, name, mimeType, size)",
        orderBy="name",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    folders = [{'id': f['id'], 'name': f['name']} for f in folders_result.get('files', [])]
    files = [{'id': f['id'], 'name': f['name'], 'size': format_size(f.get('size'))}
             for f in files_result.get('files', [])]

    return jsonify({'folders': folders, 'files': files})


@app.route('/api/user')
def api_user():
    return jsonify({'email': user_email or 'Unknown'})


@app.route('/api/shared-drives')
def api_shared_drives():
    """List all shared drives the user has access to."""
    try:
        results = drive_service.drives().list(
            pageSize=50,
            fields="drives(id, name)"
        ).execute()

        drives = [{'id': d['id'], 'name': d['name']} for d in results.get('drives', [])]
        return jsonify({'drives': drives})
    except Exception as e:
        return jsonify({'drives': [], 'error': str(e)})


@app.route('/api/folder-info')
def api_folder_info():
    """Get folder name by ID."""
    folder_id = request.args.get('id')
    if not folder_id:
        return jsonify({'error': 'No folder ID provided'})

    try:
        folder = drive_service.files().get(
            fileId=folder_id,
            fields='id, name',
            supportsAllDrives=True
        ).execute()
        return jsonify({'id': folder['id'], 'name': folder['name']})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return jsonify({'success': True, 'message': 'Logged out'})


@app.route('/api/switch-account', methods=['POST'])
def api_switch_account():
    """Clear token and restart server to re-authenticate."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()

    def restart():
        import time
        time.sleep(0.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=restart, daemon=True).start()
    return jsonify({'success': True, 'message': 'Restarting...'})


@app.route('/api/all-audio')
def api_all_audio():
    """Get all audio files with their folder paths."""
    mime_query = " or ".join([f"mimeType='{m}'" for m in AUDIO_MIMETYPES])
    file_query = f"({mime_query}) and trashed=false"

    files_result = drive_service.files().list(
        q=file_query,
        pageSize=500,
        fields="files(id, name, mimeType, size, parents)",
        orderBy="name"
    ).execute()

    # Get folder names for paths
    folder_cache = {}

    def get_folder_path(file_info):
        parents = file_info.get('parents', [])
        if not parents:
            return ''

        parent_id = parents[0]
        if parent_id in folder_cache:
            return folder_cache[parent_id]

        try:
            folder = drive_service.files().get(fileId=parent_id, fields='name').execute()
            path = folder.get('name', '')
            folder_cache[parent_id] = path
            return path
        except:
            return ''

    files = []
    for f in files_result.get('files', []):
        files.append({
            'id': f['id'],
            'name': f['name'],
            'size': format_size(f.get('size')),
            'path': get_folder_path(f)
        })

    return jsonify({'files': files})


@app.route('/api/search')
def api_search():
    """Search for audio files and folders by name."""
    query = request.args.get('q', '')
    folder_id = request.args.get('folder', '')

    if not query:
        return jsonify({'files': [], 'folders': []})

    folder_cache = {}

    def get_folder_path(file_info):
        parents = file_info.get('parents', [])
        if not parents:
            return ''
        parent_id = parents[0]
        if parent_id in folder_cache:
            return folder_cache[parent_id]
        try:
            folder = drive_service.files().get(fileId=parent_id, fields='name', supportsAllDrives=True).execute()
            path = folder.get('name', '')
            folder_cache[parent_id] = path
            return path
        except:
            return ''

    # If searching within a specific folder, search recursively
    if folder_id:
        # Search for files within this folder and subfolders
        all_files = []
        all_folders = []

        def search_in_folder(fid, depth=0):
            if depth > 5:  # Limit recursion depth
                return

            # Get audio files in this folder matching query
            mime_query = " or ".join([f"mimeType='{m}'" for m in AUDIO_MIMETYPES])
            file_query = f"({mime_query}) and trashed=false and '{fid}' in parents and name contains '{query}'"

            try:
                files_result = drive_service.files().list(
                    q=file_query,
                    pageSize=100,
                    fields="files(id, name, mimeType, size, parents)",
                    orderBy="name",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                for f in files_result.get('files', []):
                    all_files.append({
                        'id': f['id'],
                        'name': f['name'],
                        'size': format_size(f.get('size')),
                        'path': get_folder_path(f)
                    })
            except:
                pass

            # Get subfolders and search them too
            subfolder_query = f"mimeType='application/vnd.google-apps.folder' and trashed=false and '{fid}' in parents"
            try:
                subfolders_result = drive_service.files().list(
                    q=subfolder_query,
                    pageSize=50,
                    fields="files(id, name, parents)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                for sf in subfolders_result.get('files', []):
                    # Check if folder name matches query
                    if query.lower() in sf['name'].lower():
                        all_folders.append({
                            'id': sf['id'],
                            'name': sf['name'],
                            'path': get_folder_path(sf)
                        })
                    # Recursively search subfolders
                    search_in_folder(sf['id'], depth + 1)
            except:
                pass

        search_in_folder(folder_id)
        return jsonify({'files': all_files, 'folders': all_folders})

    # Global search (original behavior)
    # Search folders
    folder_query = f"mimeType='application/vnd.google-apps.folder' and trashed=false and name contains '{query}'"
    folders_result = drive_service.files().list(
        q=folder_query,
        pageSize=50,
        fields="files(id, name, parents)",
        orderBy="name",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    folders = [{'id': f['id'], 'name': f['name'], 'path': get_folder_path(f)}
               for f in folders_result.get('files', [])]

    # Search audio files
    mime_query = " or ".join([f"mimeType='{m}'" for m in AUDIO_MIMETYPES])
    file_query = f"({mime_query}) and trashed=false and name contains '{query}'"

    files_result = drive_service.files().list(
        q=file_query,
        pageSize=100,
        fields="files(id, name, mimeType, size, parents)",
        orderBy="name",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    files = [{'id': f['id'], 'name': f['name'], 'size': format_size(f.get('size')),
              'path': get_folder_path(f)} for f in files_result.get('files', [])]

    return jsonify({'files': files, 'folders': folders})


@app.route('/api/save-playlist', methods=['POST'])
def api_save_playlist():
    """Save playlist as M3U file to Google Drive."""
    from googleapiclient.http import MediaInMemoryUpload

    data = request.json
    files = data.get('files', [])
    name = data.get('name', 'My Playlist')

    if not files:
        return jsonify({'success': False, 'error': 'No files selected'})

    try:
        # Create M3U content with Google Drive URLs that VLC can stream
        m3u_content = "#EXTM3U\n"
        for f in files:
            m3u_content += f"#EXTINF:-1,{f['name']}\n"
            # Use direct download URL format
            m3u_content += f"https://drive.google.com/uc?export=download&id={f['id']}\n"

        # Upload to Google Drive
        file_metadata = {
            'name': f'{name}.m3u',
            'mimeType': 'audio/x-mpegurl'
        }

        media = MediaInMemoryUpload(
            m3u_content.encode('utf-8'),
            mimetype='audio/x-mpegurl',
            resumable=False
        )

        uploaded = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink'
        ).execute()

        return jsonify({
            'success': True,
            'fileId': uploaded.get('id'),
            'fileName': uploaded.get('name'),
            'link': uploaded.get('webViewLink')
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/play', methods=['POST'])
def api_play():
    data = request.json
    files = data.get('files', [])
    mode = data.get('mode', 'stream')
    playlist_name = data.get('name', 'Google Drive Playlist')

    if not files:
        return jsonify({'success': False, 'error': 'No files selected'})

    # Sanitize playlist name for filename
    safe_name = "".join(c for c in playlist_name if c.isalnum() or c in ' -_').strip() or 'playlist'

    try:
        if mode == 'download':
            # Save downloads in a subfolder named after the playlist
            playlist_download_dir = PLAYLISTS_DIR / safe_name
            playlist_download_dir.mkdir(parents=True, exist_ok=True)
            local_paths = []

            for f in files:
                dest_path = playlist_download_dir / f['name']
                if not dest_path.exists():
                    request_dl = drive_service.files().get_media(fileId=f['id'])
                    with open(dest_path, 'wb') as file:
                        downloader = MediaIoBaseDownload(file, request_dl)
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                local_paths.append(str(dest_path))

            # Create playlist with name in persistent directory
            PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
            playlist_path = PLAYLISTS_DIR / f"{safe_name}.m3u"
            with open(playlist_path, 'w') as pf:
                pf.write("#EXTM3U\n")
                pf.write(f"#PLAYLIST:{playlist_name}\n")
                for i, f in enumerate(files):
                    pf.write(f"#EXTINF:-1,{f['name']}\n")
                    pf.write(f"{local_paths[i]}\n")
        else:
            # Stream mode - save to persistent directory
            PLAYLISTS_DIR.mkdir(exist_ok=True)
            playlist_path = PLAYLISTS_DIR / f"{safe_name}.m3u"
            with open(playlist_path, 'w') as pf:
                pf.write("#EXTM3U\n")
                pf.write(f"#PLAYLIST:{playlist_name}\n")
                for f in files:
                    pf.write(f"#EXTINF:-1,{f['name']}\n")
                    pf.write(f"https://drive.google.com/uc?export=download&id={f['id']}\n")

        # Try VLC first, fall back to system default player
        vlc_paths = [
            '/Applications/VLC.app/Contents/MacOS/VLC',
            '/usr/bin/vlc',
            'vlc'
        ]

        vlc_cmd = None
        for path in vlc_paths:
            if path == 'vlc':
                # Check if vlc is in PATH
                import shutil
                if shutil.which('vlc'):
                    vlc_cmd = path
                    break
            elif os.path.exists(path):
                vlc_cmd = path
                break

        if vlc_cmd:
            subprocess.Popen([vlc_cmd, '--loop', str(playlist_path)])
            return jsonify({'success': True, 'player': 'VLC'})
        else:
            # Fall back to system default player
            import platform
            system = platform.system()
            if system == 'Darwin':  # macOS
                subprocess.Popen(['open', str(playlist_path)])
                return jsonify({'success': True, 'player': 'default'})
            elif system == 'Windows':
                os.startfile(str(playlist_path))
                return jsonify({'success': True, 'player': 'default'})
            else:  # Linux
                subprocess.Popen(['xdg-open', str(playlist_path)])
                return jsonify({'success': True, 'player': 'default'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/open-playlists-folder')
def api_open_playlists_folder():
    """Open the playlists folder in Finder."""
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(['open', str(PLAYLISTS_DIR)])
    return jsonify({'success': True, 'path': str(PLAYLISTS_DIR)})


@app.route('/api/open-downloads-folder')
def api_open_downloads_folder():
    """Open the downloads folder in Finder."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(['open', str(DOWNLOAD_DIR)])
    return jsonify({'success': True, 'path': str(DOWNLOAD_DIR)})


def find_free_port(start_port=5050, max_attempts=100):
    """Find an available port starting from start_port."""
    import socket
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"Could not find a free port in range {start_port}-{start_port + max_attempts}")


def check_existing_server(start_port=5050, max_attempts=20):
    """Check if our server is already running on any port."""
    import socket
    import urllib.request
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                result = s.connect_ex(('127.0.0.1', port))
                if result == 0:
                    # Port is open, check if it's our app
                    try:
                        req = urllib.request.urlopen(f'http://localhost:{port}/api/user', timeout=2)
                        if req.status == 200:
                            return port
                    except:
                        pass
        except:
            pass
    return None


def kill_stale_instances():
    """Kill any stale GDrive Player server instances."""
    import signal
    try:
        # Only kill Python processes running this specific script
        script_name = os.path.basename(__file__)
        result = subprocess.run(
            ['pgrep', '-f', f'python.*{script_name}'],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            my_pid = str(os.getpid())
            for pid in pids:
                if pid and pid != my_pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except:
                        pass
            # Wait a moment for processes to die
            import time
            time.sleep(1)
    except:
        pass


# Global to store the chosen port
server_port = 5050


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    import signal
    import platform

    def signal_handler(signum, frame):
        print("\n🛑 Shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    # SIGTERM only exists on Unix
    if platform.system() != 'Windows':
        signal.signal(signal.SIGTERM, signal_handler)


def open_browser():
    """Open browser after short delay."""
    import time
    time.sleep(1)
    webbrowser.open(f'http://localhost:{server_port}')


def get_user_email(creds):
    """Get the user's email from Google."""
    try:
        oauth2_service = build('oauth2', 'v2', credentials=creds)
        user_info = oauth2_service.userinfo().get().execute()
        return user_info.get('email', 'Unknown')
    except:
        return 'Unknown'


def main():
    global drive_service, user_email, server_port

    # Set up signal handlers for graceful shutdown (fixes macOS shutdown hang)
    setup_signal_handlers()

    # Check if already running with a healthy server
    existing_port = check_existing_server()
    if existing_port:
        print("🎵 Google Drive Audio Player")
        print("=" * 40)
        print(f"✅ Already running on port {existing_port}")
        print("🌐 Opening browser...")
        webbrowser.open(f'http://localhost:{existing_port}')
        return

    # No healthy server found - kill any stale instances
    kill_stale_instances()

    print("🎵 Google Drive Audio Player")
    print("=" * 40)
    print("🔐 Authenticating...")

    creds = None
    USER_DATA_DIR.mkdir(exist_ok=True)

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print("❌ Missing credentials.json file!")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0, prompt='select_account')

        TOKEN_FILE.write_text(creds.to_json())

    drive_service = build('drive', 'v3', credentials=creds)
    user_email = get_user_email(creds)

    print(f"✅ Connected as {user_email}!")
    print("🌐 Opening browser...")

    # Find an available port
    global server_port
    server_port = find_free_port()

    # Open browser in background thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Start Flask server
    print(f"   http://localhost:{server_port}")
    print("\nPress Ctrl+C to quit\n")
    app.run(port=server_port, debug=False)


if __name__ == '__main__':
    main()
