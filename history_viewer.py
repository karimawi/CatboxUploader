import ctypes
import os
import sqlite3
import sys
import time
import winreg
from datetime import datetime

import requests
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QAction, QCursor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout,
                             QHeaderView, QLabel, QMainWindow, QMenu,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget, QToolTip)

from thumb import generate_thumbnail

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# Constants
DB_NAME = "catbox.db"
EXPIRED_ICON_ID = 16777
SHELL32_DLL = "C:\\WINDOWS\\System32\\SHELL32.dll"
ico_path = os.path.join(application_path, "icon.ico")
REG_PATH = r"Software\CatboxUploader"

# API Endpoints
API_CATBOX = "https://catbox.moe/user/api.php"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

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

def log_upload(file_path, url, mode, expiry_duration=None):
    try:
        file_path = os.path.abspath(file_path)
        db_path = os.path.join(application_path, DB_NAME)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                url TEXT,
                mode TEXT,
                timestamp INTEGER,
                expiry_duration TEXT,
                is_deleted INTEGER DEFAULT 0
            )
        """)

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
    db_path = os.path.join(application_path, DB_NAME)
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, url, mode, timestamp, expiry_duration, is_deleted FROM uploads ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

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

def create_thumbnail(path, deleted=False):
    if not deleted:
        try:
            thumb = generate_thumbnail(path)
            pixmap = QPixmap.fromImage(thumb.toqpixmap().toImage())
            return QIcon(pixmap)
        except:
            pass
    return QIcon(os.path.join(application_path, "del.ico"))

def show_history_window():
    window = QMainWindow()
    window.setWindowIcon(QIcon(ico_path))
    window.setWindowTitle("Upload History")
    window.setMinimumSize(840, 500)

    # Add reload button
    reload_button = QPushButton()
    reload_button.setIcon(QIcon(os.path.join(application_path, "reload.ico")))
    reload_button.setFixedSize(30, 30)
    reload_button.setToolTip("Reload")
    reload_button.setCursor(Qt.CursorShape.PointingHandCursor)
    reload_button.clicked.connect(lambda: reload_history(window))

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
    table.setStyleSheet("""
        QTableWidget {
            background-color: #2D2D2D;
            alternate-background-color: #262626;
            color: white;
        }
        QHeaderView::section {
            background-color: #3C3C3C;
            color: white;
        }
    """)

    def load_table_data():
        uploads = load_uploads()
        table.setRowCount(len(uploads))

        for row_index, (file_path, url, mode, timestamp, expiry, is_deleted) in enumerate(uploads):
            file_exists = os.path.exists(file_path)
            mode_label, is_expired = format_mode(mode, expiry, timestamp)

            # Set row height (double default)
            table.setRowHeight(row_index, 50)

            # 0. Checkbox
            checkbox = QTableWidgetItem()
            checkbox.setCheckState(Qt.CheckState.Unchecked)
            checkbox.setFlags(Qt.ItemFlag.NoItemFlags)  # Initially disabled
            table.setItem(row_index, 0, checkbox)

            # 1. Thumbnail
            icon = create_thumbnail(file_path, deleted=not file_exists)
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
            table.setCellWidget(row_index, 2, file_label)
            file_label.setToolTip(file_path)

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
                delete_button.setIcon(QIcon(os.path.join(application_path, "bin.ico")))
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
                                    db_path = os.path.join(application_path, "catbox.db")
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
    remove_selection_button = QPushButton("Remove Selection")

    select_all_button.setVisible(False)
    remove_selection_button.setVisible(False)
    remove_selection_button.setEnabled(False)

    def toggle_select_mode():
        if select_button.text() == "Select":
            select_button.setText("Cancel")
            select_all_button.setVisible(True)
            remove_selection_button.setVisible(True)
            remove_selection_button.setEnabled(True)
            table.setColumnHidden(0, False)  # Show checkbox column
            for row in range(table.rowCount()):
                table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
                table.item(row, 0).setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        else:
            select_button.setText("Select")
            select_all_button.setVisible(False)
            remove_selection_button.setVisible(False)
            table.setColumnHidden(0, True)  # Hide checkbox column
            for row in range(table.rowCount()):
                table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
                table.item(row, 0).setFlags(Qt.ItemFlag.NoItemFlags)

    def select_all():
        for row in range(table.rowCount()):
            table.item(row, 0).setCheckState(Qt.CheckState.Checked)
        remove_selection_button.setEnabled(True)

    def clear_selection():
        for row in range(table.rowCount()):
            table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        remove_selection_button.setEnabled(False)

    def remove_selection():
        selected_urls = []
        for row in range(table.rowCount()):
            if table.item(row, 0).checkState() == Qt.CheckState.Checked:
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
                db_path = os.path.join(application_path, "catbox.db")
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
    remove_selection_button.clicked.connect(remove_selection)

    button_layout.addWidget(select_button)
    button_layout.addWidget(select_all_button)
    button_layout.addStretch()
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
        elif item:
            text = item.text()
        else:
            return

        menu = QMenu()
        copy_action = QAction("Copy")
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(text))
        menu.addAction(copy_action)
        menu.exec(QCursor.pos())

    table.setColumnHidden(0, True)  # Initially hide checkbox column
    window.show()

def reload_history(window):
    window.close()
    show_history_window()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    show_history_window()
    sys.exit(app.exec())