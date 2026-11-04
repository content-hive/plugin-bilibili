# Content Hive Plugin: 哔哩哔哩

适用于 Content Hive 的哔哩哔哩内容解析插件。通过解析视频链接，提取视频、作者信息等数据。

Plugin for [Content Hive](https://github.com/content-hive/content-hive).

## Layout

```
plugin/              # plugin source, installed as plugins/bilibili/ by Content Hive
├── manifest.json    # plugin metadata (domain, version, requirements, release_notes)
├── __init__.py
└── ...
contenthive.json     # repository metadata for the Content Hive plugin catalog
```

## Supported URLs

- `https://www.bilibili.com/video/BVxxxx` / `av123`
- `https://m.bilibili.com/video/BVxxxx`
- Multi-part videos with `?p=` (current part only)
- `https://b23.tv/...` short links

Bangumi seasons, courses, user spaces, favorites, live streams, and interactive branches are not supported in this version.

## Quality

The plugin requests DASH play URLs and returns the highest video track with the highest audio track (including Dolby Vision / 4K / AV1 when the account can access them). Content Hive muxes those tracks into a single mp4.

Without a logged-in Cookie, Bilibili typically caps streams around 720P. After setting Cookie, re-parse existing items to replace already-downloaded 720P files.

插件会请求 DASH 播放地址，并返回最高视频轨与最高音频轨（账号有权限时可到杜比视界 / 4K / AV1）。由 Content Hive 核心混流为单个 mp4。未登录时 B 站通常只给到 720P；设置 Cookie 后需要重新解析才会替换已经下好的低画质文件。

## Disclaimer

> 本插件通过解析哔哩哔哩链接获取内容。可选配置账号 Cookie 以访问更高清晰度或需要登录的内容，存在账号被封禁的风险。使用前请确保符合哔哩哔哩服务条款及当地法律法规，并自行承担相关风险。平台规则变更可能导致插件失效。
