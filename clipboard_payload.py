"""读取 Windows 剪贴板中的文字 + 图片（微信复制图文消息）。"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from text_encoding import encode_str

try:
    import win32clipboard
    import win32con

    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False

try:
    from PIL import Image, ImageGrab

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


@dataclass
class ClipboardPayload:
    text: str = ""
    images: list[bytes] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return bool(self.images)

    @property
    def has_content(self) -> bool:
        return bool((self.text or "").strip()) or self.has_images

    def fingerprint(self) -> str:
        h = hashlib.md5(encode_str(self.text or ""))
        for img in self.images:
            h.update(img[:8192])
            h.update(str(len(img)).encode())
        return h.hexdigest()

    def user_text(self) -> str:
        """供路由/日志使用的用户问题文本。"""
        text = (self.text or "").strip()
        if text and self.has_images:
            return f"{text}\n[附带{len(self.images)}张图片]"
        if self.has_images:
            return f"[图片消息，共{len(self.images)}张]"
        return text


def read_clipboard_payload() -> ClipboardPayload:
    payload = ClipboardPayload()
    payload.text = _read_unicode_text()
    payload.images.extend(_read_clipboard_images())
    payload.images = _dedupe_png_bytes(payload.images)
    return payload


def _read_unicode_text() -> str:
    if _HAS_WIN32:
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    return str(data or "").strip()
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            pass
    from win_clipboard import get_text

    return (get_text() or "").strip()


def _read_clipboard_images() -> list[bytes]:
    images: list[bytes] = []

    if _HAS_WIN32:
        images.extend(_read_html_images())
        images.extend(_read_dib_image())
        images.extend(_read_file_drop_images())

    if _HAS_PIL:
        images.extend(_read_via_image_grab())

    return images


def _read_html_images() -> list[bytes]:
    if not _HAS_WIN32:
        return []
    html = _read_html_format()
    if not html:
        return []
    return _parse_html_images(html)


def _read_html_format() -> str:
    try:
        cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(cf_html):
                return ""
            raw = win32clipboard.GetClipboardData(cf_html)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ""

    if isinstance(raw, bytes):
        for enc in ("utf-8", "gb18030", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                text = raw.decode("latin-1", errors="replace")
    else:
        text = str(raw)

    m = re.search(r"StartFragment:(\d+)", text)
    n = re.search(r"EndFragment:(\d+)", text)
    if m and n:
        start, end = int(m.group(1)), int(n.group(1))
        if 0 <= start < end <= len(text):
            return text[start:end]
    return text


def _parse_html_images(html: str) -> list[bytes]:
    out: list[bytes] = []
    if not html:
        return out

    for m in re.finditer(
        r"data:image/(?:png|jpe?g|gif|webp|bmp);base64,([A-Za-z0-9+/=\s]+)",
        html,
        re.I,
    ):
        try:
            blob = base64.b64decode(re.sub(r"\s+", "", m.group(1)))
            png = _to_png_bytes(blob)
            if png:
                out.append(png)
        except Exception:
            continue

    for m in re.finditer(r"""src=["']([^"']+)["']""", html, re.I):
        src = m.group(1).strip()
        if src.lower().startswith("data:"):
            continue
        path = _src_to_path(src)
        if path and _is_image_path(path):
            png = _file_to_png(path)
            if png:
                out.append(png)
    return out


def _src_to_path(src: str) -> str | None:
    src = unquote(src.strip())
    if src.lower().startswith("file:///"):
        path = src[8:].replace("/", "\\")
        if path.startswith("\\") and len(path) > 2 and path[2] != ":":
            path = path[1:]
        return path if os.path.isfile(path) else None
    if re.match(r"^[A-Za-z]:\\", src) and os.path.isfile(src):
        return src
    return None


def _read_dib_image() -> list[bytes]:
    if not _HAS_WIN32:
        return []
    try:
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                return []
            dib = win32clipboard.GetClipboardData(win32con.CF_DIB)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return []

    png = _dib_to_png(bytes(dib))
    return [png] if png else []


def _dib_to_png(dib: bytes) -> bytes | None:
    if len(dib) < 40:
        return None
    try:
        header_size = struct.unpack_from("<I", dib, 0)[0]
        if header_size < 40:
            return None
        width = struct.unpack_from("<i", dib, 4)[0]
        height = struct.unpack_from("<i", dib, 8)[0]
        if width <= 0 or height <= 0 or width > 20000 or height > 20000:
            return None
        planes, bit_count = struct.unpack_from("<HH", dib, 12)
        if bit_count not in (1, 4, 8, 16, 24, 32):
            return None
        off_bits = 14 + header_size
        if bit_count <= 8:
            num_colors = struct.unpack_from("<I", dib, 32)[0]
            if num_colors == 0:
                num_colors = 1 << bit_count
            color_table_size = num_colors * 4
            off_bits = 14 + header_size + color_table_size
        file_size = off_bits + len(dib) - header_size
        bmp = bytearray()
        bmp.extend(b"BM")
        bmp.extend(struct.pack("<I", file_size))
        bmp.extend(b"\x00\x00\x00\x00")
        bmp.extend(struct.pack("<I", off_bits))
        bmp.extend(dib)
        if _HAS_PIL:
            img = Image.open(io.BytesIO(bytes(bmp)))
            return _pil_to_png(img)
    except Exception:
        pass
    return None


def _read_file_drop_images() -> list[bytes]:
    if not _HAS_WIN32:
        return []
    try:
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                return []
            paths = win32clipboard.GetClipboardData(win32con.CF_HDROP)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return []

    out: list[bytes] = []
    if not paths:
        return out
    for path in paths:
        if _is_image_path(path):
            png = _file_to_png(path)
            if png:
                out.append(png)
    return out


def _read_via_image_grab() -> list[bytes]:
    try:
        data = ImageGrab.grabclipboard()
    except Exception:
        return []
    if data is None:
        return []
    if _HAS_PIL and isinstance(data, Image.Image):
        png = _pil_to_png(data)
        return [png] if png else []
    if isinstance(data, list):
        out: list[bytes] = []
        for path in data:
            if isinstance(path, str) and _is_image_path(path):
                png = _file_to_png(path)
                if png:
                    out.append(png)
        return out
    return []


def _is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


def _file_to_png(path: str) -> bytes | None:
    if not _HAS_PIL or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as img:
            return _pil_to_png(img)
    except Exception:
        return None


def _to_png_bytes(blob: bytes) -> bytes | None:
    if not _HAS_PIL:
        return blob or None
    try:
        with Image.open(io.BytesIO(blob)) as img:
            return _pil_to_png(img)
    except Exception:
        return None


def _pil_to_png(img: Image.Image) -> bytes | None:
    try:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _dedupe_png_bytes(images: list[bytes]) -> list[bytes]:
    seen: set[str] = set()
    out: list[bytes] = []
    for img in images:
        if not img:
            continue
        key = hashlib.md5(img).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(img)
    return out


def save_images_to_cache(
    images: list[bytes],
    workspace: str,
    *,
    subdir: str = ".wechat_bot_cache/images",
    max_images: int = 4,
) -> list[str]:
    """把图片保存到 workspace 下，供 Cursor Agent 读取。"""
    if not images:
        return []
    root = Path(workspace) if workspace and os.path.isdir(workspace) else Path.cwd()
    cache_dir = root / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    ts = int(__import__("time").time())
    for i, data in enumerate(images[:max_images]):
        path = cache_dir / f"clip_{ts}_{i}.png"
        path.write_bytes(data)
        paths.append(str(path.resolve()))
    return paths
