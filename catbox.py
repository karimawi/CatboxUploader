import argparse
import mimetypes
import os
import sys
import time
import traceback
import winreg
import sqlite3
import shutil
import json
import lzstring
from thumb import generate_thumbnail
from history_viewer import log_upload
import pythoncom
import requests
import PIL.Image as Image
from PyQt6.QtCore import (Qt, QThread, QTimer, pyqtSignal,
                          pyqtSlot)
from PyQt6.QtGui import QIcon, QImage, QPixmap, QAction, QCursor
from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QInputDialog,
                             QLabel, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QTextEdit, QVBoxLayout, QWidget, QMenu)
from requests_toolbelt.multipart.encoder import (MultipartEncoder,
                                                 MultipartEncoderMonitor)

class UploadCancelledException(Exception):
    """Exception raised when upload is cancelled."""
    pass

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    base_path = sys._MEIPASS
    os.environ['TCL_LIBRARY'] = os.path.join(base_path, 'tcl')
    os.environ['TK_LIBRARY'] = os.path.join(base_path, 'tk')
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

ico_path = os.path.join(application_path, "icons", "icon.ico")

REG_PATH = r"Software\CatboxUploader"

# Colors for dark/light theme
dark_theme_colors = {
    "border": "#606060",
    "bg": "#2D2D2D",
    "text": "white",
    "chunk": "#697DA0",
    "chunk_pressed": "#50688A"
}

light_theme_colors = {
    "border": "#c0c0c0",
    "bg": "#ffffff",
    "text": "#000000",
    "chunk": "#8E9EBB",
    "chunk_pressed": "#7A91B1"
}

# API Endpoints
API_CATBOX = "https://catbox.moe/user/api.php"
API_LITTERBOX = "https://litterbox.catbox.moe/resources/internals/api.php"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

def read_registry_value(name):
    """Read a value from Windows Registry under HKEY_CURRENT_USER."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except FileNotFoundError:
        return None

def write_registry_value(name, value):
    """Write a value to Windows Registry under HKEY_CURRENT_USER."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except Exception as e:
        app.setWindowIcon(QIcon(ico_path))
        QMessageBox.critical(None, "Registry Error", f"Failed to save to registry:\n{str(e)}")

