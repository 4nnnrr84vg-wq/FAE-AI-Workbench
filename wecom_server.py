"""企业微信回调服务：接收消息 -> 路由/NLP -> 草稿或发送。"""

from __future__ import annotations



import hashlib

import logging

import xml.etree.ElementTree as ET



from flask import Flask, Response, request



from bot_core import MessageBot

from wecom_client import WeComClient



try:

    from wechatpy.enterprise.crypto import WeChatCrypto

    from wechatpy.exceptions import InvalidSignatureException

except ImportError as e:

    raise ImportError("请安装 wechatpy: pip install wechatpy cryptography") from e



logger = logging.getLogger("wecom_server")





def _parse_incoming_xml(xml_text: str) -> dict:

    root = ET.fromstring(xml_text)

    msg = {child.tag: (child.text or "") for child in root}

    msg_type = msg.get("MsgType", "")

    content = msg.get("Content", "")

    if msg_type == "text":

        normalized_type = "text"

    elif msg_type == "event":

        normalized_type = "event"

    else:

        normalized_type = msg_type or "unknown"

    return {

        "chat": msg.get("FromUserName", ""),

        "sender": msg.get("FromUserName", ""),

        "content": content,

        "type": normalized_type,

        "raw": msg,

    }





def validate_wecom_callback_config(wecom_cfg: dict) -> list[str]:

    """返回错误列表；空列表表示通过。"""

    errors: list[str] = []

    token = str(wecom_cfg.get("token", "")).strip()

    aes = str(wecom_cfg.get("encoding_aes_key", "")).strip()

    corpid = str(wecom_cfg.get("corpid", "")).strip()



    if not token:

        errors.append("wecom.token 未配置（须与后台「接收消息」里 Token 完全一致）")

    if not aes:

        errors.append("wecom.encoding_aes_key 未配置（后台生成的 43 位 Key）")

    elif len(aes) != 43:

        errors.append(f"encoding_aes_key 长度应为 43，当前为 {len(aes)}")

    if not corpid:

        errors.append("wecom.corpid 未配置")



    if not errors:

        try:

            WeChatCrypto(token, aes, corpid)

        except Exception as e:

            errors.append(f"EncodingAESKey 无效: {e}")

    return errors





def create_wecom_app(cfg: dict) -> Flask:

    wecom_cfg = cfg.get("wecom", {})

    token = str(wecom_cfg.get("token", "")).strip()

    aes_key = str(wecom_cfg.get("encoding_aes_key", "")).strip()

    corpid = str(wecom_cfg.get("corpid", "")).strip()

    callback_path = str(wecom_cfg.get("callback_path", "/wecom/callback"))

    if not callback_path.startswith("/"):

        callback_path = "/" + callback_path



    crypto = WeChatCrypto(token, aes_key, corpid)

    wecom_api = WeComClient(wecom_cfg)

    bot = MessageBot(cfg, sender=wecom_api)



    allowed_users = set(cfg.get("bot", {}).get("allowed_users", []) or [])



    app = Flask(__name__)



    @app.get("/wecom/health")

    def health():

        return Response("ok", mimetype="text/plain")



    @app.get(callback_path)

    def verify():

        signature = request.args.get("msg_signature", "")

        timestamp = request.args.get("timestamp", "")

        nonce = request.args.get("nonce", "")

        echostr = request.args.get("echostr", "")

        try:

            plain = crypto.check_signature(signature, timestamp, nonce, echostr)

            logger.info("URL 校验成功")

            return Response(plain, mimetype="text/plain")

        except InvalidSignatureException:

            logger.error(

                "URL 校验失败: 签名不匹配，请确认 config.yaml 中 token / "

                "encoding_aes_key 与后台完全一致"

            )

            return Response("invalid signature", status=403, mimetype="text/plain")

        except Exception:

            logger.exception("URL 校验异常")

            return Response("error", status=500, mimetype="text/plain")



    @app.post(callback_path)

    def callback():

        signature = request.args.get("msg_signature", "")

        timestamp = request.args.get("timestamp", "")

        nonce = request.args.get("nonce", "")

        encrypted = request.data.decode("utf-8")

        try:

            plain_xml = crypto.decrypt_message(

                encrypted, signature, timestamp, nonce

            )

        except Exception:

            logger.exception("消息解密失败")

            return Response("success", mimetype="text/plain")



        msg = _parse_incoming_xml(plain_xml)



        userid = msg.get("chat", "")

        if allowed_users and userid not in allowed_users:

            return Response("success", mimetype="text/plain")



        if msg.get("type") != "text":

            return Response("success", mimetype="text/plain")



        fp_src = f"{userid}|{msg.get('content','')}|{msg.get('type')}"

        msg["_fp"] = hashlib.md5(fp_src.encode("utf-8")).hexdigest()

        bot.handle_message(msg)

        return Response("success", mimetype="text/plain")



    return app





def _callback_public_url(wecom_cfg: dict) -> str:

    explicit = str(wecom_cfg.get("callback_public_url", "")).strip()

    if explicit:

        return explicit.rstrip("/")

    port = int(wecom_cfg.get("callback_port", 8787))

    path = str(wecom_cfg.get("callback_path", "/wecom/callback"))

    if not path.startswith("/"):

        path = "/" + path

    return f"http://127.0.0.1:{port}{path}"





def run_wecom_server(cfg: dict):

    wecom_cfg = cfg.get("wecom", {})

    host = str(wecom_cfg.get("callback_host", "0.0.0.0"))

    port = int(wecom_cfg.get("callback_port", 8787))

    path = str(wecom_cfg.get("callback_path", "/wecom/callback"))

    public_url = _callback_public_url(wecom_cfg)



    errors = validate_wecom_callback_config(wecom_cfg)

    if errors:

        print("[ERROR] 企业微信回调配置不完整，无法通过后台 URL 校验：")

        for err in errors:

            print(f"  - {err}")

        print(

            "\n操作步骤:\n"

            "  1) 后台「接收消息」先记下 Token、EncodingAESKey\n"

            "  2) 写入 config.yaml 后保存文件\n"

            "  3) 在本机执行: python main.py\n"

            "  4) 再回后台点「保存」\n"

            "自检: python check_wecom_callback.py\n"

        )

        raise SystemExit(1)



    logging.basicConfig(

        level=logging.INFO,

        format="%(asctime)s %(levelname)s %(message)s",

    )



    app = create_wecom_app(cfg)

    print(f"[INFO] 企业微信回调服务监听: http://{host}:{port}{path}")

    print(f"[INFO] 管理后台「接收消息」URL 请填: {public_url}")

    print(f"[INFO] 连通性探测: http://127.0.0.1:{port}/wecom/health")

    print("[INFO] 云服务器请在安全组/防火墙放行 TCP 8787")

    app.run(host=host, port=port, debug=False, use_reloader=False)

