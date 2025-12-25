import ctypes
import os
import sqlite3
import sys
import time
import winreg
from datetime import datetime
import shutil

import requests
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QAction, QCursor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout,
                             QHeaderView, QLabel, QMainWindow, QMenu,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget, QToolTip,
                             QDialog, QProgressBar, QTextEdit, QCheckBox)

from thumb import generate_thumbnail

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# Constants
DB_NAME = "catbox.db"
EXPIRED_ICON_ID = 16777
SHELL32_DLL = "C:\\WINDOWS\\System32\\SHELL32.dll"
ico_path = os.path.join(application_path, "icons", "icon.ico")
REG_PATH = r"Software\CatboxUploader"

# Colors for dark/light theme
dark_theme_colors = {
    "bg": "#2D2D2D",
    "alt_bg": "#262626",
    "text": "white",
    "header_bg": "#3C3C3C",
    "header_text": "white",
    "checkbox_bg": "#404040",
    "checkbox_border": "#606060",
    "checkbox_checked": "#0078d4",
    "selection_bg": "#0078d4",
    "menu_border": "#555",
    "menu_selected": "#0078d4",
    "menu_pressed": "#106ebe"
}

light_theme_colors = {
    "bg": "#ffffff",
    "alt_bg": "#f5f5f5",
    "text": "#000000",
    "header_bg": "#e0e0e0",
    "header_text": "#000000",
    "checkbox_bg": "#f0f0f0",
    "checkbox_border": "#c0c0c0",
    "checkbox_checked": "#0078d4",
    "selection_bg": "#cce4ff",
    "menu_border": "#c0c0c0",
    "menu_selected": "#cce4ff",
    "menu_pressed": "#99c9ff"
}

# API Endpoints
API_CATBOX = "https://catbox.moe/user/api.php"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

def get_database_path():
    """Get the database path, preferring %APPDATA%/Catbox Uploader/ location."""
    # New location in %APPDATA%
    appdata_path = os.path.expandvars(r"%APPDATA%\Catbox Uploader")
    new_db_path = os.path.join(appdata_path, DB_NAME)
    
    # Old location in working directory
    old_db_path = os.path.join(application_path, DB_NAME)
    
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

