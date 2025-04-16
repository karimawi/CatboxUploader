import argparse
import mimetypes
import os
import sys
import time
import traceback
import winreg
from thumb import generate_thumbnail
from history_viewer import log_upload
import pythoncom
import requests
import PIL.Image as Image
from moviepy.video.io.VideoFileClip import VideoFileClip
from PyQt6.QtCore import (Qt, QThread, QTimer, pyqtSignal,
                          pyqtSlot)
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QInputDialog,
                             QLabel, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QTextEdit, QVBoxLayout, QWidget)
from requests_toolbelt.multipart.encoder import (MultipartEncoder,
                                                 MultipartEncoderMonitor)

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    base_path = sys._MEIPASS
    os.environ['TCL_LIBRARY'] = os.path.join(base_path, 'tcl')
    os.environ['TK_LIBRARY'] = os.path.join(base_path, 'tk')
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

ico_path = os.path.join(application_path, "icon.ico")
REG_PATH = r"Software\CatboxUploader"

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
icon_path = f'"{cwd}\\icon.ico"'

CONTEXT_MENU_KEYS = [
    (r"Software\Classes\*\shell\Catbox", "Catbox", True),
    
    # Ordered sub-items
    (r"Software\Classes\*\shell\Catbox\shell\001_upload_user", "📤 Upload as User", False),
    (r"Software\Classes\*\shell\Catbox\shell\001_upload_user\command", f'"{cwd}\\catbox.exe" "%1"', False),

    (r"Software\Classes\*\shell\Catbox\shell\002_upload_anon", "👤 Upload anonymously", False),
    (r"Software\Classes\*\shell\Catbox\shell\002_upload_anon\command", f'"{cwd}\\catbox.exe" --anonymous "%1"', False),

    (r"Software\Classes\*\shell\Catbox\shell\003_edit_userhash", "⚙️ Edit userhash", False),
    (r"Software\Classes\*\shell\Catbox\shell\003_edit_userhash\command", f'"{cwd}\\catbox.exe" --edit-userhash', False),
    
    (r"Software\Classes\*\shell\Catbox\shell\004_history", "🕓 Upload History", False),
    (r"Software\Classes\*\shell\Catbox\shell\004_history\command", f'"{cwd}\\catbox.exe" --history', False),

    (r"Software\Classes\*\shell\Litterbox", "Litterbox", True),
    
    # Ordered expiration times
    (r"Software\Classes\*\shell\Litterbox\shell\001_litterbox_1h", "1h", False),
    (r"Software\Classes\*\shell\Litterbox\shell\001_litterbox_1h\command", f'"{cwd}\\catbox.exe" --litterbox 1h "%1"', False),

    (r"Software\Classes\*\shell\Litterbox\shell\002_litterbox_12h", "12h", False),
    (r"Software\Classes\*\shell\Litterbox\shell\002_litterbox_12h\command", f'"{cwd}\\catbox.exe" --litterbox 12h "%1"', False),

    (r"Software\Classes\*\shell\Litterbox\shell\003_litterbox_24h", "24h", False),
    (r"Software\Classes\*\shell\Litterbox\shell\003_litterbox_24h\command", f'"{cwd}\\catbox.exe" --litterbox 24h "%1"', False),

    (r"Software\Classes\*\shell\Litterbox\shell\004_litterbox_72h", "72h", False),
    (r"Software\Classes\*\shell\Litterbox\shell\004_litterbox_72h\command", f'"{cwd}\\catbox.exe" --litterbox 72h "%1"', False),
]

def check_registry_keys():
    """Check if all context menu registry keys exist and have the correct values."""
    missing_or_incorrect_keys = []

    for key_path, value, is_parent in CONTEXT_MENU_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                if "command" in key_path:
                    # For command keys, check if the value matches the current executable path
                    current_value, _ = winreg.QueryValueEx(key, "")
                    if current_value != value:
                        missing_or_incorrect_keys.append((key_path, value))
                else:
                    # For non-command keys, check if the MUIVerb value matches
                    current_value, _ = winreg.QueryValueEx(key, "MUIVerb")
                    if current_value != value:
                        missing_or_incorrect_keys.append((key_path, value))
        except FileNotFoundError:
            # If the key doesn't exist, add it to the list of missing keys
            missing_or_incorrect_keys.append((key_path, value))

    return not missing_or_incorrect_keys  # True if no keys are missing or incorrect

def add_registry_keys():
    """Add or update context menu registry keys."""
    try:
        for key_path, value, is_parent in CONTEXT_MENU_KEYS:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                if "command" in key_path:
                    # For command keys, set the value to the current executable path
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
                else:
                    # For non-command keys, set the MUIVerb value
                    winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, value)
                    if is_parent:
                        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)  # Set icon
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
        if not check_registry_keys():
            if add_registry_keys():
                app.setWindowIcon(QIcon(ico_path))
                QMessageBox.information(None, "Context Menu Updated", "Context menu buttons have been added & updated.")
        sys.exit(0)

# Handle --edit-userhash separately
if args.edit_userhash:
    new_userhash = prompt_for_userhash()
    print(f"Userhash updated: {new_userhash}")
    sys.exit(0)

