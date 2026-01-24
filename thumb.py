import os
import io
import mimetypes
from PIL import Image
import pymupdf as fitz
from mutagen.mp3 import MP3
from mutagen.id3 import ID3
from win32com.shell import shell, shellcon
import win32api
import win32con
import win32ui
import win32gui
import ctypes
from ctypes import wintypes

# Define ctypes structures for IShellItemImageFactory
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

# IID_IShellItemImageFactory = {bcc18b79-ba16-442f-80c4-8a59c30c463b}
IID_IShellItemImageFactory = GUID(0xbcc18b79, 0xba16, 0x442f, 
                                  (wintypes.BYTE * 8)(0x80, 0xc4, 0x8a, 0x59, 0xc3, 0x0c, 0x46, 0x3b))

SIIGBF_THUMBNAILONLY = 0x08
SIIGBF_BIGGERSIZEOK = 0x01

shell32 = ctypes.windll.shell32

def get_image_thumbnail(filepath):
    return Image.open(filepath)

def get_video_thumbnail(filepath):
    # Use Windows IShellItemImageFactory via ctypes to avoid cv2 dependency
    
    # Define argtypes
    shell32.SHCreateItemFromParsingName.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
    ]
    shell32.SHCreateItemFromParsingName.restype = ctypes.HRESULT
    
    ptr = ctypes.c_void_p()
    hr = shell32.SHCreateItemFromParsingName(filepath, None, ctypes.byref(IID_IShellItemImageFactory), ctypes.byref(ptr))
    
    if hr != 0:
        raise Exception(f"SHCreateItemFromParsingName failed: 0x{hr:08x}")
        
    try:
        # GetImage is at index 3 in vtable
        obj = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))
        vtable = ctypes.cast(obj.contents, ctypes.POINTER(ctypes.c_void_p))
        
        GetImage_t = ctypes.CFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP))
        GetImage = ctypes.cast(vtable[3], GetImage_t)
        
        Release_t = ctypes.CFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
        Release = ctypes.cast(vtable[2], Release_t)

        hbitmap = wintypes.HBITMAP()
        sz = SIZE(256, 256)
        flags = SIIGBF_THUMBNAILONLY | SIIGBF_BIGGERSIZEOK
        
        hr = GetImage(ptr, sz, flags, ctypes.byref(hbitmap))
        
        # Always release the interface
        Release(ptr)
        
        if hr != 0:
            raise Exception(f"GetImage failed: 0x{hr:08x}")
            
        try:
            # Convert HBITMAP to PIL Image
            # hbitmap is a ctypes object, we need the integer handle
            hbitmap_handle = hbitmap.value 
            
            bmp_info = win32gui.GetObject(hbitmap_handle)
            w, h = bmp_info.bmWidth, bmp_info.bmHeight
            
            hdc_screen = win32gui.GetDC(0)
            hdc_mem_src = win32gui.CreateCompatibleDC(hdc_screen)
            win32gui.SelectObject(hdc_mem_src, hbitmap_handle)
            
            # Destination
            hdc_mem_dest = win32ui.CreateDCFromHandle(hdc_screen).CreateCompatibleDC()
            dest_bmp = win32ui.CreateBitmap()
            dest_bmp.CreateCompatibleBitmap(win32ui.CreateDCFromHandle(hdc_screen), w, h)
            hdc_mem_dest.SelectObject(dest_bmp)
            
            # Copy
            win32gui.BitBlt(hdc_mem_dest.GetSafeHdc(), 0, 0, w, h, hdc_mem_src, 0, 0, win32con.SRCCOPY)
            
            bmpstr = dest_bmp.GetBitmapBits(True)
            
            # Cleanup DCs and Bitmaps
            win32gui.DeleteDC(hdc_mem_src)
            win32gui.ReleaseDC(0, hdc_screen)
            # dest_bmp cleaned up by win32ui object
            
            img = Image.frombuffer(
                "RGBA",
                (w, h),
                bmpstr, "raw", "BGRA", 0, 1
            )
            return img
            
        finally:
            if hbitmap.value:
                win32gui.DeleteObject(hbitmap.value)
            
    except Exception as e:
        # Ensure we release ptr if we failed getting vtable or something (though usually ptr is valid if SHCreateItem succeeded)
        # But we called Release() above explicitly.
        raise e

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
