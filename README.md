# AstrBot B站链接解析插件

> 自动解析 QQ 群消息中的 B站链接，渲染精美图片卡片并回复

## ✨ 功能

- 🔗 **自动识别** QQ 群消息中的 B站链接
- 🎨 **精美卡片** 渲染为信息图片（封面、标题、UP主、统计数据等）
- 📦 **全类型支持** 视频、直播、番剧、专栏、音频、动态、用户空间
- 🔗 **短链支持** 自动解析 `b23.tv` 短链接
- 🛡️ **降级策略** T2I 服务不可用时自动降级为纯文本回复
- ⚙️ **灵活配置** 可控制解析类型、数量上限、图片质量等

## 📋 支持的链接类型

| 类型 | 示例链接 | 卡片模板 |
|------|---------|----------|
| 视频 | `bilibili.com/video/BV1xx...` | 🎬 视频卡片 |
| 短链接 | `b23.tv/xxxx` | 🔗 → 解析后对应类型 |
| 直播 | `live.bilibili.com/12345` | 🔴 直播卡片 |
| 番剧 | `bilibili.com/bangumi/play/ep...` | 📺 通用卡片 |
| 专栏 | `bilibili.com/read/cv...` | 📝 通用卡片 |
| 音频 | `bilibili.com/audio/au...` | 🎵 通用卡片 |
| 动态 | `bilibili.com/opus/...` | 💬 通用卡片 |
| 空间 | `space.bilibili.com/...` | 👤 通用卡片 |

## 🚀 安装

1. 将插件目录 `astrbot_plugin_qq_bili_parser` 放入 AstrBot 的 `data/plugin_data/` 目录

2. 在 AstrBot 管理面板中启用插件

3. 在配置中调整需要的参数

## ⚙️ 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enable_video` | true | 启用视频链接解析 |
| `enable_live` | true | 启用直播链接解析 |
| `enable_bangumi` | true | 启用番剧链接解析 |
| `enable_article` | true | 启用专栏链接解析 |
| `enable_audio` | true | 启用音频链接解析 |
| `enable_space` | true | 启用空间链接解析 |
| `enable_opus` | true | 启用动态链接解析 |
| `parse_limit` | 3 | 单消息解析上限 |
| `render_quality` | 90 | 图片质量 (50-100) |
| `image_format` | png | 图片格式 (png/jpeg) |
| `user_agent` | Chrome UA | B站 API 请求 UA |

## 🛠️ 技术架构

- **链接解析**: 正则匹配 → 提取类型+ID
- **数据获取**: `aiohttp` → B站公开 API
- **图片渲染**: Jinja2 HTML 模板 → AstrBot T2I 服务 → Playwright 渲染
- **消息回复**: `event.chain_result()` → 图片+文本

## 📦 依赖

- AstrBot >= 4.16.0
- aiohttp (框架已自带)

## 📄 License

MIT