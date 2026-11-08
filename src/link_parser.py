"""
B站链接解析模块

支持的链接类型：
- 视频：bilibili.com/video/BVxxx, bilibili.com/video/avxxx, b23.tv/xxx
- 直播：live.bilibili.com/xxx
- 番剧：bilibili.com/bangumi/play/epxxx, /ssxxx, bilibili.com/bangumi/media/mdxxx
- 专栏：bilibili.com/read/cvxxx
- 音频：bilibili.com/audio/auxxx
- 用户空间：space.bilibili.com/xxx
- 动态：bilibili.com/opus/xxx
"""

import re
from dataclasses import dataclass, field


@dataclass
class BiliLink:
    """解析出的 B站链接"""
    link_type: str          # video / live / bangumi_ep / bangumi_ss / bangumi_md / article / audio / space / opus / short
    id: str                # 提取的ID（BV号、房间号、ep_id等）
    url: str               # 原始完整URL
    resolved_url: str | None = None  # 短链解析后的真实URL


# ── 链接正则模式 ──────────────────────────────────────────────
# 格式: (类型名, 编译后的正则)
# 匹配 group(1) 为提取到的ID

_BILI_PATTERNS: list[tuple[str, re.Pattern]] = [
    # ── 视频链接（完整URL） ──
    ("video", re.compile(r"https?://(?:www\.)?bilibili\.com/video/(?:BV([A-Za-z0-9]+)|av(\d+))", re.I)),
    ("video", re.compile(r"https?://(?:m\.)?bilibili\.com/video/(?:BV([A-Za-z0-9]+)|av(\d+))", re.I)),
    # b23.tv 短链接
    ("short", re.compile(r"https?://b23\.tv/([A-Za-z0-9]+)")),
    # bili2233.cn 短链（备用）
    ("short", re.compile(r"https?://bili2233\.cn/([A-Za-z0-9]+)")),

    # ── 直播链接 ──
    ("live", re.compile(r"https?://live\.bilibili\.com/(\d+)")),

    # ── 番剧链接 ──
    ("bangumi_ep", re.compile(r"https?://(?:www\.)?bilibili\.com/bangumi/play/ep(\d+)")),
    ("bangumi_ss", re.compile(r"https?://(?:www\.)?bilibili\.com/bangumi/play/ss(\d+)")),
    ("bangumi_md", re.compile(r"https?://(?:www\.)?bilibili\.com/bangumi/media/md(\d+)")),

    # ── 专栏链接 ──
    ("article", re.compile(r"https?://(?:www\.)?bilibili\.com/read/(?:cv|mobile\?id=)(\d+)")),

    # ── 音频链接 ──
    ("audio", re.compile(r"https?://(?:www\.)?bilibili\.com/audio/au(\d+)")),

    # ── 用户空间 ──
    ("space", re.compile(r"https?://space\.bilibili\.com/(\d+)")),

    # ── 动态链接 ──
    ("opus", re.compile(r"https?://(?:www\.)?bilibili\.com/opus/(\d+)")),

    # ── 纯 BV / AV 号（独立的，不在 URL 内） ──
    ("video", re.compile(r"(?<![A-Za-z0-9])(?:BV([A-Za-z0-9]{10})|av(\d+))(?![A-Za-z0-9])", re.I)),
]


def parse_bili_links(text: str) -> list[BiliLink]:
    """
    从文本中解析所有 B站链接

    Args:
        text: 消息文本

    Returns:
        BiliLink 列表，按在文本中出现的位置排序
    """
    results: list[BiliLink] = []

    for link_type, pattern in _BILI_PATTERNS:
        matches = pattern.finditer(text)
        for m in matches:
            # 获取匹配到的ID（group(1)是第一个捕获组）
            # 对于video类型，可能匹配BV或AV，选择非None的group
            if link_type == "video":
                extracted_id = m.group(1) or m.group(2)
            else:
                extracted_id = m.group(1)

            if extracted_id:
                results.append(BiliLink(
                    link_type=link_type,
                    id=extracted_id,
                    url=m.group(0),
                    resolved_url=None,
                ))

    # 避免重复（同一个URL可能匹配多个模式）
    seen_urls: set[str] = set()
    unique_results: list[BiliLink] = []
    for link in results:
        if link.url not in seen_urls:
            seen_urls.add(link.url)
            unique_results.append(link)

    return unique_results


# ── 类型名称映射 ──
_TYPE_DISPLAY_NAME: dict[str, str] = {
    "video": "视频",
    "live": "直播",
    "bangumi_ep": "番剧",
    "bangumi_ss": "番剧",
    "bangumi_md": "番剧集",
    "article": "专栏",
    "audio": "音频",
    "space": "用户空间",
    "opus": "动态",
    "short": "b23.tv短链接",
}


def get_type_display_name(link_type: str) -> str:
    """获取类型的可读名称"""
    return _TYPE_DISPLAY_NAME.get(link_type, link_type)