def read_registry_value(name):
    """Read a value from Windows Registry under HKEY_CURRENT_USER."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except FileNotFoundError:
        return None

def delete_files(urls, userhash):
    if not userhash:
        print("❌ Userhash is required to delete files.")
        return

    # Extract file names from URLs
    filenames = [url.strip().split("/")[-1] for url in urls if url.strip().startswith("https://")]
    if not filenames:
        print("❌ No valid Catbox URLs provided.")
        return

    data = {
        "reqtype": "deletefiles",
        "userhash": userhash,
        "files": " ".join(filenames)
    }

    try:
        response = requests.post(API_CATBOX, data=data, headers={"User-Agent": USER_AGENT})
        if response.status_code == 200:
            print("🗑️ Delete request successful.")
            return response.text.strip()
        else:
            return f"❌ Failed to delete files: {response.status_code} - {response.text.strip()}"
    except requests.RequestException as e:
        return f"❌ Error while deleting files: {str(e)}"

class MassDeleteWorker(QThread):
    progress_updated = pyqtSignal(int, int, str)  # current, total, message
    finished_signal = pyqtSignal(list)  # list of successfully deleted URLs

    def __init__(self, urls, userhash):
        super().__init__()
        self.urls = urls
        self.userhash = userhash
        self.deleted_urls = []

    def run(self):
        total = len(self.urls)
        for i, url in enumerate(self.urls, 1):
            filename = os.path.basename(url)
            self.progress_updated.emit(i, total, f"Deleting {filename}...")
            
            try:
                response = delete_files([url], self.userhash)
                if response:
                    # Handle various response cases
                    response_lower = response.lower()
                    if "file doesn't exist" in response_lower or "not found" in response_lower:
                        # File already deleted from Catbox
                        self.deleted_urls.append(url)
                        self.progress_updated.emit(i, total, f"✓ {filename} (already deleted from Catbox)")
                    elif "permission denied" in response_lower or "invalid hash" in response_lower:
                        # Different userhash or no permission
                        self.progress_updated.emit(i, total, f"⚠️ {filename} (no permission - different userhash?)")
                    elif "error" not in response_lower:
                        # Successfully deleted
                        self.deleted_urls.append(url)
                        self.progress_updated.emit(i, total, f"✓ {filename} (deleted)")
                    else:
                        # Other error
                        self.progress_updated.emit(i, total, f"❌ {filename} (error: {response})")
                else:
                    self.progress_updated.emit(i, total, f"❌ {filename} (no response)")
            except Exception as e:
                self.progress_updated.emit(i, total, f"❌ {filename} (exception: {str(e)})")
            
            time.sleep(0.1)  # Small delay to show progress
        
        self.finished_signal.emit(self.deleted_urls)

class MassDeleteDialog(QDialog):
    def __init__(self, urls, userhash, parent=None):
        super().__init__(parent)
        self.urls = urls  # Store the URLs list
        self.setWindowTitle("Mass Delete Progress")
        self.setWindowIcon(QIcon(ico_path))
        self.setFixedSize(500, 200)
        self.setModal(True)
        
        layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(urls))
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Starting deletion process...")
        layout.addWidget(self.status_label)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(100)
        layout.addWidget(self.log_text)
        
        self.setLayout(layout)
        
        # Start the worker
        self.worker = MassDeleteWorker(urls, userhash)
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.finished_signal.connect(self.deletion_finished)
        self.worker.start()
        
    def update_progress(self, current, total, message):
        self.progress_bar.setValue(current)
        self.status_label.setText(f"{current}/{total} files processed")
        self.log_text.append(message)
        
    def deletion_finished(self, deleted_urls):
        processed_count = len(self.urls)  # Now self.urls is available
        success_count = len(deleted_urls)
        
        if success_count == processed_count:
            self.status_label.setText(f"<font color='green'>✅ All {processed_count} files processed successfully!</font>")
        else:
            failed_count = processed_count - success_count
            self.status_label.setText(f"<font color='orange'>⚠️ {success_count}/{processed_count} files processed successfully. {failed_count} failed or skipped.</font>")
        
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        
        # Update database to mark files as deleted (including already deleted ones)
        if deleted_urls:
            db_path = ensure_database_schema()
            if db_path:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                for url in deleted_urls:
                    cursor.execute("UPDATE uploads SET is_deleted = 1 WHERE url = ?", (url,))
                conn.commit()
                conn.close()
        
        # Add OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        self.layout().addWidget(ok_button)
        
        self.deleted_urls = deleted_urls

def is_video_file(url):
    """Check if the URL points to a video file based on extension."""
    video_extensions = ['.mp4', '.mov', '.webm', '.avi', '.mkv', '.flv', '.wmv', '.m4v', '.3gp']
    url_lower = url.lower()
    return any(url_lower.endswith(ext) for ext in video_extensions)

def generate_discord_embed_url(video_url):
    """Generate a Discord-embeddable URL using embeds.video service.
    
    Args:
        video_url: The direct URL to the video file (catbox.moe or litterbox)
    
    Returns:
        The embeddable URL in format: https://embeds.video/cat/{filename}
    """
    try:
        # Extract filename from URL
        # Example: https://files.catbox.moe/abc123.mp4 -> abc123.mp4
        # Example: https://litter.catbox.moe/abc123.mp4 -> abc123.mp4
        filename = video_url.split('/')[-1]
        
        # Generate embeds.video URL
        embed_url = f"https://embeds.video/cat/{filename}"
        return embed_url
        
    except Exception as e:
        print(f"⚠️ Failed to generate embed URL: {e}")
        return video_url

def log_upload(file_path, url, mode, expiry_duration=None):
    db_path = ensure_database_schema()
    if not db_path:
        print("❌ Failed to initialize database")
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

def load_uploads():
    db_path = ensure_database_schema()
    if not db_path:
        return []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, url, mode, timestamp, expiry_duration, is_deleted FROM uploads ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"❌ Failed to load uploads: {e}")
        return []

def format_mode(mode, expiry, timestamp):
    if "Litterbox" in mode and expiry:
        hours = int(expiry.replace("h", ""))
        expiry_time = timestamp + (hours * 3600)
        if time.time() > expiry_time:
            return mode, True
    return mode, False

def get_time_left(expiry, timestamp):
    try:
        hours = int(expiry.replace("h", ""))
        expiry_time = timestamp + (hours * 3600)
        now = time.time()
        if now >= expiry_time:
            return "Expired", True
        seconds_left = int(expiry_time - now)
        hours_left = seconds_left // 3600
        minutes_left = (seconds_left % 3600) // 60
        return f"{hours_left}h {minutes_left}m", False
    except:
        return "", False

def create_thumbnail(path, deleted=False, use_light=None):
    """Create thumbnail icon, with optional theme-aware fallback icon."""
    if use_light is None:
        use_light = is_windows_light_mode()
    
    if not deleted:
        try:
            thumb = generate_thumbnail(path)
            pixmap = QPixmap.fromImage(thumb.toqpixmap().toImage())
            return QIcon(pixmap)
        except:
            pass
    
    # Use themed delete icon
    return get_themed_icon('del')

def is_windows_light_mode() -> bool:
    """ Checks if the current Windows theme is light mode
    
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

