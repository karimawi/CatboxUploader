import os
import io
import mimetypes
from PIL import Image
import fitz  # PyMuPDF
import cv2
from mutagen.mp3 import MP3
from mutagen.id3 import ID3
from win32com.shell import shell, shellcon
import win32api
import win32con
import win32ui
import win32gui

def get_image_thumbnail(filepath):
    return Image.open(filepath)

def get_video_thumbnail(filepath):
    cap = cv2.VideoCapture(filepath)
    success, frame = cap.read()
    cap.release()
    if not success:
        raise Exception("Could not read video frame.")
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame)

def get_pdf_thumbnail(filepath):
    doc = fitz.open(filepath)
    if len(doc) == 0:
        raise Exception("Empty PDF.")
    page = doc.load_page(0)
    pix = page.get_pixmap()
    return Image.open(io.BytesIO(pix.tobytes("png")))

def get_mp3_album_art(filepath):
    audio = MP3(filepath, ID3=ID3)
    for tag in audio.tags.values():
        if tag.FrameID == 'APIC':
            return Image.open(io.BytesIO(tag.data))
    raise Exception("No album art found.")

def get_icon(PATH, size, fallback=False):
    SHGFI_ICON = 0x000000100
    SHGFI_ICONLOCATION = 0x000001000
    if size == "small":
        SHIL_SIZE = 0x00001
    elif size == "large":
        SHIL_SIZE = 0x00004
    else:
        raise TypeError("Invalid argument for 'size'. Must be 'small' or 'large'")
        
    ret, info = shell.SHGetFileInfo(PATH, 0, SHGFI_ICONLOCATION | SHGFI_ICON | SHIL_SIZE)
    hIcon, iIcon, dwAttr, name, typeName = info
    ico_x = win32api.GetSystemMetrics(win32con.SM_CXICON)
    hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
    hbmp = win32ui.CreateBitmap()
    hbmp.CreateCompatibleBitmap(hdc, ico_x, ico_x)
    hdc = hdc.CreateCompatibleDC()
    hdc.SelectObject(hbmp)
    hdc.DrawIcon((0, 0), hIcon)
    win32gui.DestroyIcon(hIcon)

    bmpinfo = hbmp.GetInfo()
    bmpstr = hbmp.GetBitmapBits(True)
    img = Image.frombuffer(
        "RGBA",
        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
        bmpstr, "raw", "BGRA", 0, 1
    )

    if size == "small":
        img = img.resize((16, 16), Image.LANCZOS)
    elif fallback:
        img = img.resize((120, 120), Image.LANCZOS)
    else:
        img = img.resize((60, 60), Image.LANCZOS)
    return img

def generate_thumbnail(filepath) -> Image.Image:
    ext = os.path.splitext(filepath)[1].lower()
    mime, _ = mimetypes.guess_type(filepath)

    canvas_size = 256

    try:
        # Generate thumbnail image
        if mime and mime.startswith("image"):
            thumb = get_image_thumbnail(filepath)
        elif mime and mime.startswith("video"):
            thumb = get_video_thumbnail(filepath)
        elif ext == ".pdf":
            thumb = get_pdf_thumbnail(filepath)
        elif ext == ".mp3":
            thumb = get_mp3_album_art(filepath)
        else:
            raise Exception(f"Unsupported file type: {ext}")

        # Resize thumbnail proportionally
        thumb.thumbnail((canvas_size, canvas_size), Image.LANCZOS)
        thumb_w, thumb_h = thumb.size

        # Create 256x256 transparent canvas and center the thumbnail
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 0))
        thumb_x = (canvas_size - thumb_w) // 2
        thumb_y = (canvas_size - thumb_h) // 2
        canvas.paste(thumb, (thumb_x, thumb_y))

        # Get and resize icon
        icon = get_icon(filepath, size="large")
        icon_w, icon_h = icon.size

        # Align icon relative to bottom-right of the thumbnail
        padding = 4
        icon_x = thumb_x + thumb_w - icon_w + padding
        icon_y = thumb_y + thumb_h - icon_h + padding

        canvas.paste(icon, (icon_x, icon_y), mask=icon)
        return canvas

    except Exception as e:
        print(f"Failed to generate thumbnail for {filepath}: {e}")
        # Fallback to just centered icon
        icon = get_icon(filepath, size="large", fallback=True)
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 0))
        icon_w, icon_h = icon.size
        icon_pos = ((canvas_size - icon_w) // 2, (canvas_size - icon_h) // 2)
        canvas.paste(icon, icon_pos, mask=icon)
        return canvas

# Example usage
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python thumbnailer.py <file>")
    else:
        input_path = sys.argv[1]
        thumbnail_img = generate_thumbnail(input_path)
        thumbnail_img.show()  # Preview in default image viewer
