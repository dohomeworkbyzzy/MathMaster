# 知识向量与 API 配置

打开软件左侧「API 配置」。解题模型和知识向量模型分开选择；保存多个配置后点击「启用」即可切换。原来的 DeepSeek V4.1 Flash 配置会沿用。本机密钥不会返回到浏览器，也不会写入题库、浏览器存储或检索结果。

- 解题支持 OpenAI Chat Completions 和 Anthropic Messages，支持各自协议的中转站。接口地址可填根地址、`/v1` 或完整接口地址；本机代理可用 HTTP。
- 默认向量模型是本地中文 BGE-small-zh-v1.5，512 维，CPU 运行，无向量 API 费用。也可以新增 OpenAI Embeddings 兼容服务。Anthropic 不提供原生 embedding，解题使用 Anthropic 时仍可搭配本地或其他向量服务。
- 新试卷默认自动预解析并建索引。扫描题图的一次性解析会调用当前解题 API；本地 embedding 本身不消耗 token。进度和错误会显示在配置页，失败后点击「补全 / 重试索引」。已有且未改变的解析和向量会复用，重启可恢复未完成任务。
- 左侧「相似题」输入知识方向，例如「泰勒展开判断等价无穷小」「Cache 地址划分」。AI 解题中的「推荐下一题」也使用同一向量库，并优先选择接近的未完成题或错题。

索引重点使用考察方向、技能、解题方法和理解要点，并补充常见大纲概念。完整答案、参考解析、个人作答和数值参数不进入文档向量。排序结合语义相似度与知识点重合；分数不是正确率。原题或图片发生修改后旧向量会失效，必须按新版本重新解析。不同向量模型和账号拥有独立索引空间，切换后自动补全所选空间；切换解题模型不重建向量。

向量与任务存放在 `data/mathmaster.db`；模型文件在 `data/models/bge-small-zh-v1.5`。API 配置在当前用户的 `.config/mathmaster/providers.json`，不会进入题库备份。清空临时 AI 缓存不会删除知识向量。恢复备份后需保留模型文件，或用项目 Python 运行 `scripts/download_embedding_model.py` 下载固定版本，再运行 `scripts/index_knowledge.py` 补全索引。

协议与模型依据：[OpenAI embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)、[Anthropic embeddings 说明](https://platform.claude.com/docs/en/build-with-claude/embeddings)、[BGE 原始模型](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[ONNX 转换版本](https://huggingface.co/Xenova/bge-small-zh-v1.5)。


AI 解题面板的模型名称旁新增「思考强度」，可直接调整并保存到当前 API 配置；配置编辑页也有同一选项。默认沿用高级参数或供应商默认，不改动已有配置。切换强度后下一次请求生效，正在处理时快捷选择会禁用。不同强度的请求分别匹配缓存，不重建知识库或向量索引。

档位按模型区分：DeepSeek Flash 为关闭、低、高、最高；GLM-5.3 为低、高、最高；GPT-6.1 Sol 为低、中、高、超高、最高；均另有默认选项。Qwen 使用思考预算，Claude 根据版本使用预算或自适应思考。强度较高通常需要更多时间与 tokens，实际用量以接口返回为准。

参数依据：[DeepSeek](https://api-docs.deepseek.com/guides/thinking_mode/)、[GLM-5.3](https://docs.z.ai/guides/llm/glm-5.3)、[OpenAI Docs: GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Claude](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)、[Qwen](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/)。
