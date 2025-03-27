<p align="center">
  <picture>
    <source srcset="https://github.com/user-attachments/assets/c2f437b0-0f8a-4e48-b109-ac149804d335" media="(prefers-color-scheme: dark)">
    <img src="https://github.com/user-attachments/assets/786784c0-c040-4c3e-ac39-e3f3e152d853" alt="(WE) Telecom Egypt Quota Check" height="auto"">
  </picture>

</p>

---

<h1 align="center"><img src="https://github.com/user-attachments/assets/a391bc7a-a4b7-4233-b651-0bd51c6930fc" alt="Catbox" width=40 style="vertical-align:top"/> Catbox Uploader for Windows</h1>

A Windows-based context menu tool to upload files to [Catbox.moe](https://catbox.moe) and [Litterbox.catbox.moe](https://litterbox.catbox.moe) with a slick GUI progress bar, thumbnail previews, upload history, and options to upload anonymously or with a saved userhash.

---

## 🚀 Features

- ✅ **Right-click Context Menu Integration** for quick uploads and automatically copy the URL to clipboard
- 🧾 **Upload History Viewer** storing all the uploads in a local SQL DB with thumbnails and status, marking deleted files and expired links in red-strikedthrough text
- 🗑  **Delete files from Catbox user data right from the history window**
- 👤 **Userhash Authentication** (optional)  
- 🕵️‍♂️ **Anonymous Upload Mode**  
- ⏳ **Litterbox Support** (1h, 12h, 24h, 72h expiration)  
- 📊 **Live Progress Bar** with file thumbnails  
- 🖼️ Generates thumbnails for images, videos, and common file types

---

## 🧩 Installation

### ✅ 1. Download or Build

- Download the latest Windows Installer Package from the [releases tab](https://github.com/karimawi/CatboxUploader/releases/latest)
- Or build it yourself using `PyInstaller`:

1. Clone the repo and open the terminal inside the installation directory using:
   ```bash
   git clone https://github.com/karimawi/CatboxUploader
   ```
   
2. Install the requred dependencies
   ```bash
   pip install -r requirements.txt
   ```
3. Build using `PyInstaller`:
```bash
pyinstaller --noconfirm --onedir --windowed --icon ".\icon.ico" --add-data ".\bin.ico;." --add-data ".\del.ico;." --add-data ".\icon.ico;." --add-data ".\reload.ico;." --add-data ".`\unins.vbs;."  ".\catbox.py"
```

### 📂 2. Run Once to Setup Context Menu
#### When you run the program for the first time with no arguments, It will add context menu entries for Catbox and Litterbox in the registry
---

## 🖱️ Usage

Right-click any file and choose one of the options:
![cm](https://github.com/user-attachments/assets/d7bc6251-0333-4307-bc42-66d43f386ab5)


### 📤 Catbox Menu

- **Upload as User** – Uses your saved `userhash`
- **Upload Anonymously** – No login needed
- **Edit Userhash** – Set or update your Catbox userhash
- **Upload History** – View a list of previous uploads with links and thumbnails

### ⌛ Litterbox Menu

- Upload with expiration times:
  - `1h`, `12h`, `24h`, `72h`

---

## 🔧 Command-Line Options

You can also run from the command line:

```bash
catbox.exe [--anonymous] [--litterbox {1h,12h,24h,72h}] <file>
```

| Option | Description |
|--------|-------------|
| `<file>` | File to upload |
| `--anonymous` | Upload without userhash |
| `--litterbox` | Upload with expiry (Litterbox) |
| `--edit-userhash` | Prompt to enter a new userhash |
| `--history` | Show upload history GUI |

---

![upload2_userhash](https://github.com/user-attachments/assets/30660e13-7981-4579-8cc9-9405f483ed76)


## 📁 Upload History

Each upload is logged with:

- ✅ Status (success or failure)
- 🔗 Link to uploaded file
- 🖼️ Thumbnail (for media types)
- 📅 Timestamp
- 📄 Local file path (with deleted file marking if missing)

![history1](https://github.com/user-attachments/assets/38be54cc-3a4e-4b1f-a2df-1bd10964c548)

---

## 🔐 Where is the userhash stored?

It's saved securely under:

```
HKEY_CURRENT_USER\Software\CatboxUploader
```

Use `--edit-userhash` anytime to update it via a GUI prompt.

---

## 🎥 Demo GIF


---

## 💡 Tips

- Run `catbox.exe` with no arguments to re-register or update context menu
- You can safely delete and re-run to reset registry entries
- Upload history helps you keep track of everything you've uploaded with no retention
- You can bulk upload if you select more than one file, the program will launch multiple instances for each file
- You might struggle with SSL or Timeout error when uploading large files, this is due to the Catbox's API limitiations, it cannot keep an open connection for such long periods of time if you don't have fast enough internet to upload your file
---

## 🐾 Credits

 Catbox API by [Catbox.moe](https://catbox.moe)
  ❤️ Support them here https://catbox.moe/support.php

---

## 🧪 Future Plans

- Drag-and-drop upload support
- Upload queue for multiple files
- Auto-thumbnail generator for more file types
- Dark mode toggle

---

## 📜 License

GNU General Public License v3.0
