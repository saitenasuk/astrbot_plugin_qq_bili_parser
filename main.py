"""
AstrBot QQ B站链接解析插件

监听 QQ 群消息中的 B站链接，解析视频/直播/番剧/专栏/音频/动态/空间信息，
通过 AstrBot 内置 T2I 服务渲染为精美图片卡片并回复。
"""

import asyncio
import logging
import os
from pathlib import Path

from astrbot.api import AstrBotConfig, logger as astrbot_logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .src.bili_api import (
    DEFAULT_UA,
    fetch_bili_info,
    resolve_b23_url,
)
from .src.link_parser import (
    BiliLink,
    get_type_display_name,
    parse_bili_links,
)

logger = logging.getLogger("astrbot")

# ── 模板文件路径 ─────────────────────────────────────────────
_TEMPLATES_DIR = Path(__file__).parent / "src" / "templates"

# 各类型 -> 模板文件映射
_TEMPLATE_MAP = {
    "video": "video_card.html",
    "live": "live_card.html",
    "bangumi_ep": "generic_card.html",
    "bangumi_ss": "generic_card.html",
    "bangumi_md": "generic_card.html",
    "article": "generic_card.html",
    "audio": "generic_card.html",
    "space": "generic_card.html",
    "opus": "generic_card.html",
}


def _read_template(name: str) -> str:
    """读取 HTML 模板文件内容"""
    template_path = _TEMPLATES_DIR / name
    if not template_path.exists():
        raise FileNotFoundError(f"模板文件不存在: {template_path}")
    return template_path.read_text(encoding="utf-8")

def _extract_all_text(event) -> str:
    """从消息事件中提取所有文本，包括纯文本和 JSON/小程序的链接"""
    texts = [event.message_str or ""]

    try:
        msg_obj = event.message_obj
        if msg_obj and hasattr(msg_obj, "message"):
            for comp in msg_obj.message:
                comp_data = None
                # 尝试多种方式获取组件数据
                if hasattr(comp, "data") and isinstance(comp.data, dict):
                    comp_data = comp.data
                elif hasattr(comp, "toDict"):
                    try:
                        d = comp.toDict()
                        if isinstance(d, dict):
                            comp_data = d.get("data", d)
                    except Exception:
                        pass

                if comp_data:
                    # JSON 消息（小程序分享卡/链接分享）
                    comp_text = str(comp_data)
                    texts.append(comp_text)
    except Exception:
        pass

    return " ".join(t for t in texts if t)