def get_table_stylesheet(colors: dict) -> str:
    """Generate a QSS stylesheet string for QTableWidget and QCheckBox based on color dict."""
    return f"""
        QTableWidget {{
            background-color: {colors['bg']};
            alternate-background-color: {colors['alt_bg']};
            color: {colors['text']};
        }}
        QHeaderView::section {{
            background-color: {colors['header_bg']};
            color: {colors['header_text']};
        }}
        QTableWidget::item {{
            border: none;
        }}
        QCheckBox {{
            spacing: 5px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            background-color: {colors['checkbox_bg']};
            border: 2px solid {colors['checkbox_border']};
            border-radius: 3px;
        }}
        QCheckBox::indicator:checked {{
            background-color: {colors['checkbox_checked']};
            border: 2px solid {colors['checkbox_checked']};
        }}
        QTableWidget::item:selected {{
            background-color: {colors['selection_bg']};
        }}
        QCheckBox::indicator:hover {{
            border: 2px solid #106ebe;
        }}
    """

def get_menu_stylesheet(colors: dict) -> str:
    """Generate a QSS stylesheet string for QMenu based on color dict."""
    return f"""
        QMenu {{
            background-color: {colors['bg']};
            color: {colors['text']};
            border: 1px solid {colors['menu_border']};
            border-radius: 8px;
            padding: 2px;
        }}
        QMenu::item {{
            background-color: transparent;
            padding: 6px 12px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {colors['menu_selected']};
            color: {colors['text']};
        }}
        QMenu::item:pressed {{
            background-color: {colors['menu_pressed']};
        }}
    """

def get_current_theme_colors() -> dict:
    """Get the current theme colors based on Windows theme."""
    return light_theme_colors if is_windows_light_mode() else dark_theme_colors

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

