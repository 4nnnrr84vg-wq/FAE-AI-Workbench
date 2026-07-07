"""企业微信回调配置自检（保存后台 URL 前请先运行）。"""
from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

from text_encoding import FILE_ENCODING, load_yaml_config, read_text, write_text

from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.exceptions import InvalidSignatureException


def _load_cfg() -> dict:
    return load_yaml_config("config.yaml")


def _check_crypto(wecom: dict) -> WeChatCrypto | None:
    token = str(wecom.get("token", "")).strip()
    aes = str(wecom.get("encoding_aes_key", "")).strip()
    corpid = str(wecom.get("corpid", "")).strip()
    if not token:
        print("[FAIL] wecom.token 为空，请填与后台「接收消息」完全相同的 Token")
        return None
    if not aes or len(aes) != 43:
        print(f"[FAIL] encoding_aes_key 须为 43 位，当前长度={len(aes)}")
        return None
    if not corpid:
        print("[FAIL] wecom.corpid 为空")
        return None
    try:
        crypto = WeChatCrypto(token, aes, corpid)
    except Exception as e:
        print(f"[FAIL] 密钥初始化失败: {e}")
        return None
    print("[OK] Token / EncodingAESKey / CorpId 可初始化")
    return crypto


def _roundtrip(crypto: WeChatCrypto, corpid: str):
    from wechatpy.enterprise.crypto import PrpCrypto
    from wechatpy.utils import to_text
    import time

    nonce = "nonce_test"
    ts = to_text(int(time.time()))
    plain_echo = "wecom_callback_test"
    pc = PrpCrypto(crypto.key)
    encrypted = to_text(pc.encrypt(plain_echo, corpid))
    from wechatpy.crypto import _get_signature

    sig = _get_signature(crypto.token, ts, nonce, encrypted)
    try:
        out = crypto.check_signature(sig, ts, nonce, encrypted)
        if out != plain_echo:
            print(f"[FAIL] 本地加解密不一致: {out!r}")
            return
    except InvalidSignatureException:
        print("[FAIL] 本地签名校验失败，请检查 token / encoding_aes_key")
        return
    except Exception as e:
        print(f"[FAIL] 本地校验异常: {e}")
        return
    print("[OK] 本地加解密与签名校验通过")


def _probe_url(url: str, label: str) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            code = resp.getcode()
            body = resp.read(200).decode(FILE_ENCODING, errors="replace")
            print(f"[{'OK' if code == 200 else 'WARN'}] {label}: HTTP {code}, body={body[:80]!r}")
            return code == 200
    except urllib.error.HTTPError as e:
        print(f"[WARN] {label}: HTTP {e.code}（服务可达，但可能尚未配置 token）")
        return True
    except Exception as e:
        print(f"[FAIL] {label}: 无法连接 — {e}")
        return False


def main() -> int:
    cfg = _load_cfg()
    wecom = cfg.get("wecom", {})
    public = str(wecom.get("callback_public_url", "")).strip()
    port = int(wecom.get("callback_port", 8787))
    path = str(wecom.get("callback_path", "/wecom/callback"))

    print("=== 企业微信回调自检 ===\n")

    crypto = _check_crypto(wecom)
    if crypto:
        _roundtrip(crypto, str(wecom.get("corpid", "")))

    print()
    local_health = f"http://127.0.0.1:{port}/wecom/health"
    _probe_url(local_health, f"本机服务 {local_health}")

    if public:
        print()
        _probe_url(public, f"公网回调 {public}")
        print(
            "\n提示: 公网 FAIL 表示企业微信也连不上。"
            "请在 IP 为 140.206.190.234 的机器上运行 python main.py，"
            "并放行安全组/防火墙 TCP 8787。"
        )
    else:
        print("\n[WARN] 未配置 callback_public_url")

    print(
        "\n后台保存顺序:\n"
        "  1) 在后台生成 Token、EncodingAESKey\n"
        "  2) 原样写入 config.yaml\n"
        "  3) python main.py 启动服务\n"
        "  4) 再点后台「保存」校验 URL\n"
    )
    return 0 if crypto else 1


if __name__ == "__main__":
    sys.exit(main())