# Ensure userhash exists if not in anonymous mode
USER_HASH = read_registry_value("userhash")

if not USER_HASH and args.file and not args.anonymous:
    USER_HASH = prompt_for_userhash()

class UploadWorker(QThread):
    update_progress = pyqtSignal(int)  # Signal for progress percentage
    update_bytes_uploaded = pyqtSignal(int)  # Signal for bytes uploaded
    upload_finished = pyqtSignal(str)  # Signal for upload completion

    def __init__(self, file_path, is_anonymous=False, litterbox_time=None):
        super().__init__()
        self.file_path = file_path
        self.is_anonymous = is_anonymous
        self.litterbox_time = litterbox_time
        self.session = requests.Session()
        self.bytes_uploaded = 0
        self.file_size = os.path.getsize(file_path)

    def run(self):
        pythoncom.CoInitialize()
        fields = {"reqtype": "fileupload"}
        api_url = API_CATBOX if not self.litterbox_time else API_LITTERBOX
        
        if self.file_size == 0:
            self.upload_finished.emit("⚠️ Error: File is empty.")
            return
        if self.litterbox_time:
            fields["time"] = self.litterbox_time
        elif not self.is_anonymous:
            fields["userhash"] = USER_HASH

        fields["fileToUpload"] = (os.path.basename(self.file_path), open(self.file_path, "rb"), "application/octet-stream")

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            with open(self.file_path, "rb") as f:
                monitor = MultipartEncoderMonitor(MultipartEncoder(fields=fields), self.update_monitor)
                headers = {"User-Agent": USER_AGENT, "Content-Type": monitor.content_type}
                try:
                    response = self.session.post(api_url, data=monitor, headers=headers, stream=True)
                    if response.status_code == 200 and "https://" in response.text:
                        self.upload_finished.emit(response.text.strip())
                        return
                    else:
                        error_msg = f"⚠️ Upload failed: {response.status_code} - {response.text.strip()}"
                        self.upload_finished.emit(error_msg)
                        return
                except requests.exceptions.SSLError as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        self.upload_finished.emit(f"⚠️ SSL Error: {str(e)} (Max retries exceeded)")
                        return
                    time.sleep(5)  # Wait 5 seconds before retrying
                except requests.exceptions.RequestException as e:
                    self.upload_finished.emit(f"⚠️ Upload failed: {str(e)}")
                    return

    def update_monitor(self, monitor):
        self.bytes_uploaded = monitor.bytes_read
        progress = int((self.bytes_uploaded / self.file_size) * 100)
        self.update_progress.emit(progress)  # Emit progress percentage
        self.update_bytes_uploaded.emit(self.bytes_uploaded)  # Emit bytes uploaded

def pil_image_to_qpixmap(pil_image: Image.Image) -> QPixmap:
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)

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
        self.setStyleSheet("background-color: #1E1E1E;")

        layout = QHBoxLayout()
        self.thumbnail_label = QLabel(self)
        pixmap = pil_image_to_qpixmap(generate_thumbnail(self.file_path))
        self.thumbnail_label.setPixmap(pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio))
        layout.addWidget(self.thumbnail_label)

        right_layout = QVBoxLayout()

        # Create file label
        self.file_label = QLabel(f"Uploading: {os.path.basename(file_path)}")
        self.file_label.setWordWrap(True)  # Enable word wrap

        self.file_label.setStyleSheet("background-color: #1E1E1E; color: white;")

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)  # Allow the label to resize within the scroll area
        scroll_area.setWidget(self.file_label)

        scroll_area.setStyleSheet("background-color: #1E1E1E; border: none;")

        right_layout.addWidget(scroll_area)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(20)  # Set the height of the progress bar to make it thicker
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid grey;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #697DA0;
            }
        """)

        right_layout.addWidget(self.progress_bar)

        self.eta_label = QLabel("ETA: Starting...")
        right_layout.addWidget(self.eta_label)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("background-color: #3C3C3C;")
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
        if self.uploading and self.bytes_uploaded > 0:
            elapsed_time = time.time() - self.start_time
            upload_speed = self.bytes_uploaded / elapsed_time if elapsed_time > 0 else 0
            remaining_size = self.file_size - self.bytes_uploaded
            eta = remaining_size / upload_speed if upload_speed > 0 else 0

            self.eta_label.setText(f"ETA: {int(eta)}s")
        else:
            self.eta_label.setText("ETA: Starting...")

    @pyqtSlot(str)
    def update_ui_after_upload(self, result):
        if "http" in result:
            self.file_label.setText(f"<p>✅ Uploaded: <a href='{result}'>{result}</a></p>")
            self.file_label.setOpenExternalLinks(True)
            QApplication.clipboard().setText(result)
        else:
            self.file_label.setText(result)
            
        self.cancel_button.setText("OK")
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

    def cancel_upload(self):
        """Cancels the upload and closes the application."""
        self.cancelled = True
        self.uploading = False
        self.upload_worker.quit()

        self.close()
        os._exit(0)

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

if __name__ == "__main__":
    main()
    app = QApplication(sys.argv)
    sys.stderr = ErrorHandler(app)  # Redirect stderr
    sys.excepthook = show_critical_error  # Handle uncaught exceptions

    try:
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