def is_windows_light_mode() -> bool:
    """Checks if the current Windows theme is light mode.
    
    Returns:
        A bool based off if Windows is using light mode
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 1
    except Exception:
        # Default to dark mode
        return False

def get_themed_icon_filename(icon_name: str) -> str:
    """Get the themed icon filename based on current Windows theme.
    
    Args:
        icon_name: Base icon filename (e.g., 'upload_user.ico')
    
    Returns:
        The appropriate icon filename for the current theme
    """
    # Icons that have light variants
    light_variant_icons = ['upload_user', 'upload_anon', 'edit_userhash', 'history']
    
    use_light = is_windows_light_mode()
    
    # Extract base name without extension
    base_name = icon_name.replace('.ico', '')
    
    if use_light and base_name in light_variant_icons:
        light_icon = f"{base_name}_light.ico"
        # Check if light variant exists
        if os.path.exists(os.path.join(icons_dir, light_icon)):
            return light_icon
    
    return icon_name

def prompt_for_userhash():
    """Show a Qt input dialog to enter and save userhash."""
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ico_path))
    userhash, ok = QInputDialog.getText(None, "Enter User Hash", "Enter your Catbox userhash:")
    
    if ok and userhash.strip():
        write_registry_value("userhash", userhash.strip())
        return userhash.strip()
    elif ok and not userhash.strip():
        app.setWindowIcon(QIcon(ico_path))
        QMessageBox.critical(None, "Error", "User hash cannot be empty.")
        return prompt_for_userhash()

    os._exit(0)  # Exit if user cancels

# Parse CLI arguments
parser = argparse.ArgumentParser(description="Upload files to Catbox or Litterbox.")
parser.add_argument("file", nargs="?", help="Path to the file to upload.")
parser.add_argument("--anonymous", action="store_true", help="Upload anonymously (no user hash).")
parser.add_argument("--litterbox", choices=["1h", "12h", "24h", "72h"], help="Litterbox with specified expiration time.")
parser.add_argument("--edit-userhash", action="store_true", help="Edit and save a new userhash.")
parser.add_argument("--history", action="store_true", help="Show upload history")

args = parser.parse_args()

cwd = os.getcwd()
icons_dir = os.path.join(application_path, "icons")
icon_path = f'"{icons_dir}\\icon.ico"'

CONTEXT_MENU_KEYS = [
    (r"Software\Classes\*\shell\Catbox", "Catbox", True, icon_path),

    # Ordered sub-items with individual icons
    (r"Software\Classes\*\shell\Catbox\shell\001_upload_user", "Upload as User", False, "upload_user.ico"),
    (r"Software\Classes\*\shell\Catbox\shell\001_upload_user\command", f'"{application_path}\\catbox.exe" "%1"', False, None),

    (r"Software\Classes\*\shell\Catbox\shell\002_upload_anon", "Upload anonymously", False, "upload_anon.ico"),
    (r"Software\Classes\*\shell\Catbox\shell\002_upload_anon\command", f'"{application_path}\\catbox.exe" --anonymous "%1"', False, None),

    (r"Software\Classes\*\shell\Catbox\shell\003_edit_userhash", "Edit userhash", False, "edit_userhash.ico"),
    (r"Software\Classes\*\shell\Catbox\shell\003_edit_userhash\command", f'"{application_path}\\catbox.exe" --edit-userhash', False, None),
    
    (r"Software\Classes\*\shell\Catbox\shell\004_history", "Upload History", False, "history.ico"),
    (r"Software\Classes\*\shell\Catbox\shell\004_history\command", f'"{application_path}\\catbox.exe" --history', False, None),

    (r"Software\Classes\*\shell\Litterbox", "Litterbox", True, icon_path),
    
    # Litterbox items without custom icons (will use default system icons)
    (r"Software\Classes\*\shell\Litterbox\shell\001_litterbox_1h", "1h", False, None),
    (r"Software\Classes\*\shell\Litterbox\shell\001_litterbox_1h\command", f'"{application_path}\\catbox.exe" --litterbox 1h "%1"', False, None),

    (r"Software\Classes\*\shell\Litterbox\shell\002_litterbox_12h", "12h", False, None),
    (r"Software\Classes\*\shell\Litterbox\shell\002_litterbox_12h\command", f'"{application_path}\\catbox.exe" --litterbox 12h "%1"', False, None),

    (r"Software\Classes\*\shell\Litterbox\shell\003_litterbox_24h", "24h", False, None),
    (r"Software\Classes\*\shell\Litterbox\shell\003_litterbox_24h\command", f'"{application_path}\\catbox.exe" --litterbox 24h "%1"', False, None),

    (r"Software\Classes\*\shell\Litterbox\shell\004_litterbox_72h", "72h", False, None),
    (r"Software\Classes\*\shell\Litterbox\shell\004_litterbox_72h\command", f'"{application_path}\\catbox.exe" --litterbox 72h "%1"', False, None),
]

def check_registry_keys():
    """Check if all context menu registry keys exist and have the correct values."""
    missing_or_incorrect_keys = []

    for entry in CONTEXT_MENU_KEYS:
        key_path, value, is_parent = entry[:3]
        icon_file = entry[3] if len(entry) > 3 else None
        
        # Get themed icon filename if icon is specified
        if icon_file and not icon_file.startswith('"'):
            icon_file = get_themed_icon_filename(icon_file)
        
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                if "command" in key_path:
                    # For command keys, check if the value matches the current executable path
                    current_value, _ = winreg.QueryValueEx(key, "")
                    if current_value != value:
                        missing_or_incorrect_keys.append((key_path, value, is_parent, icon_file))
                else:
                    # For non-command keys, check if the MUIVerb value matches
                    current_value, _ = winreg.QueryValueEx(key, "MUIVerb")
                    if current_value != value:
                        missing_or_incorrect_keys.append((key_path, value, is_parent, icon_file))
                    
                    # Check icon if specified
                    if icon_file:
                        try:
                            icon_path_full = f'"{os.path.join(icons_dir, icon_file)}"'
                            current_icon, _ = winreg.QueryValueEx(key, "Icon")
                            if current_icon != icon_path_full:
                                missing_or_incorrect_keys.append((key_path, value, is_parent, icon_file))
                        except FileNotFoundError:
                            missing_or_incorrect_keys.append((key_path, value, is_parent, icon_file))
                            
        except FileNotFoundError:
            # If the key doesn't exist, add it to the list of missing keys
            missing_or_incorrect_keys.append((key_path, value, is_parent, icon_file))

    return not missing_or_incorrect_keys  # True if no keys are missing or incorrect

def add_registry_keys():
    """Add or update context menu registry keys."""
    try:
        for entry in CONTEXT_MENU_KEYS:
            key_path, value, is_parent = entry[:3]
            icon_file = entry[3] if len(entry) > 3 else None
            
            # Get themed icon filename if icon is specified (skip already-quoted full paths)
            if icon_file and not icon_file.startswith('"'):
                icon_file = get_themed_icon_filename(icon_file)
            
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                if "command" in key_path:
                    # For command keys, set the value to the current executable path
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
                else:
                    # For non-command keys, set the MUIVerb value
                    winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, value)
                    
                    # Set icon if specified
                    if icon_file:
                        # Handle both full paths (quoted) and relative icon filenames
                        if icon_file.startswith('"'):
                            icon_path_full = icon_file
                            icon_exists = os.path.exists(icon_file.strip('"'))
                        else:
                            icon_path_full = f'"{os.path.join(icons_dir, icon_file)}"'
                            icon_exists = os.path.exists(os.path.join(icons_dir, icon_file))
                        
                        # Verify icon file exists before setting
                        if icon_exists:
                            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path_full)
                        else:
                            # Fallback to main icon if specific icon doesn't exist
                            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
                    
                    if is_parent:
                        winreg.SetValueEx(key, "SubCommands", 0, winreg.REG_SZ, "")
        return True
    except Exception as e:
        if QApplication.instance():
            app.setWindowIcon(QIcon(ico_path))
            QMessageBox.critical(None, "Registry Error", f"Failed to add/update context menu:\n{str(e)}")
        return False

def main():
    """Main function to check or add/update registry keys."""
    app = QApplication(sys.argv) if not QApplication.instance() else QApplication.instance()

    if len(sys.argv) == 1:
        # Ensure icons directory exists
        ensure_icons_directory()
        
        if not check_registry_keys():
            if add_registry_keys():
                app.setWindowIcon(QIcon(ico_path))
                QMessageBox.information(None, "Context Menu Updated", "Context menu buttons have been added & updated with custom icons.")
        sys.exit(0)

# Handle --edit-userhash separately
if args.edit_userhash:
    new_userhash = prompt_for_userhash()
    print(f"Userhash updated: {new_userhash}")
    sys.exit(0)

# Ensure userhash exists if not in anonymous mode and not in litterbox mode
USER_HASH = read_registry_value("userhash")

if not USER_HASH and args.file and not args.anonymous and not args.litterbox:
    USER_HASH = prompt_for_userhash()

def get_database_path():
    """Get the database path, preferring %APPDATA%/Catbox Uploader/ location."""
    # New location in %APPDATA%
    appdata_path = os.path.expandvars(r"%APPDATA%\Catbox Uploader")
    new_db_path = os.path.join(appdata_path, "catbox.db")
    
    # Old location in working directory
    old_db_path = os.path.join(application_path, "catbox.db")
    
    # Create %APPDATA%/Catbox Uploader directory if it doesn't exist
    os.makedirs(appdata_path, exist_ok=True)
    
    # Check if old database exists and new one doesn't
    if os.path.exists(old_db_path) and not os.path.exists(new_db_path):
        try:
            shutil.move(old_db_path, new_db_path)
            print(f"✅ Migrated database from {old_db_path} to {new_db_path}")
        except Exception as e:
            print(f"⚠️ Failed to migrate database: {e}")
            # Fall back to old location if migration fails
            return old_db_path
    
    return new_db_path

def ensure_database_schema():
    """Ensure the database exists and has the correct schema."""
    db_path = get_database_path()
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if uploads table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='uploads'
        """)
        
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            # Create the uploads table
            cursor.execute("""
                CREATE TABLE uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT,
                    url TEXT,
                    mode TEXT,
                    timestamp INTEGER,
                    expiry_duration TEXT,
                    is_deleted INTEGER DEFAULT 0
                )
            """)
            print("✅ Created uploads table")
        else:
            # Check if is_deleted column exists (for backward compatibility)
            cursor.execute("PRAGMA table_info(uploads)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'is_deleted' not in columns:
                cursor.execute("ALTER TABLE uploads ADD COLUMN is_deleted INTEGER DEFAULT 0")
                print("✅ Added is_deleted column to uploads table")
        
        conn.commit()
        conn.close()
        print(f"✅ Database schema validated: {db_path}")
        return db_path
        
    except Exception as e:
        print(f"❌ Database schema validation failed: {e}")
        return None

def log_upload(file_path, url, mode, expiry_duration=None):
    """Log upload information to database."""
    db_path = ensure_database_schema()
    if not db_path:
        return
        
    try:
        file_path = os.path.abspath(file_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO uploads (file_path, url, mode, timestamp, expiry_duration, is_deleted)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (
            file_path,
            url,
            mode,
            int(time.time()),
            expiry_duration
        ))
        conn.commit()
        conn.close()
        print(f"✅ Successfully logged upload: {file_path}")
    except Exception as e:
        print(f"⚠️ Failed to log upload: {e}")

class UploadWorker(QThread):
    update_progress = pyqtSignal(int)
    update_bytes_uploaded = pyqtSignal(int)
    upload_finished = pyqtSignal(str)

    def __init__(self, file_path, is_anonymous=False, litterbox_time=None):
        super().__init__()
        self.file_path = file_path
        self.is_anonymous = is_anonymous
        self.litterbox_time = litterbox_time
        self.total_size = 0
        self.bytes_uploaded = 0
        self._cancelled = False
        self._session = None
    
    def cancel(self):
        """Cancel the upload by closing the session."""
        self._cancelled = True
        if self._session:
            self._session.close()
        
    def run(self):
        try:
            # Create a session for this upload
            self._session = requests.Session()
            
            # Get file size for progress tracking
            self.total_size = os.path.getsize(self.file_path)
            
            # Choose upload method based on parameters
            if self.litterbox_time:
                result = self.upload_to_litterbox()
            else:
                result = self.upload_to_catbox()
            
            self.upload_finished.emit(result)
        except UploadCancelledException:
            self.upload_finished.emit("CANCELLED")
        except Exception as e:
            if self._cancelled:
                self.upload_finished.emit("CANCELLED")
            else:
                self.upload_finished.emit(f"Error: {str(e)}")
        finally:
            if self._session:
                self._session.close()
                self._session = None

    def create_monitor_callback(self, encoder):
        """Create a callback function for monitoring upload progress."""
        def callback(monitor):
            # Check if cancelled and raise exception to abort upload immediately
            if self._cancelled:
                raise UploadCancelledException("Upload cancelled by user")
            
            self.bytes_uploaded = monitor.bytes_read
            if self.total_size > 0:
                progress = int((self.bytes_uploaded / self.total_size) * 100)
                self.update_progress.emit(progress)
                self.update_bytes_uploaded.emit(self.bytes_uploaded)
        return callback

    def upload_to_catbox(self):
        """Upload file to Catbox."""
        if self._cancelled:
            return "CANCELLED"
        
        url = API_CATBOX
        
        # Prepare form data
        fields = {
            'reqtype': 'fileupload',
        }
        
        # Add userhash if not anonymous
        if not self.is_anonymous and USER_HASH:
            fields['userhash'] = USER_HASH
        
        # Add the file
        with open(self.file_path, 'rb') as f:
            fields['fileToUpload'] = (os.path.basename(self.file_path), f, mimetypes.guess_type(self.file_path)[0])
            
            # Create multipart encoder
            encoder = MultipartEncoder(fields=fields)
            monitor = MultipartEncoderMonitor(encoder, self.create_monitor_callback(encoder))
            
            # Make the request
            headers = {
                'Content-Type': monitor.content_type,
                'User-Agent': USER_AGENT
            }
            
            response = self._session.post(url, data=monitor, headers=headers, timeout=None)
            
        if response.status_code == 200:
            result = response.text.strip()
            if result.startswith('http'):
                return result
            elif not result:  # Empty response - server bug
                return "EMPTY_RESPONSE"
            else:
                return f"❌ Upload failed: {result}"
        else:
            return f"❌ Upload failed with status code: {response.status_code} \n {response.text.strip()}"

    def upload_to_litterbox(self):
        """Upload file to Litterbox with specified expiration time."""
        url = API_LITTERBOX
        
        # Prepare form data
        fields = {
            'reqtype': 'fileupload',
            'time': self.litterbox_time
        }
        
        # Add the file
        with open(self.file_path, 'rb') as f:
            fields['fileToUpload'] = (os.path.basename(self.file_path), f, mimetypes.guess_type(self.file_path)[0])
            
            # Create multipart encoder
            encoder = MultipartEncoder(fields=fields)
            monitor = MultipartEncoderMonitor(encoder, self.create_monitor_callback(encoder))
            
            # Make the request
            headers = {
                'Content-Type': monitor.content_type,
                'User-Agent': USER_AGENT
            }
            
            if self._cancelled:
                return "CANCELLED"
            
            response = self._session.post(url, data=monitor, headers=headers, timeout=None)
            
        if response.status_code == 200:
            result = response.text.strip()
            if result.startswith('http'):
                return result
            elif not result:  # Empty response - server bug
                return "EMPTY_RESPONSE"
            else:
                return f"Upload failed: {result}"
        else:
            return f"Upload failed with status code: {response.status_code}"

def pil_image_to_qpixmap(pil_image: Image.Image) -> QPixmap:
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)

