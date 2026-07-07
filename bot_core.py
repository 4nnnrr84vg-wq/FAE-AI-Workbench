"""消息处理核心（与微信客户端/企业微信 API 解耦）。"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from typing import Protocol

from model_client import ModelClient
from keyword_learning import KeywordLearner
from router import Router
from scheduler import SimpleScheduler
from smart_router import SmartRouter
from style_profile import StyleLearner
from conversation_context import ConversationContext
from question_freq import record_question
from correction_learner import CorrectionLearner
from reference_learner import learn_from_reference, status_text as ref_status
from text_encoding import encode_str, open_text


class MessageSender(Protocol):
    def send_text(self, chat: str, text: str) -> bool: ...
    def send_file(self, chat: str, path: str) -> bool: ...


class MessageBot:
    def __init__(self, cfg: dict, sender: MessageSender | None = None):
        self.cfg = cfg
        bot_cfg = cfg.get("bot", {})
        self.reply_mode = str(bot_cfg.get("reply_mode", "draft_only"))
        draft_name = str(bot_cfg.get("draft_output_txt", "reply_drafts.txt"))
        self.draft_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), draft_name)
        self.router = Router(cfg)
        self.keyword_learner = KeywordLearner(cfg)
        self.model = ModelClient(cfg)
        self.smart = SmartRouter(cfg, self.model)
        self.context = ConversationContext(max_turns=5)
        self.style = StyleLearner(cfg)
        self.correction = CorrectionLearner(cfg)
        self.sender = sender
        self._recent_fps: dict[str, float] = {}
        self._dedup_sec = float(bot_cfg.get("message_dedup_sec", 3.0))
        self._last_learn_pair: tuple[str, str] | None = None
        self.last_file_path: str | None = None
        self.scheduler = SimpleScheduler(cfg, self._run_schedule_job)
        self.scheduler.start()

    def handle_message(self, msg: dict) -> str | None:
        fp = msg.get("_fp")
        if not fp:
            raw = f"{msg.get('chat')}|{msg.get('sender')}|{msg.get('content')}|{msg.get('type')}"
            for img in msg.get("images") or []:
                raw += hashlib.md5(img[:8192]).hexdigest()
            from text_encoding import FILE_ENCODING, encode_str, open_text, read_text, write_text

            fp = hashlib.md5(encode_str(raw)).hexdigest()

        # 剪贴板/手动模式由用户主动触发，允许重复问同一问题
        allow_repeat = bool(msg.get("allow_repeat")) or msg.get("sender") in ("clipboard", "manual")
        if not allow_repeat and self._dedup_sec > 0:
            import time as _time

            now = _time.time()
            last = self._recent_fps.get(fp)
            if last is not None and (now - last) < self._dedup_sec:
                print(f"[INFO] 短时重复消息已跳过（{self._dedup_sec}s 内）", flush=True)
                return None
            self._recent_fps[fp] = now
            if len(self._recent_fps) > 2000:
                cutoff = now - self._dedup_sec * 2
                self._recent_fps = {k: v for k, v in self._recent_fps.items() if v >= cutoff}

        # 自动收集用户问题（用于后续风格学习）
        content = str(msg.get("content", "")).strip()
        if content and len(content) > 5:
            self._save_question_for_learning(content)

        chat = msg.get("chat", "")
        text = msg.get("content", "")
        raw_text = str(msg.get("raw_text", text) or text)
        images: list[bytes] = list(msg.get("images") or [])
        # 清洗 chat，防止乱码
        try:
            chat = chat.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
            if any(ord(c) > 127 for c in chat):
                chat = "All Chats"
        except Exception:
            chat = "All Chats"
        print(f"[RECV] {chat}: {text}")
        if images:
            print(f"[INFO] 附带图片 {len(images)} 张", flush=True)
        record_question(text)  # 記錄問題頻率（高頻問題後續可自動優化）
        self.last_file_path = None

        if images:
            return self._generate_answer(
                chat, text, raw_text=raw_text, images=images, force_ai=bool(msg.get("force_ai"))
            )

        force_ai = bool(msg.get("force_ai"))
        action = self.router.route(text)
        if action["type"] == "none":
            return None
        if action["type"] == "style":
            return self._handle_style_command(chat, action.get("arg", ""), text)
        if action["type"] == "keyword_cmd":
            return self._handle_keyword_command(chat, action.get("arg", ""), text)
        if action["type"] == "correction_cmd":
            return self._handle_correction_command(chat, action.get("arg", ""), text)
        if action["type"] == "reference_cmd":
            return self._handle_reference_command(chat, action.get("arg", ""), text)
        if action["type"] == "file":
            self.last_file_path = action["path"]
            notice = action.get("notice") or f"已找到文件：{os.path.basename(action['path'])}"
            print(f"[INFO] 文件命中: {action['key']} -> {action['path']}", flush=True)
            self._output_or_send_file(chat, action["path"], text, f"rule_file:{action['key']}")
            return notice
        if force_ai:
            print("[INFO] 强制 AI 重新回答，跳过关键词库/本地检索", flush=True)
            return self._generate_answer(chat, text, raw_text=raw_text, force_ai=True)
        if action["type"] == "keyword_candidate":
            kid = action.get("entry_id", "")
            if kid.startswith("ref_cache_"):
                print(f"[INFO] 精确问题缓存命中（秒回）: {text[:40]}...", flush=True)
            ok, why = self.smart.should_use_keyword(
                text,
                kid,
                action["content"],
                int(action.get("score", 0)),
                int(action.get("priority", 0)),
            )
            if ok:
                print(f"[INFO] 关键词库采用: {kid} ({why})", flush=True)
                self.keyword_learner.record_hit(kid)
                self.context.add_turn(text, action["content"])
                return self._output_or_send_text(
                    chat, action["content"], text, action.get("reason", "keyword_lib")
                )
            print(f"[INFO] 关键词库候选被拒绝 {kid} -> 转 AI ({why})", flush=True)
            return self._generate_answer(chat, text)
        if action["type"] == "text":
            reason = action.get("reason", "rule_text")
            return self._output_or_send_text(chat, action["content"], text, reason)

        return self._generate_answer(chat, text, raw_text=raw_text, force_ai=force_ai)

    def _generate_answer(
        self,
        chat: str,
        text: str,
        *,
        raw_text: str = "",
        images: list[bytes] | None = None,
        force_ai: bool = False,
    ) -> str:
        images = images or []
        raw_text = raw_text or text
        bot_cfg = self.cfg.get("bot", {})

        if force_ai:
            print("[INFO] 强制 AI 模式：跳过本地检索与关键词缓存", flush=True)
        else:
            prefer_ai, route_note = self.smart.prefer_ai_over_keyword(text)
            if prefer_ai:
                print(f"[INFO] 智能路由：优先完整 AI ({route_note})", flush=True)

        if images:
            from clipboard_payload import save_images_to_cache

            ws = str(getattr(self.model, "workspace", "."))
            cb_cfg = self.cfg.get("clipboard") or {}
            cache_subdir = str(cb_cfg.get("image_cache_dir", ".wechat_bot_cache/images"))
            max_images = int(cb_cfg.get("max_images", 4))
            image_paths = save_images_to_cache(
                images, ws, subdir=cache_subdir, max_images=max_images
            )
            ctx = self.context.get_context_text()
            reply = self.model.generate_reply_with_images(
                raw_text or text,
                images,
                context_text=ctx,
                image_paths=image_paths,
            )
            if not reply:
                err = getattr(self.model, "last_error", "") or "未知错误"
                reply = (
                    f"{self.router.default_reply}\n\n"
                    f"[AI 识图失败] {err}\n"
                    "请检查 model_api 配置，或启用支持视觉的模型"
                )
            else:
                self._print_token_usage()
            self.context.add_turn(text, reply)
            return self._output_or_send_text(chat, reply, text, "vision_force" if force_ai else "vision")

        if not force_ai and not prefer_ai and bot_cfg.get("fast_local_search", True):
            from local_search import build_local_reply

            ws = str(getattr(self.model, "workspace", "."))
            local = build_local_reply(text, ws)
            if local:
                ok, why = self.smart.should_use_local_search(text, local)
                if ok:
                    print(f"[INFO] 本地检索采用 ({why})", flush=True)

                    # 如果是 reference context，交给 AI 整合成自然回答
                    # 优先使用 model_api 整合资料。
                    if local.startswith("[[REFERENCE_CONTEXT]]"):
                        ref_ctx = local.replace("[[REFERENCE_CONTEXT]]", "").strip()
                        combined_ctx = (self.context.get_context_text() or "") + "\n\n[Reference资料]\n" + ref_ctx
                        reply = self.model.generate_reply(text, context_text=combined_ctx, prefer_model_api=True)
                        if reply:
                            self._print_token_usage()
                            self.context.add_turn(text, reply)
                            # 双快取：精确问题缓存（exact）+ 模糊关键词缓存（contains）
                            cached_exact = self.keyword_learner.learn_exact_reference_cache(text, reply)
                            cached_fuzzy = self.keyword_learner.learn_reference_fuzzy_cache(text, reply)
                            if cached_exact or cached_fuzzy:
                                self.router.reload_keywords()
                            if self._remember_for_manual_learn(text, reply, "nlp"):
                                self.router.reload_keywords()
                            return self._output_or_send_text(chat, reply, text, "nlp_ref")
                        print("[WARN] model_api 整合失败，fallback 成原始 reference 内容", flush=True)

                    # 普通 local_search 结果直接回传
                    self.context.add_turn(text, local)
                    if self._remember_for_manual_learn(text, local, "local_search"):
                        self.router.reload_keywords()
                    return self._output_or_send_text(chat, local, text, "local_search")
                print(f"[INFO] 本地检索不采用 -> 转 AI ({why})", flush=True)

        ctx = self.context.get_context_text()
        reply = self.model.generate_reply(text, context_text=ctx)
        if not reply:
            err = getattr(self.model, "last_error", "") or "未知错误"
            reply = (
                f"{self.router.default_reply}\n\n"
                f"[AI 失败] {err}\n"
                "请检查 model_api 配置"
            )
        else:
            self._print_token_usage()
        self.context.add_turn(text, reply)
        if self._remember_for_manual_learn(text, reply, "nlp"):
            self.router.reload_keywords()
        return self._output_or_send_text(chat, reply, text, "nlp")

    def _handle_style_command(self, chat: str, arg: str, source_text: str) -> str:
        arg = (arg or "").strip().lower()
        if arg in ("", "status", "状态"):
            msg = self.style.status_text()
        elif arg in ("rebuild", "重建", "learn", "学习"):
            count, msg = self.style.rebuild_from_imports()
            if count == 0:
                msg += f"\n也可运行 import_style.bat 或: import_style.py 你的聊天.txt"
        else:
            msg = (
                "用法：\n"
                "  /style            查看风格学习状态\n"
                "  /style 重建       从 style_data/imports/ 重新学习\n"
                "  /style 导出问题   把收集的问题导出成结构化 Q&A（wechat_qa.md）"
            )
        self._output_or_send_text(chat, msg, source_text, "style_cmd")
        return msg

    def _handle_keyword_command(self, chat: str, arg: str, source_text: str) -> str:
        arg = (arg or "").strip().lower()
        if arg in ("", "status", "状态"):
            msg = self.keyword_learner.status_text()
        elif arg in ("learn", "学习", "rebuild", "重建"):
            parts = [self.keyword_learner.status_text()]
            if self.keyword_learner.learn_from_drafts:
                n, m = self.keyword_learner.learn_from_drafts(self.draft_file)
                parts.append(m)
            if self.keyword_learner.learn_from_imports:
                n2, m2 = self.keyword_learner.learn_from_imports(self.cfg)
                parts.append(m2)
            self.router.reload_keywords()
            parts.append(f"当前关键词库共 {self.router.keyword_lib.count()} 条（含内置+已学习）")
            msg = "\n".join(parts)
        elif arg in ("list", "列表", "查看"):
            entries = self.keyword_learner.list_entries(15)
            if not entries:
                msg = "目前沒有已學習的關鍵字條目"
            else:
                lines = ["最近學習的關鍵字條目："]
                for e in entries:
                    lines.append(f"- {e.get('id')} | {e.get('question','')[:40]}")
                msg = "\n".join(lines)
        elif arg.startswith(("del ", "刪除 ", "delete ")):
            eid = arg.split(maxsplit=1)[-1].strip()
            if self.keyword_learner.delete_entry(eid):
                self.router.reload_keywords()
                msg = f"已刪除 {eid}"
            else:
                msg = f"找不到 {eid}"
        elif arg in ("bad", "不對", "錯誤", "差"):
            if self._last_learn_pair:
                q, r = self._last_learn_pair
                # 簡單降權：如果最後一次是關鍵字命中，嘗試降低其優先級
                # 此處僅提示使用者手動管理；完整實作可擴充 learned.yaml 欄位
                msg = "已記錄回饋。建議使用 /keyword list 與 /keyword del 手動清理。"
            else:
                msg = "目前沒有可回饋的上一條回答"
        elif arg in ("export", "導出"):
            msg = "learned.yaml 已更新，可直接查看 keyword_data/learned.yaml"
        elif arg in ("导出问题", "export-qa", "导出qa"):
            msg = self._export_questions_to_qa()
        elif arg in ("导入客户问题", "import-customer", "客户问题", "customer"):
            from customer_qa_import import import_customer_xlsx

            cq = self.cfg.get("customer_qa", {}) or {}
            xlsx = str(cq.get("xlsx_file", "keyword_data/imports/客户问题汇总.xlsx"))
            if not os.path.isabs(xlsx):
                xlsx = os.path.join(os.path.dirname(os.path.abspath(__file__)), xlsx)
            if not os.path.isfile(xlsx):
                xlsx = r"c:\Users\Administrator\Desktop\客户问题汇总(已自动还原).xlsx"
            n, skipped, detail = import_customer_xlsx(self.cfg, xlsx)
            self.router.reload_keywords()
            msg = f"{detail}\n当前关键词库共 {self.router.keyword_lib.count()} 条"
        elif arg in ("客户问题状态", "customer-status"):
            from customer_qa_import import customer_qa_status

            msg = customer_qa_status(self.cfg)
        elif arg in ("记住", "save", "last"):
            if not self._last_learn_pair:
                msg = "尚无上一条可记住的问答（需先有一次 AI 或本地检索回复）"
            else:
                q, r = self._last_learn_pair
                if self.keyword_learner.learn_pair(q, r, source="manual"):
                    self.router.reload_keywords()
                    msg = f"已记住上一条问答（{q[:30]}…）"
                else:
                    msg = "上一条不符合学习条件（过短、重复或失败回复）"
        else:
            msg = (
                "关键词库学习用法：\n"
                "  /keyword            查看状态\n"
                "  /keyword 学习       從草稿+聊天記錄導入\n"
                "  /keyword list       列出已學習條目\n"
                "  /keyword del <id>   刪除指定條目\n"
                "  /keyword 记住       強制記住上一條 AI 問答\n"
                "  /keyword 导入客户问题  从 Excel 导入历史客户 Q&A\n"
                "自動學習：AI/本地檢索成功後默認寫入 keyword_data/learned.yaml"
            )
        self._output_or_send_text(chat, msg, source_text, "keyword_cmd")
        return msg

    def _handle_reference_command(self, chat: str, arg: str, source_text: str) -> str:
        arg = (arg or "").strip().lower()
        if arg in ("learn", "学习", "scan", "扫描"):
            n, msg = learn_from_reference(force="force" in arg or "全部" in arg)
            self.router.reload_keywords()
            msg = f"{msg}\n关键词库已重新加载。"
        elif arg in ("status", "状态"):
            msg = ref_status()
        else:
            msg = (
                "用法：\n"
                "  /reference 学习     扫描 reference/documents/ 并生成关键词\n"
                "  /reference 状态     查看已学习的文件记录"
            )
        self._output_or_send_text(chat, msg, source_text, "reference_cmd")
        return msg

    def _handle_correction_command(self, chat: str, arg: str, source_text: str) -> str:
        """进入交互式修正模式（控制台）"""
        from console_correction import run_correction_interactive

        run_correction_interactive(self.correction)
        status = self.correction.status_text()
        self._output_or_send_text(chat, f"修正模式结束。\n{status}", source_text, "correction")
        return "修正模式结束"

    def _print_token_usage(self) -> None:
        # 优先显示 model_api 真实用量
        usage = getattr(self.model, "last_usage", None)
        if usage and usage.get("total_tokens"):
            p = usage.get("prompt_tokens", 0)
            c = usage.get("completion_tokens", 0)
            t = usage.get("total_tokens", 0)
            ratio = (p / t * 100) if t > 0 else 0
            print(f"[INFO] Token 使用 (model_api): prompt={p}, completion={c}, total={t} (prompt {ratio:.1f}%)", flush=True)
            return

    def _save_question_for_learning(self, question: str) -> None:
        """把用户问题自动保存到 style_data/imports/wechat_questions.txt"""
        try:
            from pathlib import Path
            import datetime as dt

            save_dir = Path(__file__).resolve().parent / "style_data" / "imports"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_file = save_dir / "wechat_questions.txt"

            now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
            line = f"[{now}] {question}\n"
            with open(save_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass  # 静默失败，不影响主流程

    def _export_questions_to_qa(self) -> str:
        """把 wechat_questions.txt 转成结构化 Q&A 文件"""
        try:
            from pathlib import Path
            import datetime as dt

            src = Path(__file__).resolve().parent / "style_data" / "imports" / "wechat_questions.txt"
            dst = Path(__file__).resolve().parent / "style_data" / "imports" / "wechat_qa.md"

            if not src.exists():
                return "目前还没有收集到问题。"

            lines = src.read_text(encoding="utf-8").strip().splitlines()
            qa_lines = [
                "# WeChat Bot 收集的问题（自动生成）",
                "",
                f"> 生成时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "",
                "格式：问题 + 期望回答（可手动补充）",
                "",
            ]

            for line in lines:
                if line.strip():
                    qa_lines.append(f"**问题**：{line.strip()}")
                    qa_lines.append("")
                    qa_lines.append("**期望回答**：（待补充）")
                    qa_lines.append("")
                    qa_lines.append("**标签**：技术 / bot功能")
                    qa_lines.append("")
                    qa_lines.append("---")
                    qa_lines.append("")

            dst.write_text("\n".join(qa_lines), encoding="utf-8")
            return f"已导出 {len(lines)} 条问题到 wechat_qa.md，可用于风格学习。"
        except Exception as e:
            return f"导出失败：{e}"

    def _remember_for_manual_learn(self, question: str, reply: str, reason: str) -> bool:
        if reason in ("nlp", "local_search"):
            self._last_learn_pair = (question, reply)
        return self.keyword_learner.try_auto_learn(question, reply, reason)

    def _run_schedule_job(self, job: dict):
        chat = job.get("chat", "")
        file_key = job.get("file_key", "")
        msg = job.get("message", "")
        path = self.cfg.get("files", {}).get("mapping", {}).get(file_key)
        if not chat or not path:
            return
        if not os.path.exists(path):
            print(f"[WARN] schedule file not found: {path}")
            return
        if msg:
            self._output_or_send_text(chat, msg, "", "schedule")
        self._output_or_send_file(chat, path, "", "schedule")
        print(f"[SCHEDULE] sent {file_key} -> {chat}")

    def _output_or_send_text(self, chat: str, reply_text: str, source_text: str, reason: str) -> str:
        if self.reply_mode == "send" and self.sender:
            self.sender.send_text(chat, reply_text)
            return reply_text
        self._append_draft(chat, source_text, reason, f"TEXT: {reply_text}")
        return reply_text

    def _output_or_send_file(self, chat: str, file_path: str, source_text: str, reason: str):
        if self.reply_mode == "send" and self.sender:
            self.sender.send_file(chat, file_path)
            return
        self._append_draft(chat, source_text, reason, f"FILE: {file_path}")

    def _append_draft(self, chat: str, source_text: str, reason: str, output: str):
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"[{ts}]",
            f"chat={chat}",
            f"reason={reason}",
            f"incoming={source_text}",
            f"draft={output}",
            "-" * 60,
            "",
        ]
        with open_text(self.draft_file, "a") as f:
            f.write("\n".join(lines))
        print(f"[DRAFT] saved -> {self.draft_file}")
