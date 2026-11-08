"""
B站 API 调用模块

负责调用各类型的 B站公开 API，获取内容详情。
所有函数均返回统一结构化的数据。
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

from .link_parser import BiliLink

logger = logging.getLogger("astrbot")

# ── 通用请求头 ──────────────────────────────────────────────

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _build_headers(user_agent: str = DEFAULT_UA) -> dict[str, str]:
    """构建B站 API 请求头"""
    return {
        "User-Agent": user_agent,
        "Referer": "https://www.bilibili.com/",
    }


# ── 统一结果数据结构 ──────────────────────────────────────

@dataclass
class BiliResult:
    """B站内容统一数据结构"""
    link_type: str           # 原始链接类型
    bili_type: str           # 可读类型名
    title: str               # 标题
    cover: str               # 封面图URL
    author_name: str         # UP主/作者/主播名
    author_face: str = ""    # 作者头像URL
    desc: str = ""           # 简介/描述
    duration: int = 0        # 时长（秒，视频专用）
    pubdate: int = 0         # 发布时间戳
    url: str = ""            # 链接
    extra: dict = field(default_factory=dict)  # 额外信息

    # 统计数据
    stat_view: int = 0       # 播放/观看
    stat_danmaku: int = 0    # 弹幕
    stat_like: int = 0       # 点赞
    stat_coin: int = 0       # 投币
    stat_favorite: int = 0   # 收藏
    stat_share: int = 0      # 分享
    stat_reply: int = 0      # 评论

    # 直播专用
    live_status: int = 0     # 0=未开播 1=直播中 2=轮播中

    # 实时在线人数（视频「x人正在看」）与 UP主粉丝数
    online_text: str = ""    # 已格式化的展示文本，空串表示不展示
    fans_text: str = ""      # UP主粉丝数展示文本，空串表示不展示

    def to_dict(self) -> dict:
        """转为模板渲染用的 dict，所有字段都格式化好了"""
        return {
            "link_type": self.link_type,
            "bili_type": self.bili_type,
            "title": self.title,
            "cover": self.cover,
            "author_name": self.author_name,
            "author_face": self.author_face,
            "desc": self.desc,
            "duration": self._format_duration(),
            "pubdate": self._format_date(),
            "url": self.url,
            "stat_view": _format_number(self.stat_view),
            "stat_danmaku": _format_number(self.stat_danmaku),
            "stat_like": _format_number(self.stat_like),
            "stat_coin": _format_number(self.stat_coin),
            "stat_favorite": _format_number(self.stat_favorite),
            "stat_share": _format_number(self.stat_share),
            "stat_reply": _format_number(self.stat_reply),
            "live_status": self.live_status,
            "live_status_text": _get_live_status_text(self.live_status),
            "online_text": self.online_text,
            "fans_text": self.fans_text,
            "extra": self.extra,
            "has_cover": bool(self.cover),
            "has_desc": bool(self.desc),
        }

    def fallback_text(self) -> str:
        """降级纯文本回复"""
        lines = [f"【{self.bili_type}】{self.title}"]
        if self.author_name:
            lines.append(f"UP主/作者：{self.author_name}")
        if self.url:
            lines.append(self.url)
        return "\n".join(lines)

    def _format_duration(self) -> str:
        """将秒数格式化为 mm:ss 或 hh:mm:ss"""
        if self.duration <= 0:
            return ""
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _format_date(self) -> str:
        """将Unix时间戳格式化为日期字符串"""
        if self.pubdate <= 0:
            return ""
        return datetime.fromtimestamp(self.pubdate).strftime("%Y-%m-%d %H:%M:%S")


# ── 短链接解析 ──────────────────────────────────────────────

async def resolve_b23_url(short_id: str, user_agent: str = DEFAULT_UA, cookie: str = "") -> str | None:
    """
    解析 b23.tv 短链接，返回真实 URL

    Args:
        short_id: b23.tv 路径中的短链ID
        user_agent: 请求UA
        cookie: 可选cookie

    Returns:
        解析后的真实URL，失败返回 None
    """
    url = f"https://b23.tv/{short_id}"
    headers = _build_headers(user_agent)
    if cookie:
        headers["Cookie"] = cookie

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=False, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                # 302 重定向
                if resp.status in (301, 302, 307, 308):
                    location = resp.headers.get("Location", "")
                    if location:
                        return location

                # 部分短链会返回HTML页面，需要从页面中提取链接
                html = await resp.text()
                # 匹配 <a href="..."> 模式
                match = re.search(r'<a\s+(?:[^>]*?\s+)?href="([^"]*)"', html, re.I)
                if match:
                    return match.group(1)

    except Exception as e:
        logger.warning(f"[BiliParser] 解析 b23.tv/{short_id} 失败: {e}")

    return None


def _resolve_b23_from_url(short_url: str) -> str | None:
    """同步方式从短链URL提取路径ID（用于import时）"""
    m = re.match(r"https?://b23\.tv/([A-Za-z0-9]+)", short_url)
    return m.group(1) if m else None


# ── 实时在线人数 ──────────────────────────────────────────

async def _fetch_video_online(bvid: str, cid: int, user_agent: str = DEFAULT_UA) -> str:
    """
    获取视频「x人正在看」的实时在线人数

    API: https://api.bilibili.com/x/player/online/total
    返回 B站 页面上原样展示的文本（大数会被截断成 "1000+"），失败返回空串。
    """
    if not bvid or not cid:
        return ""

    url = f"https://api.bilibili.com/x/player/online/total?bvid={bvid}&cid={cid}"
    headers = _build_headers(user_agent)
    headers["Referer"] = f"https://www.bilibili.com/video/{bvid}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
    except Exception as e:
        logger.debug(f"[BiliParser] 在线人数获取失败: {e}")
        return ""

    if data.get("code") != 0:
        return ""

    payload = data.get("data") or {}
    # 站方开关关闭时不展示
    if not (payload.get("show_switch") or {}).get("total", True):
        return ""

    return str(payload.get("total") or "")


async def _fetch_fans(mid: int, user_agent: str = DEFAULT_UA) -> str:
    """
    获取 UP主粉丝数

    API: https://api.bilibili.com/x/relation/stat?vmid={mid}
    失败返回空串（不展示粉丝标签）。
    """
    if not mid:
        return ""

    url = f"https://api.bilibili.com/x/relation/stat?vmid={mid}"
    headers = _build_headers(user_agent)
    headers["Referer"] = f"https://space.bilibili.com/{mid}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
    except Exception as e:
        logger.debug(f"[BiliParser] 粉丝数获取失败: {e}")
        return ""

    if data.get("code") != 0:
        return ""

    follower = (data.get("data") or {}).get("follower", 0) or 0
    return _format_number(follower) if follower > 0 else ""


# ── 各类型 API 调用函数 ───────────────────────────────────

async def fetch_video(bvid_or_aid: str, user_agent: str = DEFAULT_UA) -> BiliResult | None:
    """
    获取视频信息

    API: https://api.bilibili.com/x/web-interface/view
    """
    # 纯数字 = av 号（aid 参数），其余 = BV 号（bvid 参数，B站接受不带 BV 前缀的写法）
    key = "aid" if str(bvid_or_aid).isdigit() else "bvid"
    url = f"https://api.bilibili.com/x/web-interface/view?{key}={bvid_or_aid}"
    headers = _build_headers(user_agent)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"[BiliParser] 视频API HTTP {resp.status}")
                    return None
                data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[BiliParser] 视频API错误: code={data.get('code')} msg={data.get('message')}")
            return None

        video = data["data"]
        stat = video.get("stat", {})
        owner = video.get("owner", {})
        bvid = video.get("bvid", bvid_or_aid)

        online_text, fans_text = await asyncio.gather(
            _fetch_video_online(bvid, video.get("cid", 0), user_agent),
            _fetch_fans(owner.get("mid", 0), user_agent),
        )

        return BiliResult(
            link_type="video",
            bili_type="视频",
            title=video.get("title", ""),
            cover=video.get("pic", ""),
            author_name=owner.get("name", ""),
            author_face=owner.get("face", ""),
            desc=video.get("desc", ""),
            duration=video.get("duration", 0),
            pubdate=video.get("pubdate", 0),
            url=f"https://www.bilibili.com/video/{bvid}",
            stat_view=stat.get("view", 0),
            stat_danmaku=stat.get("danmaku", 0),
            stat_like=stat.get("like", 0),
            stat_coin=stat.get("coin", 0),
            stat_favorite=stat.get("favorite", 0),
            stat_share=stat.get("share", 0),
            stat_reply=stat.get("reply", 0),
            online_text=online_text,
            fans_text=fans_text,
            extra={"cid": video.get("cid", 0), "tname": video.get("tname", "")},
        )
    except Exception as e:
        logger.error(f"[BiliParser] 获取视频信息失败: {e}")
        return None


async def fetch_live(room_id: str, user_agent: str = DEFAULT_UA) -> BiliResult | None:
    """
    获取直播间信息

    API: https://api.live.bilibili.com/room/v1/Room/get_info
    """
    url = f"https://api.live.bilibili.com/room/v1/Room/get_info?id={room_id}"
    headers = _build_headers(user_agent)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"[BiliParser] 直播API HTTP {resp.status}")
                    return None
                data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[BiliParser] 直播API错误: code={data.get('code')} msg={data.get('message')}")
            return None

        info = data.get("data", {}).get("room_info", data.get("data", {}))
        anchor = data.get("data", {}).get("anchor_info", data.get("data", {}).get("anchor", {}))

        return BiliResult(
            link_type="live",
            bili_type="直播",
            title=info.get("title", ""),
            cover=info.get("cover", "") or info.get("user_cover", ""),
            author_name=anchor.get("base_info", {}).get("uname", info.get("uname", "")),
            author_face=anchor.get("base_info", {}).get("face", ""),
            desc=info.get("description", ""),
            url=f"https://live.bilibili.com/{room_id}",
            stat_view=info.get("online", 0),
            stat_like=info.get("attention", 0),
            live_status=info.get("live_status", 0),
        )
    except Exception as e:
        logger.error(f"[BiliParser] 获取直播信息失败: {e}")
        return None


async def fetch_bangumi(bgm_id: str, bgm_type: str, user_agent: str = DEFAULT_UA) -> BiliResult | None:
    """
    获取番剧/影视信息

    API: https://api.bilibili.com/pgc/view/web/season
    """
    if bgm_type == "bangumi_ep":
        url = f"https://api.bilibili.com/pgc/view/web/season?ep_id={bgm_id}"
    elif bgm_type == "bangumi_ss":
        url = f"https://api.bilibili.com/pgc/view/web/season?season_id={bgm_id}"
    elif bgm_type == "bangumi_md":
        url = f"https://api.bilibili.com/pgc/review/user?media_id={bgm_id}"
    else:
        return None

    headers = _build_headers(user_agent)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"[BiliParser] 番剧API HTTP {resp.status}")
                    return None
                data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[BiliParser] 番剧API错误: code={data.get('code')} msg={data.get('message')}")
            return None

        result = data.get("result", data.get("data", {}))

        # 提取媒体ID
        media_id = result.get("media_id", "")
        if not media_id and bgm_type == "bangumi_md":
            media_id = bgm_id

        web_url = f"https://www.bilibili.com/bangumi/play/ep{result.get('episodes', [{}])[0].get('ep_id', '')}" if result.get("episodes") else \
                  f"https://www.bilibili.com/bangumi/play/ss{result.get('season_id', '')}" if result.get("season_id") else \
                  f"https://www.bilibili.com/bangumi/media/md{media_id}"

        stat = result.get("stat", {})
        rating = result.get("rating", {})

        # 番剧的评分信息放入extra
        extra = {
            "rating_score": rating.get("score", 0),
            "styles": result.get("styles", []),
            "season_title": result.get("season_title", ""),
        }

        # 筛选可见的fields
        def _filter_visible_fields(fields: list[dict]) -> str:
            """提取fields中visible的value"""
            parts = []
            for f in fields:
                if f.get("visible", False) and f.get("value"):
                    parts.append(f["value"])
            return "  ".join(parts)

        # 提取UP主信息
        sections = result.get("sections", [])
        author_name = ""
        if sections:
            for ep in sections[0].get("episodes", []):
                if ep.get("badge") == "会员" and ep.get("badge_info", {}).get("content"):
                    author_name = ep["badge_info"]["content"]
                    break

        return BiliResult(
            link_type=bgm_type,
            bili_type="番剧",
            title=result.get("season_title", result.get("title", "")),
            cover=result.get("cover", ""),
            author_name=author_name or _filter_visible_fields(result.get("actor", {}).get("info", "") or "" or []),
            desc=result.get("evaluate", ""),
            pubdate=result.get("pub", {}).get("time", "") or "",
            url=web_url,
            stat_view=stat.get("views", 0),
            stat_danmaku=stat.get("danmakus", 0),
            stat_like=stat.get("likes", 0),
            stat_coin=stat.get("coins", 0),
            stat_favorite=stat.get("favorites", 0),
            stat_share=stat.get("share", 0),
            stat_reply=stat.get("reply", 0),
            extra=extra,
        )
    except Exception as e:
        logger.error(f"[BiliParser] 获取番剧信息失败: {e}")
        return None


async def fetch_article(cv_id: str, user_agent: str = DEFAULT_UA) -> BiliResult | None:
    """
    获取专栏信息

    API: https://api.bilibili.com/x/article/view
    """
    url = f"https://api.bilibili.com/x/article/view?id={cv_id}"
    headers = _build_headers(user_agent)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"[BiliParser] 专栏API HTTP {resp.status}")
                    return None
                data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[BiliParser] 专栏API错误: code={data.get('code')} msg={data.get('message')}")
            return None

        article = data["data"]
        stats = article.get("stats", {})

        cover = ""
        image_urls = article.get("image_urls", [])
        if image_urls:
            cover = image_urls[0]

        return BiliResult(
            link_type="article",
            bili_type="专栏",
            title=article.get("title", ""),
            cover=cover,
            author_name=article.get("author_name", ""),
            desc=article.get("summary", ""),
            pubdate=article.get("publish_time", 0),
            url=f"https://www.bilibili.com/read/cv{cv_id}",
            stat_view=stats.get("view", 0),
            stat_like=stats.get("like", 0),
            stat_coin=stats.get("coin", 0),
            stat_favorite=stats.get("favorite", 0),
            stat_share=stats.get("share", 0),
            stat_reply=stats.get("reply", 0),
            extra={"origin_image_urls": image_urls, "words": article.get("words", 0)},
        )
    except Exception as e:
        logger.error(f"[BiliParser] 获取专栏信息失败: {e}")
        return None


async def fetch_audio(au_id: str, user_agent: str = DEFAULT_UA) -> BiliResult | None:
    """
    获取音频信息

    API: https://api.bilibili.com/audio/music-service-c/songs/playing
    """
    url = f"https://api.bilibili.com/audio/music-service-c/songs/playing?song_id={au_id}"
    headers = _build_headers(user_agent)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"[BiliParser] 音频API HTTP {resp.status}")
                    return None
                data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[BiliParser] 音频API错误: code={data.get('code')} msg={data.get('message')}")
            return None

        song = data.get("data", data)
        stat = song.get("statistic", {})

        return BiliResult(
            link_type="audio",
            bili_type="音频",
            title=song.get("title", ""),
            cover=song.get("cover", ""),
            author_name=song.get("uname", ""),
            desc=song.get("intro", ""),
            url=f"https://www.bilibili.com/audio/au{au_id}",
            stat_view=stat.get("play", 0),
            stat_favorite=stat.get("collect", 0),
            stat_share=stat.get("share", 0),
            extra={"author": song.get("author", ""), "coin_num": _format_number(song.get("coin_num", 0))},
        )
    except Exception as e:
        logger.error(f"[BiliParser] 获取音频信息失败: {e}")
        return None


async def fetch_space(uid: str, user_agent: str = DEFAULT_UA) -> BiliResult | None:
    """
    获取用户空间信息

    API: https://api.bilibili.com/x/space/wbi/arc/search（简化版，仅获取基本信息）
    同时调用: https://api.bilibili.com/x/space/acc/info
    """
    # 优先使用 acc/info API，更轻量
    url = f"https://api.bilibili.com/x/space/acc/info?mid={uid}"
    headers = _build_headers(user_agent)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"[BiliParser] 空间API HTTP {resp.status}")
                    return None
                data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[BiliParser] 空间API错误: code={data.get('code')} msg={data.get('message')}")
            return None

        info = data["data"]

        return BiliResult(
            link_type="space",
            bili_type="用户空间",
            title=f"{info.get('name', '')} 的B站空间",
            cover=info.get("face", ""),
            author_name=info.get("name", ""),
            author_face=info.get("face", ""),
            desc=info.get("sign", ""),
            url=f"https://space.bilibili.com/{uid}",
            extra={"mid": uid, "level": info.get("level", 0), "sex": info.get("sex", "")},
        )
    except Exception as e:
        logger.error(f"[BiliParser] 获取空间信息失败: {e}")
        return None


async def fetch_opus(opus_id: str, user_agent: str = DEFAULT_UA) -> BiliResult | None:
    """
    获取动态信息

    API: https://api.bilibili.com/x/polymer/web-dynamic/v1/detail
    """
    url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id={opus_id}"
    headers = _build_headers(user_agent)
    headers["Origin"] = "https://t.bilibili.com"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"[BiliParser] 动态API HTTP {resp.status}")
                    return None
                data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[BiliParser] 动态API错误: code={data.get('code')} msg={data.get('message')}")
            return None

        item = data.get("data", {}).get("item", data.get("data", {}))
        modules = item.get("modules", {})
        author_module = modules.get("module_author", {})
        dynamic_module = modules.get("module_dynamic", {})
        stat_module = modules.get("module_stat", {})

        # 提取文本内容
        desc = dynamic_module.get("desc", {})
        text = desc.get("text", "") if isinstance(desc, dict) else ""

        # 提取封面图（可能是动态中的图片或视频封面）
        major = dynamic_module.get("major", {})
        cover = ""
        if major:
            archive = major.get("archive", {})
            if archive:
                cover = archive.get("cover", "")
            if not cover:
                opus_pics = major.get("opus", {}).get("pics", [])
                if opus_pics:
                    cover = opus_pics[0].get("url", "")
            if not cover:
                draw_items = major.get("draw", {}).get("items", [])
                if draw_items:
                    cover = draw_items[0].get("src", "")

        return BiliResult(
            link_type="opus",
            bili_type="动态",
            title=text[:60] if text else "(无文本动态)",
            cover=cover or author_module.get("face", ""),
            author_name=author_module.get("name", ""),
            author_face=author_module.get("face", ""),
            desc=text,
            url=f"https://www.bilibili.com/opus/{opus_id}",
            stat_view=stat_module.get("forward", {}).get("count", 0),
            stat_like=stat_module.get("like", {}).get("count", 0),
            stat_reply=stat_module.get("comment", {}).get("count", 0),
            extra={"type": dynamic_module.get("type", ""), "id_str": item.get("id_str", "")},
        )
    except Exception as e:
        logger.error(f"[BiliParser] 获取动态信息失败: {e}")
        return None


# ── 统一调度入口 ───────────────────────────────────────────

# API映射表
_FETCH_MAP = {
    "video": fetch_video,
    "live": fetch_live,
    "bangumi_ep": fetch_bangumi,
    "bangumi_ss": fetch_bangumi,
    "bangumi_md": fetch_bangumi,
    "article": fetch_article,
    "audio": fetch_audio,
    "space": fetch_space,
    "opus": fetch_opus,
    "short": None,  # short 需要先解析再重新分类
}


async def fetch_bili_info(link: BiliLink, user_agent: str = DEFAULT_UA, cookie: str = "") -> BiliResult | None:
    """
    统一入口：根据链接类型调用对应 B站 API

    Args:
        link: 解析出的 B站链接
        user_agent: 请求UA
        cookie: 可选cookie

    Returns:
        BiliResult 或 None（失败时）
    """
    from .link_parser import parse_bili_links

    # ── 步骤1: 处理短链接 ──
    if link.link_type == "short":
        real_url = await resolve_b23_url(link.id, user_agent, cookie)
        if not real_url:
            logger.warning(f"[BiliParser] 无法解析短链 b23.tv/{link.id}")
            return None
        resolved_links = parse_bili_links(real_url)
        if not resolved_links:
            logger.warning(f"[BiliParser] 短链 {real_url} 解析后没有匹配到已知链接类型")
            return None
        # 用解析后的链接替换
        link = resolved_links[0]
        logger.info(f"[BiliParser] 短链 {link.id} → {link.link_type}:{link.id}")

    # ── 步骤2: 获取对应的 fetch 函数 ──
    fetch_func = _FETCH_MAP.get(link.link_type)
    if fetch_func is None:
        logger.warning(f"[BiliParser] 不支持的链接类型: {link.link_type}")
        return None

    # ── 步骤3: 番剧类型特殊处理（需要 bgm_type 参数） ──
    if link.link_type in ("bangumi_ep", "bangumi_ss", "bangumi_md"):
        return await fetch_bangumi(link.id, link.link_type, user_agent)

    # ── 步骤4: 调用对应 API ──
    return await fetch_func(link.id, user_agent)


# ── 辅助函数 ──────────────────────────────────────────────

def _format_number(value: int) -> str:
    """将数字格式化为人类可读的形式（万、亿）"""
    if value >= 100000000:
        return f"{value / 100000000:.1f}亿"
    elif value >= 10000:
        return f"{value / 10000:.1f}万"
    return str(value)


def _get_live_status_text(status: int) -> str:
    """直播状态文本"""
    status_map = {0: "未开播", 1: "直播中", 2: "轮播中"}
    return status_map.get(status, "未知")