def is_video_file(file_path):
    """Check if the file is a video file based on extension."""
    video_extensions = ['.mp4', '.mov', '.webm']
    return any(file_path.lower().endswith(ext) for ext in video_extensions)

def generate_discord_embed_url(video_url, original_filename=None):
    """Generate a Discord-embeddable URL using video.karimawi.me service with LZString."""
    try:
        # Extract filename from URL (files.catbox.moe/abcdef.mp4 -> abcdef.mp4)
        filename = video_url.split('/')[-1]
        
        # Use original filename for title if provided, otherwise default to URL filename without extension
        if original_filename:
            title = os.path.splitext(original_filename)[0]
        else:
            title = os.path.splitext(filename)[0]
        
        # Check for Litterbox
        is_litterbox = "litter.catbox.moe" in video_url
        
        # Format for embedder: ["filename.ext", "Title"] or ["*filename.ext", "Title"] for litterbox
        stored_filename = f"*{filename}" if is_litterbox else filename
        
        payload = [stored_filename, title]
        json_str = json.dumps(payload)
        
        lz = lzstring.LZString()
        encoded = lz.compressToEncodedURIComponent(json_str)
        
        return f"https://video.karimawi.me/{encoded}"
        
    except Exception as e:
        print(f"⚠️ Failed to generate embed URL: {e}")
        return video_url