def show_history_window():
    # Dark = default; use light only if Windows explicitly uses light mode
    use_light = is_windows_light_mode()
    colors = light_theme_colors if use_light else dark_theme_colors
    window = QMainWindow()
    window.setWindowIcon(QIcon(ico_path))
    window.setWindowTitle("Upload History")
    window.setMinimumSize(840, 500)
    
    # Store references for theme updates
    window._theme_widgets = {}

    # Add reload button
    reload_button = QPushButton()
    reload_button.setIcon(get_themed_icon('reload'))
    reload_button.setFixedSize(30, 30)
    reload_button.setToolTip("Reload")
    reload_button.setCursor(Qt.CursorShape.PointingHandCursor)
    reload_button.clicked.connect(lambda: reload_history(window))
    window._theme_widgets['reload_button'] = reload_button

    # Create a layout for the reload button
    top_layout = QHBoxLayout()
    top_layout.addStretch()
    top_layout.addWidget(reload_button)

    table = QTableWidget()
    QApplication.setEffectEnabled(Qt.UIEffect.UI_General, False)
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(lambda pos: show_context_menu(table, pos))
    table.setColumnCount(8)  # Add an extra column for checkboxes
    table.setHorizontalHeaderLabels(["", "Icon", "File Path", "Mode", "Uploaded", "URL", "Time Left", ""])
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)

    # Enable alternating row colors
    table.setAlternatingRowColors(True)
    table.setStyleSheet(get_table_stylesheet(colors))


    def load_table_data():
        uploads = load_uploads()
        table.setRowCount(len(uploads))

        for row_index, (file_path, url, mode, timestamp, expiry, is_deleted) in enumerate(uploads):
            file_exists = os.path.exists(file_path)
            mode_label, is_expired = format_mode(mode, expiry, timestamp)

            # Set row height (double default)
            table.setRowHeight(row_index, 50)

            # 0. Checkbox
            checkbox_widget = CustomCheckBox()
            checkbox_widget.setChecked(False)
            checkbox_widget.setEnabled(False)  # Initially disabled
            
            # Center the checkbox
            checkbox_container = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_container)
            checkbox_layout.addWidget(checkbox_widget)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            table.setCellWidget(row_index, 0, checkbox_container)

            # Store checkbox reference for theme updates
            checkbox_widget._use_light_theme = use_light

            # 1. Thumbnail
            icon = create_thumbnail(file_path, deleted=not file_exists, use_light=use_light)
            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_pixmap = icon.pixmap(48, 48)
            thumb_label.setPixmap(thumb_pixmap)
            table.setCellWidget(row_index, 1, thumb_label)

            # 2. File Path
            display_path = file_path
            if not file_exists:
                display_path = f"<s><font color='red'>{file_path}</font></s>"
            
            file_label = QLabel()
            file_label.setTextFormat(Qt.TextFormat.RichText)
            file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            file_label.setText(display_path)
            file_label.setToolTip(file_path)
            
            # Make file path clickable if file exists
            if file_exists:
                file_label.setCursor(Qt.CursorShape.PointingHandCursor)
                file_label.mousePressEvent = lambda event, path=file_path: open_file_in_default_app(path) if event.button() == Qt.MouseButton.LeftButton else None
            
            # Set up custom context menu for file path
            file_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            file_label.customContextMenuRequested.connect(lambda pos, widget=file_label, path=file_path: show_file_context_menu(widget, pos, path))
            
            table.setCellWidget(row_index, 2, file_label)

            # 3. Mode
            mode_item = QTableWidgetItem(mode_label)
            mode_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_expired:
                font = mode_item.font()
                font.setStrikeOut(True)
                mode_item.setForeground(QColor("red"))
                mode_item.setFont(font)
            table.setItem(row_index, 3, mode_item)

            # 4. Uploaded
            time_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            time_item = QTableWidgetItem(time_str)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row_index, 4, time_item)

            # 5. URL
            url_label = QLabel()
            url_label.setTextFormat(Qt.TextFormat.RichText)
            url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            url_label.setOpenExternalLinks(True)
            url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            url_label.setToolTip(url)

            # Set raw URL as a property (for later retrieval)
            url_label.setProperty("raw_url", url)
            url_label.setProperty("file_path", file_path)  # Store file path for embed generation
            
            # Set up custom context menu for URL
            url_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            url_label.customContextMenuRequested.connect(lambda pos, widget=url_label: show_url_context_menu(widget, pos))

            # Display formatted text
            if is_expired:
                url_text = f"<s><font color='red'>{url}</font></s>"
            else:
                url_text = f"<a href='{url}'>{url}</a>"

            url_label.setText(url_text)
            table.setCellWidget(row_index, 5, url_label)

            # 6. Time Left
            time_left_str, expired = get_time_left(expiry, timestamp) if "Litterbox" in mode else ("", False)
            time_left_item = QTableWidgetItem(time_left_str)
            time_left_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if expired:
                font = time_left_item.font()
                font.setStrikeOut(True)
                time_left_item.setForeground(QColor("red"))
                time_left_item.setFont(font)
            table.setItem(row_index, 6, time_left_item)

            # 7. Delete Button for "User" uploads only
            if mode == "User":
                delete_button = QPushButton()
                delete_button.setIcon(get_themed_icon('bin'))
                delete_button.setFixedHeight(30)
                delete_button.setToolTip("Delete file from Catbox")
                delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
                delete_button.setEnabled(not is_deleted)

                if not delete_button.isEnabled():
                    delete_button.setToolTip("File Already Deleted")

                def make_delete_handler(file_url, button):
                    def handler():
                        confirm = QMessageBox.question(
                            window,
                            "Confirm Deletion",
                            f"Are you sure you want to delete this file from Catbox?\n\n{file_url}",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if confirm == QMessageBox.StandardButton.Yes:
                            try:
                                response = delete_files([file_url], read_registry_value("userhash"))
                                if "error" in response and "File doesn't exist?" not in response:
                                    QMessageBox.critical(window, "Error", f"❌ Failed to delete:\n{response}")
                                else:
                                    # Update DB
                                    db_path = ensure_database_schema()
                                    if db_path:
                                        conn = sqlite3.connect(db_path)
                                        cursor = conn.cursor()
                                        cursor.execute("UPDATE uploads SET is_deleted = 1 WHERE url = ?", (file_url,))
                                        conn.commit()
                                        conn.close()

                                    # Disable button
                                    button.setEnabled(False)
                                    button.setToolTip("File Already Deleted")

                                    msg = "✅ Deleted from Catbox (already deleted)." if "File doesn't exist?" in response else f"✅ Deleted from Catbox:\n{file_url}"
                                    QMessageBox.information(window, "Success", msg)
                            except Exception as e:
                                QMessageBox.critical(window, "Error", f"❌ Exception:\n{e}")
                    return handler

                delete_button.clicked.connect(make_delete_handler(url, delete_button))

                button_container = QWidget()
                button_layout = QVBoxLayout(button_container)
                button_layout.addWidget(delete_button)
                button_layout.setContentsMargins(0, 0, 0, 0)
                button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setCellWidget(row_index, 7, button_container)

            else:
                table.setCellWidget(row_index, 7, QWidget())  # Empty cell

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(False)

        header = table.horizontalHeader()
        # Stretch most columns
        for col in range(7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

        # Set fixed width for the delete button column
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(7, 40)

        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 30)

        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(1, 60)

        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(6, 70)

        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(3, 85)

    load_table_data()

    layout = QVBoxLayout()
    layout.addLayout(top_layout)
    layout.addWidget(table)

    # Add buttons at the bottom
    button_layout = QHBoxLayout()
    select_button = QPushButton("Select")
    select_all_button = QPushButton("Select All")
    mass_delete_button = QPushButton()
    mass_delete_button.setIcon(get_themed_icon('bin'))
    mass_delete_button.setToolTip("Mass Delete Selected Files from Catbox")
    remove_selection_button = QPushButton("Remove Selection")

    select_all_button.setVisible(False)
    mass_delete_button.setVisible(False)
    remove_selection_button.setVisible(False)
    remove_selection_button.setEnabled(False)

    def get_checkbox_widget(row):
        """Get the checkbox widget from a table row."""
        container = table.cellWidget(row, 0)
        if container:
            return container.findChild(CustomCheckBox)
        return None

    def set_checkbox_checked(row, checked):
        """Set the checkbox state for a table row."""
        checkbox = get_checkbox_widget(row)
        if checkbox:
            checkbox.setChecked(checked)

    def is_checkbox_checked(row):
        """Check if the checkbox is checked for a table row."""
        checkbox = get_checkbox_widget(row)
        return checkbox.isChecked() if checkbox else False

    def set_checkbox_enabled(row, enabled):
        """Enable or disable the checkbox for a table row."""
        checkbox = get_checkbox_widget(row)
        if checkbox:
            checkbox.setEnabled(enabled)

    def toggle_select_mode():
        if select_button.text() == "Select":
            select_button.setText("Cancel")
            select_all_button.setVisible(True)
            mass_delete_button.setVisible(False)  # Hidden until a User upload is selected
            remove_selection_button.setVisible(True)
            remove_selection_button.setEnabled(True)
            table.setColumnHidden(0, False)  # Show checkbox column
            for row in range(table.rowCount()):
                set_checkbox_checked(row, False)
                set_checkbox_enabled(row, True)
        else:
            select_button.setText("Select")
            select_all_button.setVisible(False)
            mass_delete_button.setVisible(False)
            remove_selection_button.setVisible(False)
            table.setColumnHidden(0, True)  # Hide checkbox column
            for row in range(table.rowCount()):
                set_checkbox_checked(row, False)
                set_checkbox_enabled(row, False)
    
    def update_mass_delete_visibility():
        """Show mass delete button only if at least one User upload is selected."""
        if select_button.text() != "Cancel":  # Not in select mode
            return
        
        uploads = load_uploads()
        has_user_upload_selected = False
        
        for row in range(table.rowCount()):
            if is_checkbox_checked(row) and row < len(uploads):
                file_path, url, mode, timestamp, expiry, is_deleted = uploads[row]
                if mode == "User" and not is_deleted:
                    has_user_upload_selected = True
                    break
        
        mass_delete_button.setVisible(has_user_upload_selected)

    def select_all():
        for row in range(table.rowCount()):
            set_checkbox_checked(row, True)
        remove_selection_button.setEnabled(True)
        update_mass_delete_visibility()

    def clear_selection():
        for row in range(table.rowCount()):
            set_checkbox_checked(row, False)
        remove_selection_button.setEnabled(False)
        update_mass_delete_visibility()

    def mass_delete_selection():
        # Get selected User uploads only (skip expired ones)
        selected_urls = []
        uploads = load_uploads()
        
        for row in range(table.rowCount()):
            if is_checkbox_checked(row):
                # Get the original upload data
                if row < len(uploads):
                    file_path, url, mode, timestamp, expiry, is_deleted = uploads[row]
                    # Only include User mode uploads that aren't already deleted
                    if mode == "User" and not is_deleted:
                        selected_urls.append(url)

        if not selected_urls:
            QMessageBox.warning(window, "No Files", "No User mode files selected for deletion.")
            return

        userhash = read_registry_value("userhash")
        if not userhash:
            QMessageBox.critical(window, "Error", "Userhash is required for deletion.")
            return

        # Show mass delete dialog
        dialog = MassDeleteDialog(selected_urls, userhash, window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Ask if user wants to remove from database too
            if dialog.deleted_urls:
                confirm = QMessageBox.question(
                    window,
                    "Remove from Database?",
                    f"{len(dialog.deleted_urls)} files were successfully processed. Do you want to remove only the successfully deleted items from the history list as well?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if confirm == QMessageBox.StandardButton.Yes:
                    # Remove only the successfully deleted URLs from database
                    db_path = ensure_database_schema()
                    if db_path:
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        for url in dialog.deleted_urls:
                            cursor.execute("DELETE FROM uploads WHERE url = ?", (url,))
                        conn.commit()
                        conn.close()
                
                # Refresh the window
                window.close()
                show_history_window()

    def remove_selection():
        selected_urls = []
        for row in range(table.rowCount()):
            if is_checkbox_checked(row):
                url_widget = table.cellWidget(row, 5)
                if isinstance(url_widget, QLabel):
                    raw_url = url_widget.property("raw_url")
                    if raw_url:
                        selected_urls.append(raw_url)

        if selected_urls:
            confirm = QMessageBox.question(
                window,
                "Confirm Remove Selection",
                "Are you sure you want to remove the selected items from the database?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if confirm == QMessageBox.StandardButton.Yes:
                db_path = ensure_database_schema()
                if db_path:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    for url in selected_urls:
                        cursor.execute("DELETE FROM uploads WHERE url = ?", (url,))
                        print(f"Successfully deleted {url}")
                    conn.commit()
                    conn.close()
                    QMessageBox.information(window, "Success", "Selected items have been removed from the database.")
                    window.close()
                    show_history_window()

    select_button.clicked.connect(toggle_select_mode)
    select_all_button.clicked.connect(select_all)
    mass_delete_button.clicked.connect(mass_delete_selection)
    remove_selection_button.clicked.connect(remove_selection)
    
    # Connect all checkbox signals to update mass delete button visibility
    for row in range(table.rowCount()):
        checkbox = get_checkbox_widget(row)
        if checkbox:
            checkbox.stateChanged.connect(update_mass_delete_visibility)

    button_layout.addWidget(select_button)
    button_layout.addWidget(select_all_button)
    button_layout.addStretch()
    button_layout.addWidget(mass_delete_button)
    button_layout.addWidget(remove_selection_button)

    layout.addLayout(button_layout)

    central_widget = QWidget()
    central_widget.setLayout(layout)
    window.setCentralWidget(central_widget)

    def show_context_menu(table, pos):
        index = table.indexAt(pos)
        if not index.isValid():
            return

        row, column = index.row(), index.column()
        item = table.item(row, column)

        # Check for a QLabel (for File Path or URL)
        widget = table.cellWidget(row, column)
        if isinstance(widget, QLabel):
            from PyQt6.QtGui import QTextDocument
            doc = QTextDocument()
            doc.setHtml(widget.text())
            text = doc.toPlainText()
            
            # Special handling for URL column (column 5)
            if column == 5:
                raw_url = widget.property("raw_url")
                if raw_url:
                    show_url_context_menu(widget, pos)
                    return
            # Special handling for File Path column (column 2)
            elif column == 2:
                # This will be handled by the file_label's custom context menu
                return
        elif item:
            text = item.text()
        else:
            return

        # Default context menu for other columns
        menu = QMenu()
        menu.setStyleSheet(get_menu_stylesheet(get_current_theme_colors()))
        copy_action = QAction("Copy")
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(text))
        menu.addAction(copy_action)
        menu.exec(QCursor.pos())

    def show_url_context_menu(widget, pos):
        """Show custom context menu for URL labels."""
        raw_url = widget.property("raw_url")
        file_path = widget.property("file_path")
        if not raw_url:
            return
        
        menu = QMenu()
        menu.setStyleSheet(get_menu_stylesheet(get_current_theme_colors()))
        
        # Copy action
        copy_action = QAction("Copy", menu)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(raw_url))
        menu.addAction(copy_action)
        
        # Copy embeddable action (only for videos)
        if is_video_file(raw_url):
            embed_url = generate_discord_embed_url(raw_url)
            
            copy_embed_action = QAction("Copy Embeddable", menu)
            copy_embed_action.triggered.connect(lambda: QApplication.clipboard().setText(embed_url))
            menu.addAction(copy_embed_action)
        
        open_action = QAction("Open in Browser", menu)
        open_action.triggered.connect(lambda: open_url_in_browser(raw_url))
        menu.addAction(open_action)
        
        menu.exec(widget.mapToGlobal(pos))

    table.setColumnHidden(0, True)  # Initially hide checkbox column
    window.show()

def open_url_in_browser(url):
    """Open URL in default browser."""
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception as e:
        QMessageBox.warning(None, "Error", f"Failed to open URL: {str(e)}")

def open_file_in_default_app(file_path):
    """Open file in default application."""
    try:
        os.startfile(file_path)
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to open file:\n{str(e)}")

def show_file_in_explorer(file_path):
    """Show file in Windows Explorer."""
    try:
        import subprocess
        subprocess.run(f'explorer /select,"{file_path}"', shell=True)
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to show file in explorer:\n{str(e)}")

def show_file_context_menu(widget, pos, file_path):
    """Show custom context menu for file path labels."""
    menu = QMenu()
    menu.setStyleSheet(get_menu_stylesheet(get_current_theme_colors()))
    
    # Copy file path action
    copy_action = QAction("Copy Path", menu)
    copy_action.triggered.connect(lambda: QApplication.clipboard().setText(file_path))
    menu.addAction(copy_action)
    
    # Open file action (only if file exists)
    if os.path.exists(file_path):
        open_action = QAction("Open File", menu)
        open_action.triggered.connect(lambda: open_file_in_default_app(file_path))
        menu.addAction(open_action)
        
        # Show in folder action
        show_in_folder_action = QAction("Show in Folder", menu)
        show_in_folder_action.triggered.connect(lambda: show_file_in_explorer(file_path))
        menu.addAction(show_in_folder_action)
    
    menu.exec(widget.mapToGlobal(pos))

class CustomCheckBox(QWidget):
    """Custom checkbox widget with visible checkmark."""
    stateChanged = pyqtSignal()  # Signal emitted when checkbox state changes
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.checked = False
        self._use_light_theme = is_windows_light_mode()
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
    def setChecked(self, checked):
        self.checked = checked
        self.update()
        
    def isChecked(self):
        return self.checked
        
    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        
    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self.checked)
            self.stateChanged.emit()  # Emit signal when state changes
            
    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QPen, QBrush, QFont
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Get theme colors
        colors = light_theme_colors if self._use_light_theme else dark_theme_colors
        
        # Draw the checkbox background
        rect = self.rect().adjusted(1, 1, -1, -1)
        
        if self.checked:
            # Blue background when checked
            brush = QBrush(QColor(colors['checkbox_checked']))
            painter.setBrush(brush)
            painter.setPen(QPen(QColor(colors['checkbox_checked']), 2))
        else:
            # Theme-appropriate background when unchecked
            brush = QBrush(QColor(colors['checkbox_bg']))
            painter.setBrush(brush)
            painter.setPen(QPen(QColor(colors['checkbox_border']), 2))
            
        painter.drawRoundedRect(rect, 3, 3)
        
        # Draw checkmark if checked
        if self.checked:
            painter.setPen(QPen(QColor(255, 255, 255), 2))  # White checkmark
            # Draw checkmark path
            check_points = [
                (rect.left() + 4, rect.center().y()),
                (rect.center().x() - 1, rect.bottom() - 5),
                (rect.right() - 4, rect.top() + 4)
            ]
            
            for i in range(len(check_points) - 1):
                painter.drawLine(check_points[i][0], check_points[i][1], 
                               check_points[i+1][0], check_points[i+1][1])
def reload_history(window):
    window.close()
    show_history_window()

def refresh_context_menu_icons():
    """Silently refresh context menu icons to match current theme."""
    try:
        from catbox import check_registry_keys, add_registry_keys, ensure_icons_directory
        ensure_icons_directory()
        if not check_registry_keys():
            add_registry_keys()
    except Exception:
        pass  # Silently ignore errors when refreshing icons

if __name__ == "__main__":
    app = QApplication(sys.argv)
    refresh_context_menu_icons()  # Refresh icons on launch
    show_history_window()
    sys.exit(app.exec())