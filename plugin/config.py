"""Bilibili plugin configuration schema."""

from pydantic import Field

from contenthive.plugins.contracts import PluginConfigSchema


class ConfigSchema(PluginConfigSchema):
    cookies: str = Field(
        default="",
        title="Cookie",
        description="可选。哔哩哔哩账号 Cookie 字符串。填写后可获取更高清晰度或需要登录的内容。",
        json_schema_extra={"secret": True},
    )
    download_max_retries: int = Field(
        default=3,
        title="下载重试次数",
        description="下载失败时的重试次数",
    )


CONFIG_SCHEMA = ConfigSchema