def get_themed_icon(icon_name: str) -> QIcon:
    """Get an icon based on the current theme.
    
    Args:
        icon_name: Base icon name without extension (e.g., 'reload', 'del', 'bin')
    
    Returns:
        QIcon for the appropriate theme
    """
    use_light = is_windows_light_mode()
    
    # Icons that have light variants
    light_variant_icons = ['bin', 'reload', 'edit_userhash', 'history', 'upload_anon', 'upload_user']
    
    if use_light and icon_name in light_variant_icons:
        icon_file = f"{icon_name}_light.ico"
    else:
        icon_file = f"{icon_name}.ico"
    
    icon_path = os.path.join(application_path, "icons", icon_file)
    
    # Fallback to regular icon if light variant doesn't exist
    if use_light and icon_name in light_variant_icons and not os.path.exists(icon_path):
        icon_path = os.path.join(application_path, "icons", f"{icon_name}.ico")
    
    return QIcon(icon_path)

def create_thumbnail(path, deleted=False):
    """Create thumbnail icon, with optional theme-aware fallback icon."""
    if not deleted:
        try:
            thumb = generate_thumbnail(path)
            pixmap = QPixmap.fromImage(thumb.toqpixmap().toImage())
            return QIcon(pixmap)
        except:
            pass
    
    # Use themed delete icon
    return get_themed_icon('del')

