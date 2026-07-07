"""Windows 剪贴板读写（编码与项目一致，默认 GB18030）。"""
from __future__ import annotations

import base64
import os
import subprocess

from text_encoding import FILE_ENCODING, encode_str


def _ps_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def get_text() -> str:
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"[Console]::OutputEncoding=[Text.Encoding]::GetEncoding('{FILE_ENCODING}'); "
                "Get-Clipboard -Raw",
            ],
            capture_output=True,
            text=True,
            encoding=FILE_ENCODING,
            errors="replace",
            timeout=5,
            creationflags=_ps_flags(),
        )
        if proc.returncode == 0 and proc.stdout is not None:
            return proc.stdout
    except Exception:
        pass
    return ""


def set_text(text: str) -> bool:
    b64 = base64.b64encode(encode_str(text)).decode("ascii")
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"$enc=[Text.Encoding]::GetEncoding('{FILE_ENCODING}'); "
                f"$t=$enc.GetString([Convert]::FromBase64String('{b64}')); "
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Clipboard]::SetText($t)",
            ],
            capture_output=True,
            text=True,
            encoding=FILE_ENCODING,
            errors="replace",
            timeout=5,
            creationflags=_ps_flags(),
        )
        if proc.returncode == 0:
            return True
    except Exception:
        pass
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"[Console]::InputEncoding=[Text.Encoding]::GetEncoding('{FILE_ENCODING}'); "
                "Set-Clipboard -Value $input",
            ],
            input=text,
            capture_output=True,
            text=True,
            encoding=FILE_ENCODING,
            errors="replace",
            timeout=5,
            creationflags=_ps_flags(),
        )
        return proc.returncode == 0
    except Exception:
        return False


def set_files(paths: list[str]) -> bool:
    """把文件复制到剪贴板（CF_HDROP），微信里 Ctrl+V 可发送文件。"""
    abs_paths: list[str] = []
    for p in paths:
        try:
            fp = os.path.abspath(p)
            if os.path.isfile(fp):
                abs_paths.append(fp)
        except Exception:
            continue
    if not abs_paths:
        return False

    ps_paths = "','".join(p.replace("'", "''") for p in abs_paths)
    ps_cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$col = New-Object System.Collections.Specialized.StringCollection; "
        f"@('{ps_paths}') | ForEach-Object {{ [void]$col.Add($_) }}; "
        "[System.Windows.Forms.Clipboard]::SetFileDropList($col)"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding=FILE_ENCODING,
            errors="replace",
            timeout=8,
            creationflags=_ps_flags(),
        )
        return proc.returncode == 0
    except Exception:
        return False
