# 第三方依赖与服务

本仓库通过 `requirements.txt` 声明依赖，不附带这些库的源码或二进制。以下是直接依赖；安装版本及传递依赖以实际环境为准。重新分发打包应用时应审查并附带所分发组件要求的版权与许可证。

| 依赖 | 用途 | 上游许可与来源 |
| --- | --- | --- |
| python-docx | Word 读写 | MIT · <https://github.com/python-openxml/python-docx> |
| pypdf | PDF 文本读取 | BSD-3-Clause · <https://github.com/py-pdf/pypdf> |
| reportlab | PDF 输出 | BSD 风格许可，以安装版本 LICENSE 为准 · <https://www.reportlab.com/> |
| Pillow | 图片处理 | MIT-CMU/HPND 系列及包含组件条款，以安装版本 LICENSE 为准 · <https://github.com/python-pillow/Pillow> |

Python 及标准库使用其各自许可证。运行时可能涉及上述库的传递依赖；此表不是完整打包软件物料清单。

Crossref 用于候选文献元数据查询；使用须遵守其服务和数据条款。模型 API 由用户自行配置，其模型、接口、费用及内容使用条款不由本仓库的 MIT 许可证授予。