class BiliParserPlugin(Star):
    """B站链接解析插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        logger.info("[BiliParser] B站链接解析插件已加载")

    # ── 消息处理器 ──────────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """监听群消息，解析 B站链接并回复"""
        # 1. 检查平台
        platform = event.get_platform_name()
        if platform != "aiocqhttp":
            return

        # 2. 获取消息文本（含小程序卡片、JSON等非文本组件）
        msg_text = _extract_all_text(event)
        if not msg_text:
            return

        # 3. 解析 B站链接
        links = parse_bili_links(msg_text)
        if not links:
            return

        # 4. 检查启用配置
        parse_limit = self._config_int("parse_limit", 3)
        links = links[:parse_limit]

        logger.info(f"[BiliParser] 检测到 {len(links)} 个B站链接")

        # 5. 获取配置
        user_agent = self._config_str("user_agent", DEFAULT_UA)
        render_quality = self._config_int("render_quality", 90)
        image_format = self._config_str("image_format", "png")

        # 6. 遍历处理每个链接
        results = []
        for link in links:
            # 检查类型是否启用
            enable_key = _get_enable_key(link.link_type)
            if enable_key and not self._config_bool(enable_key, True):
                continue

            # 调用 API
            bili_result = await fetch_bili_info(link, user_agent)
            if bili_result is None:
                # API 失败 → 降级文本
                results.append(f"❌ 获取{get_type_display_name(link.link_type)}信息失败")
                continue

            # 获取对应模板
            template_name = _TEMPLATE_MAP.get(bili_result.link_type, "generic_card.html")
            try:
                tmpl_str = _read_template(template_name)
            except FileNotFoundError as e:
                logger.error(f"[BiliParser] {e}")
                results.append(bili_result.fallback_text())
                continue

            # 调用 html_render 渲染图片
            render_data = bili_result.to_dict()
            options = {
                "full_page": True,
                "type": image_format,
                "quality": render_quality,
            }

            try:
                image_url = await self.html_render(
                    tmpl=tmpl_str,
                    data=render_data,
                    return_url=True,
                    options=options,
                )
            except Exception as e:
                logger.warning(f"[BiliParser] html_render 失败: {e}, 降级为纯文本")
                results.append(bili_result.fallback_text())
                continue

            # 构建回复
            results.append({
                "image_url": image_url,
                "text": bili_result.url or "",
            })

        # 7. 组装并发送回复
        if not results:
            return

        all_text_parts = []  # 纯文本累积
        chain_components = []  # 消息链组合

        for i, result in enumerate(results):
            if isinstance(result, str):
                # 纯文本错误消息
                all_text_parts.append(result)
            else:
                # 成功渲染的结果
                from pathlib import Path
                chain_components.extend(_build_reply_components(result["image_url"], result["text"]))

        if all_text_parts:
            # 先发文本错误
            text_msg = "\n".join(all_text_parts)
            yield event.plain_result(text_msg)

        if chain_components:
            yield event.chain_result(chain_components)

    # ── 配置读取辅助方法 ──────────────────────────────────

    def _config_str(self, key: str, default: str) -> str:
        """读取字符串类型配置"""
        try:
            val = self.config.get(key)
            if val is None or val == "":
                return default
            return str(val)
        except Exception:
            return default

    def _config_int(self, key: str, default: int) -> int:
        """读取整数类型配置"""
        try:
            val = self.config.get(key)
            if val is None:
                return default
            result = int(val)
            return result if result > 0 else default
        except (ValueError, TypeError):
            return default

    def _config_bool(self, key: str, default: bool) -> bool:
        """读取布尔类型配置"""
        try:
            val = self.config.get(key)
            if val is None:
                return default
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes")
            return bool(val)
        except Exception:
            return default


# ── 辅助函数 ─────────────────────────────────────────────

def _get_enable_key(link_type: str) -> str | None:
    """将链接类型映射到配置项 key"""
    mapping = {
        "video": "enable_video",
        "live": "enable_live",
        "bangumi_ep": "enable_bangumi",
        "bangumi_ss": "enable_bangumi",
        "bangumi_md": "enable_bangumi",
        "article": "enable_article",
        "audio": "enable_audio",
        "space": "enable_space",
        "opus": "enable_opus",
    }
    return mapping.get(link_type)


def _build_reply_components(image_url: str, caption_text: str) -> list:
    """
    构建回复消息组件列表。

    使用 AstrBot 的 Image 组件发送图片（支持 URL/本地路径/base64）。
    附带文本链接。
    """
    from astrbot.core.message.components import Image, Plain

    components = []

    if image_url:
        if image_url.startswith(("http://", "https://")):
            # 网络图片 URL → Image 组件（T2I 返回的就是 URL）
            components.append(Image.fromURL(image_url))
        elif image_url.startswith("base64://"):
            # Base64 图片
            components.append(Image.fromBase64(image_url.removeprefix("base64://")))
        elif image_url.startswith("file:///"):
            # 本地文件
            components.append(Image.fromFileSystem(image_url[8:]))
        else:
            # 可能是本地路径
            components.append(Image.fromFileSystem(image_url))

    if caption_text:
        components.append(Plain(caption_text))

    return components


# ── T2I 渲染配置 ──────────────────────────────────────────

# T2I options 默认配置说明:
# - full_page: True  → 截取完整页面
# - type: "png"/"jpeg" → 输出图片格式
# - quality: 1-100 → JPEG 质量（PNG 忽略此参数）
# - device_scale_factor_level: "normal"/"ultra" → 设备像素比
#   可通过 options dict 传入额外参数