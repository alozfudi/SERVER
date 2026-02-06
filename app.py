import sys
import subprocess
import threading
import time
import os
import json
import sqlite3
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

# --- 1. AUTO INSTALL REQUIRED PACKAGES ---
def install_package(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import streamlit as st
    import psutil   # Monitor RAM
    import requests # Download biasa
    import gdown    # Download Google Drive
except ImportError:
    install_package("streamlit")
    install_package("psutil")
    install_package("requests")
    install_package("gdown")
    import streamlit as st
    import psutil
    import requests
    import gdown

try:
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-auth", "google-auth-oauthlib", "google-api-python-client"])
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow

# Predefined OAuth configuration
PREDEFINED_OAUTH_CONFIG = {
    "web": {
        "client_id": "1086578184958-hin4d45sit9ma5psovppiq543eho41sl.apps.googleusercontent.com",
        "project_id": "anjelikakozme",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "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",
        "redirect_uris": ["https://livenews1x.streamlit.app"]
    }
}

# --- DATABASE FUNCTIONS ---
def init_database():
    try:
        db_path = Path("streaming_logs.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streaming_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                log_type TEXT NOT NULL,
                message TEXT NOT NULL,
                video_file TEXT,
                stream_key TEXT,
                channel_name TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streaming_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                video_file TEXT,
                stream_title TEXT,
                stream_description TEXT,
                tags TEXT,
                category TEXT,
                privacy_status TEXT,
                made_for_kids BOOLEAN,
                channel_name TEXT,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT UNIQUE NOT NULL,
                channel_id TEXT NOT NULL,
                auth_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Database initialization error: {e}")

def save_channel_auth(channel_name, channel_id, auth_data):
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO saved_channels 
            (channel_name, channel_id, auth_data, created_at, last_used)
            VALUES (?, ?, ?, ?, ?)
        ''', (channel_name, channel_id, json.dumps(auth_data), datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return False

def load_saved_channels():
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        cursor.execute('SELECT channel_name, channel_id, auth_data, last_used FROM saved_channels ORDER BY last_used DESC')
        channels = [{'name': row[0], 'id': row[1], 'auth': json.loads(row[2]), 'last_used': row[3]} for row in cursor.fetchall()]
        conn.close()
        return channels
    except Exception as e:
        return []

def update_channel_last_used(channel_name):
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        cursor.execute('UPDATE saved_channels SET last_used = ? WHERE channel_name = ?', (datetime.now().isoformat(), channel_name))
        conn.commit()
        conn.close()
    except: pass

def log_to_database(session_id, log_type, message, video_file=None, stream_key=None, channel_name=None):
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO streaming_logs (timestamp, session_id, log_type, message, video_file, stream_key, channel_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), session_id, log_type, message, video_file, stream_key, channel_name))
        conn.commit()
        conn.close()
    except: pass

def get_logs_from_database(session_id=None, limit=100):
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        if session_id:
            cursor.execute('SELECT timestamp, log_type, message, video_file, channel_name FROM streaming_logs WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?', (session_id, limit))
        else:
            cursor.execute('SELECT timestamp, log_type, message, video_file, channel_name FROM streaming_logs ORDER BY timestamp DESC LIMIT ?', (limit,))
        logs = cursor.fetchall()
        conn.close()
        return logs
    except: return []

def save_streaming_session(session_id, video_file, stream_title, stream_description, tags, category, privacy_status, made_for_kids, channel_name):
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO streaming_sessions (session_id, start_time, video_file, stream_title, stream_description, tags, category, privacy_status, made_for_kids, channel_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (session_id, datetime.now().isoformat(), video_file, stream_title, stream_description, tags, category, privacy_status, made_for_kids, channel_name))
        conn.commit()
        conn.close()
    except: pass

# --- AUTH HELPER FUNCTIONS ---
def load_google_oauth_config(json_file):
    try:
        config = json.load(json_file)
        return config.get('web') or config.get('installed')
    except: return None

def generate_auth_url(client_config):
    scopes = ['https://www.googleapis.com/auth/youtube.force-ssl']
    return (f"{client_config['auth_uri']}?client_id={client_config['client_id']}&"
            f"redirect_uri={urllib.parse.quote(client_config['redirect_uris'][0])}&"
            f"scope={urllib.parse.quote(' '.join(scopes))}&response_type=code&access_type=offline&prompt=consent")

def exchange_code_for_tokens(client_config, auth_code):
    try:
        token_data = {
            'client_id': client_config['client_id'],
            'client_secret': client_config['client_secret'],
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': client_config['redirect_uris'][0]
        }
        response = requests.post(client_config['token_uri'], data=token_data)
        return response.json() if response.status_code == 200 else None
    except: return None

def load_channel_config(json_file):
    try: return json.load(json_file)
    except: return None

def validate_channel_config(config):
    if 'channels' not in config: return False, "Missing 'channels'"
    if not isinstance(config['channels'], list): return False, "Channels must be list"
    return True, "Valid"

def create_youtube_service(credentials_dict):
    try:
        if 'token' in credentials_dict:
            credentials = Credentials.from_authorized_user_info(credentials_dict)
        else:
            credentials = Credentials(
                token=credentials_dict.get('access_token'),
                refresh_token=credentials_dict.get('refresh_token'),
                token_uri=credentials_dict.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=credentials_dict.get('client_id'),
                client_secret=credentials_dict.get('client_secret'),
                scopes=['https://www.googleapis.com/auth/youtube.force-ssl']
            )
        return build('youtube', 'v3', credentials=credentials)
    except: return None

# --- YOUTUBE API FUNCTIONS ---
def get_stream_key_only(service):
    try:
        req = service.liveStreams().insert(
            part="snippet,cdn",
            body={
                "snippet": {"title": f"KeyGen-{datetime.now().strftime('%H%M%S')}"},
                "cdn": {"resolution": "1080p", "frameRate": "30fps", "ingestionType": "rtmp"}
            }
        )
        resp = req.execute()
        return {
            "stream_key": resp['cdn']['ingestionInfo']['streamName'],
            "stream_url": resp['cdn']['ingestionInfo']['ingestionAddress'],
            "stream_id": resp['id']
        }
    except Exception as e:
        st.error(f"Error getting stream key: {e}")
        return None

def get_channel_info(service, channel_id=None):
    try:
        if channel_id:
            req = service.channels().list(part="snippet,statistics", id=channel_id)
        else:
            req = service.channels().list(part="snippet,statistics", mine=True)
        return req.execute().get('items', [])
    except: return []

def create_live_stream(service, title, description, scheduled_time, tags=None, category_id="20", privacy="public", made_for_kids=False):
    try:
        # 1. Stream
        s_body = {
            "snippet": {"title": f"{title} - Stream"},
            "cdn": {"resolution": "1080p", "frameRate": "30fps", "ingestionType": "rtmp"}
        }
        s_resp = service.liveStreams().insert(part="snippet,cdn", body=s_body).execute()
        
        # 2. Broadcast
        b_body = {
            "snippet": {
                "title": title,
                "description": description,
                "scheduledStartTime": scheduled_time.isoformat(),
                "tags": tags or [],
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": made_for_kids,
                "enableAutoStart": True,
                "enableAutoStop": True
            },
            "contentDetails": {
                "enableAutoStart": True, 
                "enableAutoStop": True, 
                "enableDvr": True
            }
        }
        b_resp = service.liveBroadcasts().insert(part="snippet,status,contentDetails", body=b_body).execute()
        
        # 3. Bind
        service.liveBroadcasts().bind(
            part="id,contentDetails",
            id=b_resp['id'],
            streamId=s_resp['id']
        ).execute()
        
        return {
            "stream_key": s_resp['cdn']['ingestionInfo']['streamName'],
            "stream_url": s_resp['cdn']['ingestionInfo']['ingestionAddress'],
            "broadcast_id": b_resp['id'],
            "stream_id": s_resp['id'],
            "watch_url": f"https://www.youtube.com/watch?v={b_resp['id']}",
            "studio_url": f"https://studio.youtube.com/video/{b_resp['id']}/livestreaming",
            "broadcast_response": b_resp
        }
    except Exception as e:
        st.error(f"Error creating live stream: {e}")
        return None

def get_existing_broadcasts(service, max_results=10):
    try:
        req = service.liveBroadcasts().list(part="snippet,status,contentDetails", mine=True, maxResults=max_results, broadcastStatus="all")
        return req.execute().get('items', [])
    except: return []

def get_broadcast_stream_key(service, broadcast_id):
    try:
        b_resp = service.liveBroadcasts().list(part="contentDetails", id=broadcast_id).execute()
        if not b_resp['items']: return None
        stream_id = b_resp['items'][0]['contentDetails'].get('boundStreamId')
        if not stream_id: return None
        
        s_resp = service.liveStreams().list(part="cdn", id=stream_id).execute()
        if s_resp['items']:
            info = s_resp['items'][0]['cdn']['ingestionInfo']
            return {"stream_key": info['streamName'], "stream_url": info['ingestionAddress'], "stream_id": stream_id}
        return None
    except: return None

# --- OPTIMIZED FFMPEG (FIX LOADING SCREEN) ---
def run_ffmpeg(video_path, stream_key, is_shorts, log_callback, rtmp_url=None, session_id=None):
    output_url = rtmp_url or f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
    
    cmd = [
        "ffmpeg", 
        "-re", 
        "-stream_loop", "-1",  # Loop selamanya
        "-i", video_path,      # Input file
        
        # --- VIDEO SETTINGS ---
        "-c:v", "libx264",     # Codec Video
        "-preset", "ultrafast",# Prioritas kecepatan (biar CPU gak jebol)
        "-tune", "zerolatency",# Kurangi delay
        "-pix_fmt", "yuv420p", # <--- WAJIB! Agar YouTube bisa baca gambarnya
        "-r", "30",            # Paksa 30 FPS stabil
        "-g", "60",            # Keyframe tiap 2 detik (Wajib YouTube: 2 * 30fps = 60)
        "-b:v", "2000k",       # Bitrate 2000kbps (Cukup untuk 720p)
        "-maxrate", "2500k",   # Batas atas bitrate
        "-bufsize", "5000k",   # Buffer size
        
        # --- AUDIO SETTINGS ---
        "-c:a", "aac",         # Codec Audio
        "-b:a", "128k",        # Bitrate Audio
        "-ar", "44100",        # Sample Rate Standar
        
        # --- FORMAT OUTPUT ---
        "-f", "flv",           # Format FLV untuk RTMP
    ]
    
    # Skala Resolusi (Downscale ke 720p biar server kuat)
    if is_shorts:
         # Mode Shorts (Vertikal)
         cmd.extend(["-vf", "scale=-2:1280,crop=720:1280:0:0"]) 
    else:
         # Mode Landscape (720p)
         cmd.extend(["-vf", "scale=1280:-2"]) 

    cmd.append(output_url)
    
    start_msg = f"🚀 Starting FIX Stream (YUV420P) for {video_path}..."
    log_callback(start_msg)
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Baca log baris per baris
        for line in process.stdout:
            # Filter log biar tidak spam, tapi tampilkan error/frame
            if "frame=" in line or "Error" in line or "kb/s" in line: 
                log_callback(line.strip())
                
        process.wait()
        log_callback("✅ Streaming stopped")
        
    except Exception as e:
        log_callback(f"❌ FFmpeg Error: {e}")
    finally:
        log_callback("⏹️ Session ended")

def auto_process_auth_code():
    if 'code' in st.query_params:
        auth_code = st.query_params['code']
        if 'processed_codes' not in st.session_state: st.session_state['processed_codes'] = set()
        
        if auth_code not in st.session_state['processed_codes'] and 'oauth_config' in st.session_state:
            with st.spinner("Authenticating..."):
                tokens = exchange_code_for_tokens(st.session_state['oauth_config'], auth_code)
                if tokens:
                    st.session_state['processed_codes'].add(auth_code)
                    creds_dict = {
                        'access_token': tokens['access_token'],
                        'refresh_token': tokens.get('refresh_token'),
                        'token_uri': st.session_state['oauth_config']['token_uri'],
                        'client_id': st.session_state['oauth_config']['client_id'],
                        'client_secret': st.session_state['oauth_config']['client_secret']
                    }
                    service = create_youtube_service(creds_dict)
                    if service:
                        channels = get_channel_info(service)
                        if channels:
                            channel = channels[0]
                            st.session_state['youtube_service'] = service
                            st.session_state['channel_info'] = channel
                            save_channel_auth(channel['snippet']['title'], channel['id'], creds_dict)
                            st.success(f"✅ Connected: {channel['snippet']['title']}")
                            st.query_params.clear()
                            st.rerun()

def get_youtube_categories():
    return {
        "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals",
        "17": "Sports", "20": "Gaming", "22": "People & Blogs", "23": "Comedy",
        "24": "Entertainment", "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology"
    }

def auto_start_streaming(video_path, stream_key, is_shorts=False, custom_rtmp=None, session_id=None):
    if not video_path or not stream_key:
        st.error("❌ Video atau stream key tidak ditemukan!")
        return False
    
    st.session_state['streaming'] = True
    st.session_state['stream_start_time'] = datetime.now()
    st.session_state['live_logs'] = []
    
    def log_callback(msg):
        if 'live_logs' not in st.session_state: st.session_state['live_logs'] = []
        st.session_state['live_logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(st.session_state['live_logs']) > 100: st.session_state['live_logs'] = st.session_state['live_logs'][-100:]
    
    st.session_state['ffmpeg_thread'] = threading.Thread(
        target=run_ffmpeg, 
        args=(video_path, stream_key, is_shorts, log_callback, custom_rtmp or None, session_id), 
        daemon=True
    )
    st.session_state['ffmpeg_thread'].start()
    log_to_database(session_id, "INFO", f"Auto streaming started: {video_path}")
    return True

def auto_create_live_broadcast(service, use_custom_settings=True, custom_settings=None, session_id=None):
    try:
        with st.spinner("Creating auto YouTube Live broadcast..."):
            scheduled_time = datetime.now() + timedelta(seconds=30)
            default_settings = {
                'title': f"Auto Live Stream {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                'description': "Auto-generated live stream",
                'tags': [],
                'category_id': "20",
                'privacy_status': "public",
                'made_for_kids': False
            }
            settings = {**default_settings, **custom_settings} if (use_custom_settings and custom_settings) else default_settings
            
            live_info = create_live_stream(service, settings['title'], settings['description'], scheduled_time, settings['tags'], settings['category_id'], settings['privacy_status'], settings['made_for_kids'])
            
            if live_info:
                st.session_state['current_stream_key'] = live_info['stream_key']
                st.session_state['live_broadcast_info'] = live_info
                st.success("🎉 Broadcast Created!")
                log_to_database(session_id, "INFO", f"Live created: {live_info['watch_url']}")
                return live_info
            return None
    except Exception as e:
        st.error(f"Error: {e}")
        return None

# --- MAIN APP UI ---
def main():
    st.set_page_config(page_title="Advanced YouTube Live Streaming", page_icon="📺", layout="wide")
    init_database()
    
    if 'session_id' not in st.session_state:
        st.session_state['session_id'] = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if 'live_logs' not in st.session_state:
        st.session_state['live_logs'] = []
    
    st.title("🎥 Advanced YouTube Live Streaming Platform")
    st.markdown("---")
    auto_process_auth_code()
    
    # --- SIDEBAR ---
    with st.sidebar:
        st.header("📋 Configuration")
        
        # RAM MONITOR
        try:
            st.subheader("🖥️ Server Health")
            ram = psutil.virtual_memory()
            st.progress(ram.percent / 100)
            st.caption(f"RAM: {ram.percent}% ({ram.used/(1024**3):.1f} GB / {ram.total/(1024**3):.1f} GB)")
            if ram.percent > 90: st.error("⚠️ RAM CRITICAL!")
        except: pass

        st.info(f"🆔 Session: {st.session_state['session_id']}")
        
        # Saved Channels
        st.subheader("💾 Saved Channels")
        saved_channels = load_saved_channels()
        if saved_channels:
            for channel in saved_channels:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📺 {channel['name']}")
                    st.caption(f"Last: {channel['last_used'][:10]}")
                with col2:
                    if st.button("🔑 Use", key=f"use_{channel['name']}"):
                        service = create_youtube_service(channel['auth'])
                        if service and get_channel_info(service):
                            st.session_state['youtube_service'] = service
                            st.session_state['channel_info'] = get_channel_info(service)[0]
                            update_channel_last_used(channel['name'])
                            st.success("Loaded!")
                            st.rerun()
                        else: st.error("Expired")
        else: st.info("No saved channels.")
        
        # Google OAuth
        st.subheader("🔐 Google OAuth")
        if st.button("🚀 Quick Auth"):
            st.session_state['oauth_config'] = PREDEFINED_OAUTH_CONFIG['web']
            st.rerun()
            
        oauth_file = st.file_uploader("Upload JSON", type=['json'], key="oauth_upload")
        if oauth_file: st.session_state['oauth_config'] = load_google_oauth_config(oauth_file)
        
        if 'oauth_config' in st.session_state:
            auth_url = generate_auth_url(st.session_state['oauth_config'])
            st.markdown(f"[**👉 Authorize Here**]({auth_url})")
            auth_code = st.text_input("Paste Auth Code", type="password")
            if st.button("Verify Code"):
                st.query_params["code"] = auth_code
                st.rerun()

        # Config Upload
        st.subheader("📄 Config")
        json_file = st.file_uploader("Upload Config JSON", type=['json'])
        if json_file:
            config = load_channel_config(json_file)
            if config: st.session_state['channel_config'] = config

        # Logs
        st.markdown("---")
        if st.button("🗑️ Clear Logs"): st.session_state['live_logs'] = []
        if st.button("📥 Download Logs"):
            logs = "\n".join(st.session_state.get('live_logs', []))
            st.download_button("Save", logs, "logs.txt")

    # --- MAIN CONTENT ---
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("🎥 Video Source")
        
        # 1. Local Selection
        video_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv'))]
        selected_video = st.selectbox("Select Local Video", ["-- Select --"] + video_files)
        
        # 2. Smart Downloader (GDrive)
        st.markdown("---")
        st.write("🔗 **Smart Downloader (Google Drive 1GB+ Support):**")
        url_input = st.text_input("Paste URL (Direct/GDrive)", key="dl_url")
        if st.button("⬇️ Download ke Server"):
            if url_input:
                try:
                    with st.spinner("⏳ Mendownload file besar (menggunakan gdown)..."):
                        save_path = "downloaded_video.mp4"
                        gdrive_match = re.search(r'drive\.google\.com\/file\/d\/([a-zA-Z0-9_-]+)', url_input)
                        
                        if gdrive_match:
                            file_id = gdrive_match.group(1)
                            if os.path.exists(save_path): os.remove(save_path)
                            url = f'https://drive.google.com/uc?id={file_id}'
                            gdown.download(url, save_path, quiet=False, fuzzy=True)
                        else:
                            resp = requests.get(url_input, stream=True)
                            with open(save_path, 'wb') as f:
                                for chunk in resp.iter_content(chunk_size=1024*1024):
                                    if chunk: f.write(chunk)
                        
                        if os.path.exists(save_path):
                            sz = os.path.getsize(save_path)/(1024*1024)
                            st.success(f"✅ Download Sukses! Ukuran: {sz:.2f} MB")
                            st.rerun()
                        else: st.error("Gagal.")
                except Exception as e: st.error(f"Error: {e}")

        # 3. Manual Upload (Chunked)
        st.markdown("---")
        uploaded_file = st.file_uploader("Upload Manual (Max 200MB)", type=['mp4', 'mkv'])
        if uploaded_file:
            with st.spinner("Saving..."):
                with open(uploaded_file.name, "wb") as f:
                    while True:
                        chunk = uploaded_file.read(5*1024*1024)
                        if not chunk: break
                        f.write(chunk)
            st.success("Uploaded!")
            st.rerun()

        # Determine Active Video
        active_video = None
        if selected_video != "-- Select --": active_video = selected_video
        elif os.path.exists("downloaded_video.mp4"): active_video = "downloaded_video.mp4"
        elif uploaded_file: active_video = uploaded_file.name
        
        if active_video and os.path.exists(active_video):
            sz = os.path.getsize(active_video)/(1024*1024)
            st.success(f"🎬 Active: **{active_video}** ({sz:.2f} MB)")
            if sz < 1: st.warning("⚠️ File terlalu kecil (<1MB). Cek link Google Drive!")
        
        # YouTube Info
        if 'youtube_service' in st.session_state and 'channel_info' in st.session_state:
            st.markdown("---")
            st.subheader("📺 Connected Channel")
            ch = st.session_state['channel_info']
            c1, c2 = st.columns(2)
            c1.write(f"**Name:** {ch['snippet']['title']}")
            c2.write(f"**Subs:** {ch['statistics'].get('subscriberCount', 'Hidden')}")

            # Stream Settings
            st.subheader("⚙️ Live Settings")
            setting_mode = st.radio("Mode:", ["🔧 Manual", "⚡ Auto"], horizontal=True)
            
            if setting_mode == "🔧 Manual":
                with st.expander("📝 Edit Settings", expanded=True):
                    col_set1, col_set2 = st.columns(2)
                    with col_set1:
                        auto_stream_title = st.text_input("Title", f"Live Stream {datetime.now().strftime('%H:%M')}")
                        auto_privacy = st.selectbox("Privacy", ["public", "unlisted"])
                    with col_set2:
                        cats = get_youtube_categories()
                        cat_name = st.selectbox("Category", list(cats.values()), index=5)
                        cat_id = [k for k, v in cats.items() if v == cat_name][0]
                    
                    st.session_state['manual_settings'] = {
                        'title': auto_stream_title, 'description': "Live via Streamlit",
                        'tags': [], 'category_id': cat_id, 'privacy_status': auto_privacy, 'made_for_kids': False
                    }

            if st.button("🚀 Start Auto Stream", type="primary"):
                service = st.session_state['youtube_service']
                use_custom = (setting_mode == "🔧 Manual")
                custom_sets = st.session_state.get('manual_settings')
                
                live_info = auto_create_live_broadcast(service, use_custom, custom_sets, st.session_state['session_id'])
                if live_info and active_video:
                    auto_start_streaming(active_video, live_info['stream_key'], session_id=st.session_state['session_id'])
                    st.rerun()

            # 3 Big Buttons
            c_btn1, c_btn2, c_btn3 = st.columns(3)
            with c_btn1:
                if st.button("🔑 Get Stream Key"):
                    info = get_stream_key_only(st.session_state['youtube_service'])
                    if info:
                        st.session_state['current_stream_key'] = info['stream_key']
                        st.success("Key Generated!")
            
            with c_btn2:
                if st.button("🎬 Create Live"):
                    # Quick create
                    live_info = create_live_stream(st.session_state['youtube_service'], "Live Stream", "Desc", datetime.now()+timedelta(seconds=30), [], "20", "public", False)
                    if live_info:
                        st.session_state['live_broadcast_info'] = live_info
                        st.session_state['current_stream_key'] = live_info['stream_key']
                        st.success("Created!")
            
            with c_btn3:
                if st.button("📋 Existing Streams"):
                    broadcasts = get_existing_broadcasts(st.session_state['youtube_service'])
                    if broadcasts:
                        for b in broadcasts:
                            if st.button(f"Use: {b['snippet']['title']}", key=b['id']):
                                key_info = get_broadcast_stream_key(st.session_state['youtube_service'], b['id'])
                                if key_info:
                                    st.session_state['current_stream_key'] = key_info['stream_key']
                                    st.success(f"Selected: {b['snippet']['title']}")

    with col2:
        st.header("📊 Controls")
        
        # --- TAMBAHAN: Agar Stream Key Terlihat / Bisa Diisi Manual ---
        current_k = st.session_state.get('current_stream_key', '')
        stream_key_input = st.text_input("🔑 Stream Key", value=current_k, type="password", help="Otomatis terisi jika klik tombol di kiri, atau paste manual dari YouTube Studio.")
        
        # Simpan ke memori jika user mengubah isinya
        if stream_key_input:
            st.session_state['current_stream_key'] = stream_key_input
        # -------------------------------------------------------------

        streaming = st.session_state.get('streaming', False)
        if streaming:
            st.error("🔴 LIVE")
            if 'stream_start_time' in st.session_state:
                dur = datetime.now() - st.session_state['stream_start_time']
                st.write(f"Duration: {str(dur).split('.')[0]}")
        else:
            st.success("⚫ OFFLINE")

        # FORCE KILL BUTTON (PENTING)
        if st.button("💀 FORCE KILL FFMPEG", type="secondary"):
            os.system("pkill ffmpeg")
            st.session_state['streaming'] = False
            st.warning("All FFmpeg processes killed.")
            time.sleep(1)
            st.rerun()

        st.markdown("---")
        if st.button("▶️ Start Stream", type="primary", disabled=streaming):
            key = st.session_state.get('current_stream_key')
            if active_video and key:
                auto_start_streaming(active_video, key, session_id=st.session_state['session_id'])
                st.rerun()
            else: st.error("No Video or Key!")

        if st.button("⏹️ Stop Stream", disabled=not streaming):
            st.session_state['streaming'] = False
            os.system("pkill ffmpeg")
            st.rerun()

        # Logs
        st.markdown("---")
        st.subheader("Logs")
        logs_text = "\n".join(st.session_state.get('live_logs', [])[-20:])
        st.text_area("Live Output", logs_text, height=300)
        if st.checkbox("Auto-refresh Logs", value=streaming):
            time.sleep(2)
            st.rerun()

if __name__ == '__main__':
    main()
