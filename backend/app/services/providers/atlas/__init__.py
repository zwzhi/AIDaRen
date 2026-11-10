"""Atlas Cloud 接入（商业模板业务域专用）。

与底座 TokenFree 通道完全隔离：
- 配置存独立命名空间（Settings.atlas_* / commercial_*，DB flat 加密）；
- 不注册为 SystemModelChannelRow，不被启动渠道归一停用；
- 旧业务（kepu/drama/studio/tools）继续走 TokenFree，互不可见对方的密钥与 Base URL。
"""