def get_progressbar_stylesheet(colors: dict) -> str:
    """
    Generates a QSS string for QProgressBar using the given color dictionary.
    """
    return f"""
        QProgressBar {{
            border: 1px solid {colors['border']};
            border-radius: 5px;
            background-color: {colors['bg']};
            text-align: center;
            font-weight: bold;
            color: {colors['text']};
        }}
        QProgressBar::chunk {{
            background-color: {colors['chunk']};
        }}
    """
def get_menu_stylesheet(colors: dict) -> str:
    """
    Generates a QSS string for QMenu using the given color dictionary.
    """
    return f"""
        QMenu {{
            background-color: {colors['bg']};
            color: {colors['text']};
            border: 1px solid {colors['border']};
            border-radius: 8px;
            padding: 2px;
        }}
        QMenu::item {{
            background-color: transparent;
            padding: 6px 12px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {colors['chunk']};
            color: {colors['text']};
        }}
        QMenu::item:pressed {{
            background-color: {colors['chunk_pressed']};
        }}
    """

class UploadWindow(QWidget):
    def __init__(self, file_path, is_anonymous=False, litterbox_time=None):
        super().__init__()
        self.file_path = file_path
        self.file_size = os.path.getsize(file_path)
        self.bytes_uploaded = 0
        self.uploading = True
        self.cancelled = False
        self.is_anonymous = is_anonymous
        self.litterbox_time = litterbox_time
        self.start_time = time.time()  # Initialize start_time here
        use_light = is_windows_light_mode()
        theme_colors = light_theme_colors if use_light else dark_theme_colors

        
        # Dynamic Window Title
        if litterbox_time:
            self.setWindowTitle(f"Uploading to Litterbox ({litterbox_time})")
        elif is_anonymous:
            self.setWindowTitle("Uploading to Catbox anonymously")
        else:
            self.setWindowTitle("Uploading to Catbox")

        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowIcon(QIcon(ico_path))
        self.setFixedSize(420, 160)

        # Set the background color of the window
        self.setStyleSheet(f"background-color: {theme_colors['bg']};")
        layout = QHBoxLayout()
        self.thumbnail_label = QLabel(self)
        pixmap = pil_image_to_qpixmap(generate_thumbnail(self.file_path))
        self.thumbnail_label.setPixmap(pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio))
        layout.addWidget(self.thumbnail_label)

        right_layout = QVBoxLayout()

        # Create file label
        self.file_label = QLabel(f"Uploading: {os.path.basename(file_path)}")
        self.file_label.setWordWrap(True)  # Enable word wrap

        self.file_label.setStyleSheet(f"background-color: {theme_colors['bg']}; color: {theme_colors['text']};")
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)  # Allow the label to resize within the scroll area
        scroll_area.setWidget(self.file_label)

        scroll_area.setStyleSheet(f"background-color: {theme_colors['bg']}; border: none;")
        right_layout.addWidget(scroll_area)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(20)  # Set the height of the progress bar to make it thicker
        self.progress_bar.setStyleSheet(get_progressbar_stylesheet(theme_colors))

        right_layout.addWidget(self.progress_bar)

        self.eta_label = QLabel("ETA: Starting...")
        right_layout.addWidget(self.eta_label)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(f"background-color: {theme_colors['chunk']}; color: {theme_colors['text']};")
        self.cancel_button.clicked.connect(self.cancel_upload)
        right_layout.addWidget(self.cancel_button)

        layout.addLayout(right_layout)
        self.setLayout(layout)
        self.move_to_bottom_right()

        self.upload_worker = UploadWorker(file_path, is_anonymous, litterbox_time)
        self.upload_worker.update_progress.connect(self.update_progress)
        self.upload_worker.update_bytes_uploaded.connect(self.update_bytes_uploaded)
        self.upload_worker.upload_finished.connect(self.update_ui_after_upload)
        self.upload_worker.start()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_eta)
        self.timer.start(500)
        

    def move_to_bottom_right(self):
        screen = QApplication.primaryScreen()
        available_geometry = screen.availableGeometry()
        window_geometry = self.frameGeometry()
        x = available_geometry.right() - window_geometry.width() - 10
        y = available_geometry.bottom() - window_geometry.height() - 40
        self.move(x, y)

    def update_progress(self, progress):
        self.progress_bar.setValue(progress)

    def update_bytes_uploaded(self, bytes_uploaded):
        self.bytes_uploaded = bytes_uploaded

    def update_eta(self):
        if hasattr(self, 'start_time') and hasattr(self, 'bytes_uploaded') and self.bytes_uploaded > 0:
            elapsed_time = time.time() - self.start_time
            
            # Check if upload_worker and total_size are available
            if hasattr(self.upload_worker, 'total_size') and self.upload_worker.total_size > 0:
                total_bytes = self.upload_worker.total_size
            else:
                # Fallback: try to get file size directly
                try:
                    total_bytes = os.path.getsize(self.upload_worker.file_path)
                except:
                    total_bytes = 0
            
            if total_bytes > 0 and elapsed_time > 0:
                bytes_per_second = self.bytes_uploaded / elapsed_time
                remaining_bytes = total_bytes - self.bytes_uploaded
                eta_seconds = remaining_bytes / bytes_per_second
                
                # Format ETA with hours, minutes, and seconds
                if eta_seconds > 3600:  # More than 1 hour
                    hours = int(eta_seconds // 3600)
                    minutes = int((eta_seconds % 3600) // 60)
                    seconds = int(eta_seconds % 60)
                    eta_text = f"ETA: {hours}h {minutes}m {seconds}s"
                elif eta_seconds > 60:  # More than 1 minute
                    minutes = int(eta_seconds // 60)
                    seconds = int(eta_seconds % 60)
                    eta_text = f"ETA: {minutes}m {seconds}s"
                else:  # Less than 1 minute
                    seconds = int(eta_seconds)
                    eta_text = f"ETA: {seconds}s"
                
                self.eta_label.setText(eta_text)
            else:
                self.eta_label.setText("ETA: Calculating...")
        else:
            self.eta_label.setText("ETA: Starting...")

    @pyqtSlot(str)
    def update_ui_after_upload(self, result):
        # Ignore if already cancelled (UI was already updated)
        if self.cancelled:
            return
            
        if result == "CANCELLED":
            # This shouldn't normally be reached since we disconnect signals,
            # but handle it just in case
            self.file_label.setText("❌ Upload cancelled")
            self.progress_bar.setFormat("Cancelled")
            self.eta_label.setText("Cancelled")
            self.cancel_button.setText("OK")
            self.uploading = False
            self.timer.stop()
        elif result == "EMPTY_RESPONSE":
            self.handle_empty_response()
        elif "http" in result:
            self.file_label.setText(f"<p>✅ Uploaded: <a href='{result}'>{result}</a></p>")
            self.file_label.setOpenExternalLinks(True)
            
            # Store the URL for context menu
            self.file_label.setProperty("upload_url", result.strip())
            
            # Set up context menu for URL
            self.file_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.file_label.customContextMenuRequested.connect(self.show_url_context_menu)
            
            clipboard = QApplication.clipboard()
            clipboard.setText(result.strip(), clipboard.Mode.Clipboard)
            
            self.cancel_button.setText("OK")
            self.progress_bar.setFormat("%p%")
            self.progress_bar.setValue(100)
            self.eta_label.setText("Upload Complete")

            if self.is_anonymous:
                mode = "Anonymous"
            elif self.litterbox_time:
                mode = f"Litterbox {self.litterbox_time}"
            else:
                mode = "User"

            log_upload(file_path=self.file_path, url=result, mode=mode, expiry_duration=getattr(self, 'litterbox_time', None))
            self.uploading = False
            self.timer.stop()  # Stop the timer when the upload is complete
            
            # Force UI to update now
            QApplication.processEvents()
        else:
            self.file_label.setText(result)
            self.cancel_button.setText("OK")
            self.progress_bar.setValue(100)
            self.eta_label.setText("Upload Failed")
            self.uploading = False
            self.timer.stop()

    def show_url_context_menu(self, position):
        """Show context menu for the uploaded URL."""
        url = self.file_label.property("upload_url")
        use_light = is_windows_light_mode()
        theme_colors = light_theme_colors if use_light else dark_theme_colors
        if not url:
            return
            
        menu = QMenu(self)

        menu.setStyleSheet(get_menu_stylesheet(theme_colors))
        # Copy action
        copy_action = QAction("Copy URL", self)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(url))
        menu.addAction(copy_action)
        
        # Copy embeddable action (only for videos)
        if is_video_file(self.file_path):
            # Pass basename of source file as title
            embed_url = generate_discord_embed_url(url, os.path.basename(self.file_path))
            
            copy_embed_action = QAction("Copy Embeddable", self)
            copy_embed_action.triggered.connect(lambda: QApplication.clipboard().setText(embed_url))
            menu.addAction(copy_embed_action)

        open_action = QAction("Open in Browser", self)
        open_action.triggered.connect(lambda: self.open_url_in_browser(url))
        menu.addAction(open_action)
        
        menu.exec(self.file_label.mapToGlobal(position))

    def open_url_in_browser(self, url):
        """Open URL in default browser."""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open URL: {str(e)}")

    def cancel_upload(self):
        """Cancel the current upload."""
        if self.uploading:
            # Mark as cancelled and not uploading first
            self.uploading = False
            self.cancelled = True
            
            # Stop timer first to prevent UI updates
            self.timer.stop()
            
            # Disconnect ALL signals to stop any updates from the worker
            if hasattr(self, 'upload_worker'):
                try:
                    self.upload_worker.update_progress.disconnect(self.update_progress)
                except TypeError:
                    pass  # Already disconnected
                try:
                    self.upload_worker.update_bytes_uploaded.disconnect(self.update_bytes_uploaded)
                except TypeError:
                    pass  # Already disconnected
                try:
                    self.upload_worker.upload_finished.disconnect(self.update_ui_after_upload)
                except TypeError:
                    pass  # Already disconnected
                
                # Cancel the upload worker
                self.upload_worker.cancel()
                
                # Forcefully terminate the thread - requests doesn't support true cancellation
                # Give it a tiny moment to clean up, then terminate
                if not self.upload_worker.wait(100):  # Wait 100ms max
                    self.upload_worker.terminate()
                    self.upload_worker.wait()  # Wait for termination to complete
            
            # Update UI immediately
            self.file_label.setText("❌ Upload cancelled")
            self.progress_bar.setFormat("Cancelled")
            self.eta_label.setText("Cancelled")
            self.cancel_button.setText("OK")
            
            # Force UI to update now
            QApplication.processEvents()
        else:
            # If not uploading, just close the window
            self.close()

    def handle_empty_response(self):
        """Handle empty response from server - known Catbox bug."""
        self.progress_bar.setValue(100)
        self.eta_label.setText("Server Bug Detected")
        self.uploading = False
        self.timer.stop()
        
        # Create message box with appropriate options
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Server Response Bug")
        msg_box.setWindowIcon(QIcon(ico_path))
        msg_box.setIcon(QMessageBox.Icon.Warning)
        
        if self.litterbox_time:
            msg_box.setText("Catbox server bug detected!")
            msg_box.setInformativeText(
                "The file was likely uploaded to Litterbox successfully, but the server "
                "didn't return the link due to a known bug (especially common with GIFs).\n"
                "It also may be corrupted, a re-upload would ensure the uploaded file is not corrupted.\n\n"
                "What would you like to do?"
            )
        elif self.is_anonymous:
            msg_box.setText("Catbox server bug detected!")
            msg_box.setInformativeText(
                "The file was likely uploaded anonymously to Catbox successfully, but the server "
                "didn't return the link due to a known bug (especially common with GIFs).\n"
                "It also may be corrupted, a re-upload would ensure the uploaded file is not corrupted.\n\n"
                "What would you like to do?"
            )
        else:
            msg_box.setText("Catbox server bug detected!")
            msg_box.setInformativeText(
                "The file was likely uploaded to your Catbox account successfully, but the server "
                "didn't return the link due to a known bug (especially common with GIFs).\n"
                "It also may be corrupted, a re-upload would ensure the uploaded file is not corrupted.\n\n"
                "What would you like to do?"
            )
        
        # Add buttons based on upload type
        reupload_btn = msg_box.addButton("Reupload File", QMessageBox.ButtonRole.ActionRole)
        
        if not self.is_anonymous and not self.litterbox_time:
            dashboard_btn = msg_box.addButton("Open Dashboard", QMessageBox.ButtonRole.ActionRole)
        else:
            dashboard_btn = None
            
        cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.setDefaultButton(reupload_btn)
        msg_box.exec()
        
        clicked_button = msg_box.clickedButton()
        
        if clicked_button == reupload_btn:
            self.reupload_file()
        elif dashboard_btn and clicked_button == dashboard_btn:
            self.open_catbox_dashboard()
        else:
            # Cancel - just update UI to show the situation
            self.file_label.setText("❌ Upload completed but link not returned due to server bug")
            self.cancel_button.setText("OK")

    def reupload_file(self):
        """Restart the upload process."""
        self.file_label.setText(f"Re-uploading: {os.path.basename(self.file_path)}")
        self.progress_bar.setValue(0)
        self.eta_label.setText("ETA: Starting...")
        self.cancel_button.setText("Cancel")
        self.uploading = True
        self.start_time = time.time()
        self.bytes_uploaded = 0
        
        # Create new worker and restart upload
        self.upload_worker = UploadWorker(self.file_path, self.is_anonymous, self.litterbox_time)
        self.upload_worker.update_progress.connect(self.update_progress)
        self.upload_worker.update_bytes_uploaded.connect(self.update_bytes_uploaded)
        self.upload_worker.upload_finished.connect(self.update_ui_after_upload)
        self.upload_worker.start()
        
        # Restart timer
        self.timer.start(500)

    def open_catbox_dashboard(self):
        """Open Catbox login page and dashboard in browser."""
        import webbrowser
        
        try:
            # Open login page first
            webbrowser.open("https://catbox.moe/user/login.php")
            
            # Show instructions
            info_msg = QMessageBox(self)
            info_msg.setWindowTitle("Dashboard Instructions")
            info_msg.setWindowIcon(QIcon(ico_path))
            info_msg.setIcon(QMessageBox.Icon.Information)
            info_msg.setText("Browser opened to Catbox login page")
            info_msg.setInformativeText(
                "1. Log in with your account\n"
                "2. Navigate to your files dashboard\n"
                "3. Look for your recently uploaded file\n\n"
                "Click OK to open the dashboard page directly."
            )
            info_msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            
            if info_msg.exec() == QMessageBox.StandardButton.Ok:
                # Open dashboard page
                webbrowser.open("https://catbox.moe/user/view.php")
                
        except Exception as e:
            error_msg = QMessageBox(self)
            error_msg.setWindowTitle("Error")
            error_msg.setWindowIcon(QIcon(ico_path))
            error_msg.setIcon(QMessageBox.Icon.Critical)
            error_msg.setText(f"Failed to open browser: {str(e)}")
            error_msg.exec()
        
        # Update UI to show action taken
        self.file_label.setText("🌐 Dashboard opened in browser - check for your uploaded file")
        self.cancel_button.setText("OK")
        
class ErrorDialog(QDialog):
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Error")
        self.setWindowIcon(QIcon(ico_path))
        self.setFixedSize(500, 300)

        layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setText(message)
        layout.addWidget(self.text_edit)

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.close)
        layout.addWidget(self.ok_button)

        self.setLayout(layout)

class ErrorHandler:
    """Redirects stderr to a custom scrollable error dialog."""
    def __init__(self, app):
        self.app = app

    def write(self, message):
        if message.strip():  # Avoid empty error messages
            app = QApplication(sys.argv)
            app.setWindowIcon(QIcon(ico_path))
            dialog = ErrorDialog(message)
            dialog.exec()

    def flush(self):
        pass  # Required for sys.stderr compatibility

def show_critical_error(exc_type, exc_value, exc_traceback):
    """Shows uncaught exceptions in a custom scrollable dialog."""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ico_path))
    dialog = ErrorDialog(error_msg)
    dialog.exec()

