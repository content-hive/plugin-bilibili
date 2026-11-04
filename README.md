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

## Disclaimer

> 本插件通过解析哔哩哔哩链接获取内容。可选配置账号 Cookie 以访问更高清晰度或需要登录的内容，存在账号被封禁的风险。使用前请确保符合哔哩哔哩服务条款及当地法律法规，并自行承担相关风险。平台规则变更可能导致插件失效。
