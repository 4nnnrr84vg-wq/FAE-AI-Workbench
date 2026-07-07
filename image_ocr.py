"""本地 OCR：Cursor / 视觉 API 不可用时，从截图提取文字。"""
from __future__ import annotations

import re
from pathlib import Path

_RAPID_OCR = None


def _get_rapid_ocr():
    global _RAPID_OCR
    if _RAPID_OCR is False:
        return None
    if _RAPID_OCR is not None:
        return _RAPID_OCR
    try:
        from rapidocr_onnxruntime import RapidOCR

        _RAPID_OCR = RapidOCR()
        return _RAPID_OCR
    except Exception:
        _RAPID_OCR = False
        return None


def extract_text_from_paths(paths: list[str]) -> str:
    """对多张图片做 OCR，合并后返回文本。"""
    chunks: list[str] = []
    seen: set[str] = set()
    for path in paths:
        text = ocr_image_file(path)
        norm = re.sub(r"\s+", " ", (text or "").strip())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        chunks.append(text.strip())
    return "\n\n".join(chunks).strip()


def ocr_image_file(path: str) -> str:
    path = str(Path(path).resolve())
    if not Path(path).is_file():
        return ""
    return _ocr_rapid(path) or _ocr_windows_media(path)


def _ocr_rapid(path: str) -> str:
    engine = _get_rapid_ocr()
    if engine is None:
        return ""
    try:
        result, _ = engine(path)
        if not result:
            return ""
        lines = [str(item[1]).strip() for item in result if len(item) > 1 and str(item[1]).strip()]
        return "\n".join(lines).strip()
    except Exception:
        return ""


def _ocr_windows_media(path: str) -> str:
    """Windows 10+ 内置 OCR 备用。"""
    import subprocess

    ps_path = path.replace("'", "''")
    ps_script = rf"""
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$loader = [Windows.Storage.FileIO, Windows.Storage, ContentType=WindowsRuntime]
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
function Await($AsyncOp, $TypeName) {{
  $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and !$_.IsGenericMethod
  }} | Select-Object -First 1
  if ($method) {{
    $task = $method.Invoke($null, @($AsyncOp))
    $task.Wait(-1) | Out-Null
    return $task.Result
  }}
  return $null
}}
$p = '{ps_path}'
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) $null
if ($null -eq $file) {{ exit 1 }}
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) $null
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) $null
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) $null
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {{ exit 2 }}
$result = Await ($engine.RecognizeAsync($bitmap)) $null
if ($result) {{ Write-Output $result.Text }}
"""
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            creationflags=flags,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def build_enriched_prompt(user_text: str, ocr_text: str) -> str:
    """把 OCR 结果并入用户问题，供纯文本 AI / 本地检索使用。"""
    user_text = (user_text or "").strip()
    ocr_text = (ocr_text or "").strip()
    if not ocr_text:
        return user_text
    placeholder = (
        not user_text
        or user_text.startswith("[图片消息")
        or user_text.startswith("[附带")
    )
    if placeholder:
        return f"用户发送了图片，OCR 识别内容如下：\n{ocr_text}\n\n请根据图片内容回答。"
    return (
        f"{user_text}\n\n"
        f"[图片 OCR 识别内容]\n{ocr_text}\n\n"
        "请结合以上文字与图片内容回答。"
    )