def ensure_icons_directory():
    """Ensure the icons directory exists and create placeholder icons if needed."""
    if not os.path.exists(icons_dir):
        os.makedirs(icons_dir)
    
    # List of required icon files
    required_icons = [
        "upload_user.ico", 
        "upload_anon.ico", 
        "edit_userhash.ico", 
        "history.ico",
        "reload.ico",
        "del.ico", 
        "bin.ico"
    ]
    
    # Copy main icon as fallback for missing icons
    main_icon_path = os.path.join(application_path, "icon.ico")
    for icon_file in required_icons:
        icon_path = os.path.join(icons_dir, icon_file)
        if not os.path.exists(icon_path) and os.path.exists(main_icon_path):
            try:
                import shutil
                shutil.copy2(main_icon_path, icon_path)
            except Exception:
                pass  # Ignore copy errors

if __name__ == "__main__":
    main()
    app = QApplication(sys.argv)
    sys.stderr = ErrorHandler(app)  # Redirect stderr
    sys.excepthook = show_critical_error  # Handle uncaught exceptions

    try:
        ensure_icons_directory()  # Ensure icons directory and files are set up
        
        # Always silently refresh icons to match current theme
        if not check_registry_keys():
            add_registry_keys()

        if args.history:
            from history_viewer import show_history_window
            show_history_window()
            sys.exit(app.exec())

        if args.file:  # Ensure a file was provided
            window = UploadWindow(args.file, is_anonymous=args.anonymous, litterbox_time=args.litterbox)
            window.show()
            sys.exit(app.exec())
        else:
            app = QApplication(sys.argv)
            app.setWindowIcon(QIcon(ico_path))
            QMessageBox.critical(None, "Error", "No file specified for upload.")
            sys.exit(1)
            
    except Exception as e:
        app.setWindowIcon(QIcon(ico_path))
        QMessageBox.critical(None, "Unhandled Exception", str(e))
        sys.exit(1)
