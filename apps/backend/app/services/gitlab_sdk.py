from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import quote

import requests

from app.core.config import Settings
from app.schemas import SdkVersionInfo, Source
from app.services.text_utils import normalize_space


class GitLabSdkResolver:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.gitlab_base_url and self.settings.gitlab_project)

    def resolve(self, version: str) -> SdkVersionInfo:
        version = (version or "").strip()
        if not version:
            return SdkVersionInfo(enabled=False, configured=self.configured)
        if not self.configured:
            return SdkVersionInfo(
                enabled=False,
                configured=False,
                version=version,
                error="GitLab 未配置，已跳过 SDK 版本关联。",
            )
        return self._resolve_cached(version)

    def to_source(self, info: SdkVersionInfo) -> Source | None:
        if not info.enabled:
            return None
        parts = []
        if info.ref:
            parts.append(f"{info.ref_type}: {info.ref}")
        if info.commit_sha:
            parts.append(f"commit: {info.commit_sha[:12]}")
        if info.commit_title:
            parts.append(info.commit_title)
        if info.release_notes:
            parts.append(f"Release notes: {info.release_notes}")
        snippet = " | ".join(parts)[:600]
        return Source(
            path=info.web_url or self.settings.gitlab_project,
            title=f"GitLab SDK {info.version}",
            snippet=snippet,
            score=10.0,
            retrieval="gitlab_sdk",
            matched_issue="SDK 版本对应的 GitLab tag/branch/release notes",
        )

    @lru_cache(maxsize=128)
    def _resolve_cached(self, version: str) -> SdkVersionInfo:
        candidates = self._ref_candidates(version)
        last_error = ""
        for ref in candidates:
            tag_info, tag_error = self._get_ref("tags", ref)
            if tag_info:
                return self._build_info(version, ref, "tag", tag_info)
            last_error = tag_error or last_error

        for ref in candidates:
            branch_info, branch_error = self._get_ref("branches", ref)
            if branch_info:
                return self._build_info(version, ref, "branch", branch_info)
            last_error = branch_error or last_error

        searched = self._search_tags(version)
        if searched:
            ref, data = searched
            return self._build_info(version, ref, "tag", data)

        return SdkVersionInfo(
            enabled=False,
            configured=True,
            version=version,
            error=last_error or f"GitLab 未找到 SDK 版本对应 tag/branch：{version}",
        )

    def _build_info(self, version: str, ref: str, ref_type: str, data: dict) -> SdkVersionInfo:
        commit = data.get("commit") or {}
        release = data.get("release") or {}
        release_notes = self._release_notes(ref, version)
        if not release_notes and release:
            release_notes = normalize_space(str(release.get("description") or ""))[:800]
        return SdkVersionInfo(
            enabled=True,
            configured=True,
            version=version,
            ref=ref,
            ref_type=ref_type,
            commit_sha=str(commit.get("id") or commit.get("short_id") or ""),
            commit_title=str(commit.get("title") or commit.get("message") or ""),
            web_url=str(data.get("web_url") or commit.get("web_url") or ""),
            release_notes=release_notes,
            matched_files=self._matched_release_files(ref, version),
        )

    def _get_ref(self, kind: str, ref: str) -> tuple[dict | None, str]:
        try:
            data = self._request_json(f"/repository/{kind}/{quote(ref, safe='')}")
            return data if isinstance(data, dict) else None, ""
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None, ""
            return None, str(exc)
        except Exception as exc:
            return None, str(exc)

    def _search_tags(self, version: str) -> tuple[str, dict] | None:
        try:
            tags = self._request_json("/repository/tags", params={"search": version})
        except Exception:
            return None
        if not isinstance(tags, list):
            return None
        plain = version[1:] if version.lower().startswith("v") else version
        for tag in tags:
            name = str(tag.get("name") or "")
            if name == version or name == plain or name == f"v{plain}" or plain in name:
                return name, tag
        return None

    def _release_notes(self, ref: str, version: str) -> str:
        for file_path in self._release_paths():
            text = self._read_raw_file(file_path, ref)
            if not text:
                continue
            snippet = self._version_snippet(text, version)
            if snippet:
                return snippet
        return ""

    def _matched_release_files(self, ref: str, version: str) -> list[str]:
        matched: list[str] = []
        for file_path in self._release_paths():
            text = self._read_raw_file(file_path, ref)
            if text and self._version_snippet(text, version):
                matched.append(file_path)
        return matched

    def _read_raw_file(self, file_path: str, ref: str) -> str:
        try:
            encoded = quote(file_path.strip(), safe="")
            url = f"/repository/files/{encoded}/raw"
            resp = self._request(url, params={"ref": ref})
            return resp.text
        except Exception:
            return ""

    def _version_snippet(self, text: str, version: str) -> str:
        lines = text.splitlines()
        plain = version[1:] if version.lower().startswith("v") else version
        patterns = [version, plain, f"v{plain}"]
        for idx, line in enumerate(lines):
            if any(p and p in line for p in patterns):
                start = max(0, idx - 2)
                end = min(len(lines), idx + 8)
                return normalize_space(" ".join(lines[start:end]))[:800]
        return ""

    def _request_json(self, path: str, params: dict | None = None):
        resp = self._request(path, params=params)
        return resp.json()

    def _request(self, path: str, params: dict | None = None) -> requests.Response:
        project = quote(self.settings.gitlab_project, safe="")
        base = self.settings.gitlab_base_url.rstrip("/")
        url = f"{base}/api/v4/projects/{project}{path}"
        headers = {}
        if self.settings.gitlab_token:
            headers["PRIVATE-TOKEN"] = self.settings.gitlab_token
        resp = requests.get(url, headers=headers, params=params, timeout=self.settings.gitlab_timeout_sec)
        resp.raise_for_status()
        return resp

    def _ref_candidates(self, version: str) -> list[str]:
        plain = version[1:] if version.lower().startswith("v") else version
        values: list[str] = []
        for pattern in self.settings.gitlab_ref_patterns.split(","):
            pattern = pattern.strip()
            if not pattern:
                continue
            values.append(pattern.format(version=version, plain=plain))
        values.extend([version, plain, f"v{plain}"])
        return list(dict.fromkeys(v for v in values if v))

    def _release_paths(self) -> list[str]:
        return [item.strip() for item in self.settings.gitlab_release_note_paths.split(",") if item.strip()]


def extract_sdk_version(text: str) -> str:
    match = re.search(r"(?:SDK|sdk)\s*[:=： ]?\s*([vV]?\d+\.\d+(?:\.\d+)?)", text or "")
    if match:
        return match.group(1)
    match = re.search(r"\b[vV]?\d+\.\d+(?:\.\d+)?\b", text or "")
    return match.group(0) if match else ""
