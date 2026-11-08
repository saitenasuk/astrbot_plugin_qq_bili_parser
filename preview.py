"""
HTML 卡片模板可视化预览脚本

用法：
    python preview.py              # 预览视频卡片
    python preview.py live         # 预览直播卡片
    python preview.py generic      # 预览通用卡片
    python preview.py all          # 一次性预览全部

启动后在浏览器中打开显示的地址，修改 HTML 后刷新页面即可实时看到效果。
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

import jinja2

TEMPLATES_DIR = Path(__file__).parent / "src" / "templates"

# ── 模拟数据 ──────────────────────────────────────────────

VIDEO_DATA = {
    "link_type": "video",
    "bili_type": "视频",
    "title": "【4K】《黑神话：悟空》最终预告 全面解读！究竟还有多少惊喜？",
    "cover": "https://i0.hdslb.com/bfs/archive/5edf22a45efc2b8e6f3c3e38a9b0c8b1da123456.jpg",
    "author_name": "智能路障",
    "author_face": "https://i0.hdslb.com/bfs/face/abc123def456.jpg",
    "desc": "从第一支预告到现在，我们已经等了四年。这支最终预告里到底藏了多少东西？让我一一拆解。",
    "duration": "18:42",
    "pubdate": "2024-08-08",
    "url": "https://www.bilibili.com/video/BV1xx411c7mD",
    "stat_view": "128.5万",
    "stat_danmaku": "3.2万",
    "stat_like": "12.1万",
    "stat_coin": "8.1万",
    "stat_favorite": "5.6万",
    "stat_share": "2.3万",
    "stat_reply": "1.5万",
    "live_status": 0,
    "live_status_text": "未开播",
    "extra": {"cid": 123456, "tname": "单机游戏"},
    "has_cover": True,
    "has_desc": True,
}

LIVE_DATA = {
    "link_type": "live",
    "bili_type": "直播",
    "title": "【直播】今晚只打瓦！来一起上分",
    "cover": "https://i0.hdslb.com/bfs/live/new_room_cover/abc123def456.jpg",
    "author_name": "老番茄",
    "author_face": "https://i0.hdslb.com/bfs/face/xyz789abc123.jpg",
    "desc": "CS2 排位冲分！欢迎大家来玩~",
    "duration": "",
    "pubdate": "",
    "url": "https://live.bilibili.com/654321",
    "stat_view": "3.7万",
    "stat_danmaku": "0",
    "stat_like": "12.3万",
    "stat_coin": "0",
    "stat_favorite": "0",
    "stat_share": "0",
    "stat_reply": "0",
    "live_status": 1,
    "live_status_text": "直播中",
    "extra": {},
    "has_cover": True,
    "has_desc": True,
}

BANGUMI_DATA = {
    "link_type": "bangumi_ep",
    "bili_type": "番剧",
    "title": "葬送的芙莉莲",
    "cover": "https://i0.hdslb.com/bfs/bangumi/image/abc123.jpg",
    "author_name": "MADHOUSE",
    "author_face": "",
    "desc": "打倒魔王的勇者一行人后日谈——魔法使芙莉莲的旅程。",
    "duration": "",
    "pubdate": "2023-09-29",
    "url": "https://www.bilibili.com/bangumi/play/ep123456",
    "stat_view": "2.1亿",
    "stat_danmaku": "156.2万",
    "stat_like": "6.8万",
    "stat_coin": "3.2万",
    "stat_favorite": "856.3万",
    "stat_share": "18.5万",
    "stat_reply": "12.3万",
    "live_status": 0,
    "live_status_text": "",
    "extra": {"rating_score": 9.9},
    "has_cover": True,
    "has_desc": True,
}

ARTICLE_DATA = {
    "link_type": "article",
    "bili_type": "专栏",
    "title": "【万字长文】从零开始理解 Transformer：注意力机制全解析",
    "cover": "https://i0.hdslb.com/bfs/column/abc123.jpg",
    "author_name": "3Blue1Brown",
    "author_face": "",
    "desc": "Transformer 是现代 AI 的基石。本文用可视化方式带你一步步理解它的工作原理。",
    "duration": "",
    "pubdate": "2024-06-15",
    "url": "https://www.bilibili.com/read/cv12345678",
    "stat_view": "56.8万",
    "stat_danmaku": "0",
    "stat_like": "3.5万",
    "stat_coin": "1.2万",
    "stat_favorite": "4.2万",
    "stat_share": "8.9千",
    "stat_reply": "2.1千",
    "live_status": 0,
    "live_status_text": "",
    "extra": {"words": 12480},
    "has_cover": True,
    "has_desc": True,
}

AUDIO_DATA = {
    "link_type": "audio",
    "bili_type": "音频",
    "title": "Gymnopédie No.1 - Erik Satie",
    "cover": "https://i0.hdslb.com/bfs/audio/abc123.jpg",
    "author_name": "音乐分享站",
    "author_face": "",
    "desc": "萨蒂最著名的钢琴作品，宁静而富有冥想气质。",
    "duration": "",
    "pubdate": "2024-03-10",
    "url": "https://www.bilibili.com/audio/au1234567",
    "stat_view": "3.2万",
    "stat_danmaku": "0",
    "stat_like": "560",
    "stat_coin": "0",
    "stat_favorite": "1.3万",
    "stat_share": "890",
    "stat_reply": "156",
    "live_status": 0,
    "live_status_text": "",
    "extra": {"author": "Erik Satie"},
    "has_cover": True,
    "has_desc": True,
}

SPACE_DATA = {
    "link_type": "space",
    "bili_type": "用户空间",
    "title": "泛式的B站空间",
    "cover": "https://i0.hdslb.com/bfs/face/fan123.jpg",
    "author_name": "泛式",
    "author_face": "https://i0.hdslb.com/bfs/face/fan123.jpg",
    "desc": "动画区UP主，喜欢请关注~",
    "duration": "",
    "pubdate": "",
    "url": "https://space.bilibili.com/12345678",
    "stat_view": "0",
    "stat_danmaku": "0",
    "stat_like": "0",
    "stat_coin": "0",
    "stat_favorite": "0",
    "stat_share": "0",
    "stat_reply": "0",
    "live_status": 0,
    "live_status_text": "",
    "extra": {"mid": "12345678", "level": 6},
    "has_cover": True,
    "has_desc": True,
}

OPUS_DATA = {
    "link_type": "opus",
    "bili_type": "动态",
    "title": "新视频做的差不多了，这周末发！先放个GIF预告~",
    "cover": "https://i0.hdslb.com/bfs/opus/dyn123.jpg",
    "author_name": "稚晖君",
    "author_face": "https://i0.hdslb.com/bfs/face/zhj123.jpg",
    "desc": "新视频做的差不多了，这周末发！先放个GIF预告~",
    "duration": "",
    "pubdate": "2024-07-01",
    "url": "https://www.bilibili.com/opus/123456789",
    "stat_view": "2.3万",
    "stat_danmaku": "0",
    "stat_like": "4.5万",
    "stat_coin": "0",
    "stat_favorite": "0",
    "stat_share": "0",
    "stat_reply": "3.2千",
    "live_status": 0,
    "live_status_text": "",
    "extra": {"type": "DYNAMIC_TYPE_WORD"},
    "has_cover": True,
    "has_desc": True,
}

GENERIC_DATA = {
    "link_type": "generic",
    "bili_type": "示例",
    "title": "新视频做的差不多了，这周末发！先放个GIF预告~",
    "cover": "https://i0.hdslb.com/bfs/opus/dyn123.jpg",
    "author_name": "稚晖君",
    "author_face": "https://i0.hdslb.com/bfs/face/zhj123.jpg",
    "desc": "新视频做的差不多了，这周末发！先放个GIF预告~",
    "duration": "",
    "pubdate": "2024-07-01",
    "url": "https://www.bilibili.com/opus/123456789",
    "stat_view": "2.3万",
    "stat_danmaku": "0",
    "stat_like": "4.5万",
    "stat_coin": "0",
    "stat_favorite": "0",
    "stat_share": "0",
    "stat_reply": "3.2千",
    "live_status": 0,
    "live_status_text": "",
    "extra": {"type": "DYNAMIC_TYPE_WORD"},
    "has_cover": True,
    "has_desc": True,
}

# ── 模板映射 ──────────────────────────────────────────────

PREVIEW_CONFIGS = {
    "video": ("video_card.html", VIDEO_DATA, "视频卡片预览"),
    "live": ("live_card.html", LIVE_DATA, "直播卡片预览"),
    "bangumi": ("generic_card.html", BANGUMI_DATA, "番剧卡片预览"),
    "article": ("generic_card.html", ARTICLE_DATA, "专栏卡片预览"),
    "audio": ("generic_card.html", AUDIO_DATA, "音频卡片预览"),
    "space": ("generic_card.html", SPACE_DATA, "空间卡片预览"),
    "opus": ("generic_card.html", OPUS_DATA, "动态卡片预览"),
    "generic": ("generic_card.html", GENERIC_DATA, "通用卡片预览"),
}


def render_html(template_name: str, data: dict) -> str:
    """用 Jinja2 渲染模板"""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    template = env.get_template(template_name)
    return template.render(**data)


def generate_preview_page(keys: list[str]) -> str:
    """生成包含多个卡片预览的 HTML 页面"""
    cards_html = ""
    for key in keys:
        tmpl_name, data, title = PREVIEW_CONFIGS[key]
        try:
            rendered = render_html(tmpl_name, data)
            cards_html += f'<div class="preview-section">\n'
            cards_html += f'  <h2 style="color:#4a5568;margin-bottom:12px;font-family:sans-serif">{title} — <code>{tmpl_name}</code></h2>\n'
            cards_html += f"  {rendered}\n"
            cards_html += f'</div>\n<hr style="margin:30px 0;border-color:#e2e8f0">\n'
        except Exception as e:
            cards_html += f"<p style='color:red'>渲染失败: {e}</p>\n"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>AstrBot B站卡片预览</title></head>
<body style="background:#edf2f7;padding:20px;">
  <h1 style="font-family:sans-serif;color:#1a202c">📱 B站链接解析卡片预览</h1>
  <p style="color:#a0aec0;margin-bottom:24px">修改对应 HTML 模板后刷新此页面即可看到效果</p>
  {cards_html}
</body>
</html>"""


class DynamicHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/.preview.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            # 重新生成预览页面（使用全部类型，或根据参数可定制）
            html = generate_preview_page(list(PREVIEW_CONFIGS.keys()))
            self.wfile.write(html.encode("utf-8"))
        else:
            # 其他路径可继续提供静态资源（如 CSS/图片），如果需要
            super().do_GET()


def serve_preview(keys: list[str], port: int = 8765):
    """启动 HTTP 服务器，预览 keys 中指定的卡片类型"""
    os.chdir(Path(__file__).parent)
    socketserver.TCPServer.allow_reuse_address = True

    # 动态创建 handler 类，捕获当前 keys
    class PreviewHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path == "/.preview.html":
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                html = generate_preview_page(keys)  # 使用外部 keys
                self.wfile.write(html.encode("utf-8"))
            else:
                # 其他路径（如静态资源）交给父类处理
                super().do_GET()

        def log_message(self, format, *args):
            pass  # 静默日志（可选）

    with socketserver.TCPServer(("", port), PreviewHandler) as httpd:
        print(f"  🔗 预览地址: http://localhost:{port}/")
        print(f"  预览类型: {', '.join(keys)}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.shutdown()
            httpd.server_close()
            print("\n已停止")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "video"
    if arg == "all":
        keys = list(PREVIEW_CONFIGS.keys())
    elif arg in PREVIEW_CONFIGS:
        keys = [arg]
    else:
        print(f"未知类型: {arg}")
        print(f"可选: {', '.join(PREVIEW_CONFIGS.keys())} / all")
        sys.exit(1)
    serve_preview(keys)  # 不再传递 html_content
