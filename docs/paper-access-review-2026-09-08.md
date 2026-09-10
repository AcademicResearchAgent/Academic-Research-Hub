科研工作站论文检索与获取调研

本文是首轮基础渠道检查。随后增加的真实 Agent 任务、两种方案对比和扩展接口验证，见 [综合调研](paper-retrieval-options-2026-09-08.md)。

调研日期：2026-09-08。对象：服务器 42.193.15.167 上的 Open WebUI + Hermes 0.21.0（693641aa8b4359c602283bdbbc14041e03bc47bc）+ DeepSeek。依据：当前部署配置、直接工具/API 实测、官方文档。

**结论**

当前系统可以检索论文、下载部分公开论文并提取正文。论文来源由 Hermes 调用的搜索、HTTP、浏览器或 MCP 工具提供；DeepSeek 负责理解问题和选择工具。无需为了获得公开论文而先更换 GPT。

当前系统还未建立科研工作站所需的稳定跨库文献工作流。单次工具连通成功不代表模型会自主完成系统检索、全文筛选、引用核验和综述，也不代表跨用户资料隔离已经完成。

**服务器实际状态与验证**

- API 工具集为 hermes-cli，服务器已有 arxiv、grounded-citations 技能文件。
- 未配置学术 MCP 服务；检查的 NCBI、OpenAlex、Semantic Scholar API 密钥均未设置。
- 未配置所检查的常见网页搜索服务凭据。Hermes 自动选择 keenable 后端，启用了无密钥回退；实际 web_search 调用成功，因此不能根据“没有搜索密钥”断定无法联网。
- Hermes Python 环境未安装 pypdf、PyMuPDF（fitz）、pdfplumber、ddgs。本次没有安装任何软件或修改运行配置。

| 测试 | 实测结果 | 能说明什么 |
| --- | --- | --- |
| Hermes web_search 查询 Attention Is All You Need | 约 3 秒返回 arXiv 摘要页、PDF、HTML 三个结果 | 当前网页搜索工具确实能发现论文 |
| Hermes web_extract 读取 arXiv HTML | 返回约 1.5 万字符响应，含 Scaled Dot-Product 正文内容 | 能提取正文片段；本次设置字符上限，未验证全文完整性 |
| PubMed ESearch，CRISPR | HTTP 200，返回 PMID | 官方题录检索接口可达 |
| Europe PMC 搜索，CRISPR | HTTP 200，有命中记录 | 生物医学聚合检索可达 |
| Crossref 标题查询 | HTTP 200，有题录记录 | DOI/元数据检索可达 |
| OpenAlex 搜索，无密钥 | HTTP 200，有返回记录 | 当前匿名小规模检索可用 |
| Semantic Scholar 搜索，无密钥 | HTTP 429 | 当前请求受到限流；不能推断接口长期不可用 |
| arXiv API 标题查询 | 约 26 秒 ReadTimeout | 当前服务器此请求超时，需要重试/备用来源 |
| arXiv PDF 1706.03762 | HTTP 200，2,215,244 字节，%PDF 文件头，约 135 秒 | 能下载真实 PDF；未验证 PDF 内容解析、完整性及批量稳定性 |
| Europe PMC PMC3257301/fullTextXML | HTTP 200，159,879 字节，正文约 71,725 字符 | 已实际获取并解析开放论文的 XML 正文 |

这些测试在服务器上直接调用工具或公开接口，没有用 DeepSeek 完成一次自主多篇论文调研，也没有做 GPT/DeepSeek 质量对照。耗时属于单次观测，不能作为平均性能指标。测试下载内容在内存中处理，未建立论文库。

复现脚本位于 deploy/hermes：audit-paper-access.sh、probe-hermes-web.sh、probe-paper-fulltext.sh；通过 remote.py 执行。完整审计脚本后续增加了 180 秒总时限，并改为完成一个请求就输出一个结果。

**Codex/GPT 的检索渠道是什么**

Codex 的官方文档描述了内置网页搜索：默认缓存搜索，还可以配置实时搜索；这是产品提供的工具能力。Codex 也支持 MCP 扩展数据和工具来源。[Codex 搜索配置](https://learn.chatgpt.com/docs/config-file/config-basic)、[MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

OpenAI API 通过显式配置 web_search 提供联网检索；Deep Research API 要求至少一个数据源，如网页搜索、远程 MCP 或文件检索。不能把更换模型名称等同于接通这些工具，也不能把 Codex、ChatGPT 和单纯 GPT API 视为配置完全相同的产品。[Web search](https://developers.openai.com/api/docs/guides/tools-web-search)、[Deep research](https://developers.openai.com/api/docs/guides/deep-research)。

所查官方文档没有证明 Codex 默认拥有覆盖所有学术库、可下载所有付费论文的独占渠道。具体订阅库访问取决于产品、已连接服务及用户权限。我们这次 Codex 调研使用了网页搜索和服务器 HTTP 请求，没有使用付费论文库账号。

Hermes 同样支持本地或远程 MCP 工具，因此学术数据接入可以独立于推理模型设计。[Hermes MCP 官方文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)。

**适合本项目的数据源分工**

| 数据源 | 建议用途 | 全文边界 |
| --- | --- | --- |
| PubMed | 生物医学题录、摘要、MeSH 检索 | PubMed 本身主要是引文和摘要；另外解析 PMC 或出版社全文链接 |
| Europe PMC / PMC OA | 开放生物医学正文、参考文献及结构化 XML | 使用允许自动获取的接口，按文章的许可和开放状态处理 |
| arXiv | 计算机、数学、物理等预印本题录和全文 | 记录版本及预印本身份；API 超时时可用其他索引发现原文 |
| OpenAlex | 跨学科搜索、作者/主题/引文关联、OA 地址 | 题录、OA 地址和内容下载是不同能力；内容 API 另有密钥及用量条件 |
| Crossref | DOI 匹配、元数据校验、去重辅助 | 不应把题录记录当成已经获取全文 |
| Unpaywall | 由 DOI 定位免费可读副本 | 返回 OA 位置而非保证任意论文可下载；新项目也可直接利用 OpenAlex 的 OA 字段 |
| Semantic Scholar | 相关论文发现、引文关系、OA PDF 地址 | 本次匿名请求限流，先配置配额、缓存与退避再纳入稳定工作流 |

依据：[PubMed 数据接口](https://pubmed.ncbi.nlm.nih.gov/download/)、[Europe PMC REST](https://europepmc.org/RestfulWebService)、[PMC 自动获取渠道](https://pmc.ncbi.nlm.nih.gov/tools/textmining/)、[arXiv API](https://info.arxiv.org/help/api/user-manual.html)、[OpenAlex API](https://help.openalex.org/api/)、[Crossref REST](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)、[Unpaywall](https://help.openalex.org/access/unpaywall/)、[Semantic Scholar API 示例](https://api.semanticscholar.org/api-docs/snippets)。

OpenAlex 当前官方文档允许无密钥基本查询，免费密钥提高额度；不能照搬旧文档的配额结论。其全文归档可提供 PDF 和 GROBID TEI XML，但覆盖有限，内容文件保留原版权，解析结果可能出错。按本次官方文档，单文件内容下载标价 0.01 美元，免费密钥的日额度可用于小规模试用；实际接入前核对账号当日条件。本次未调用该内容 API。[认证及额度](https://help.openalex.org/api/authentication/)、[全文归档](https://help.openalex.org/access/fulltext/)。

**建议的落地顺序**

第一阶段保留现有模型与界面，增加一个供 Hermes 调用的学术检索服务（原生工具或 MCP）：先接 PubMed、Europe PMC、OpenAlex、Crossref；arXiv 保留并加入超时及备用发现渠道。使用结构化结果而非只给网页搜索摘要。

最小工具接口建议：search_papers、get_paper_metadata、resolve_fulltext、fetch_fulltext、read_paper、export_citations。每篇文献记录 DOI/PMID/PMCID/arXiv ID、标题、作者、年份、版本、来源和获取时间；区分仅题录、仅摘要、正文已获取、获取失败。检索式、筛选条件和去重记录应可导出复现。

全文优先解析 XML/HTML，然后处理文本 PDF，扫描件最后进入 OCR 队列。保存章节/页码与原文定位，回答中的引用绑定这些证据。下载及解析需要队列、进度提示、总超时、重试、限流退避和缓存。本次 arXiv 下载耗时说明这些机制直接影响用户体验。

当前约 4 GB 内存的服务器适合先采用按需下载、轻量文本解析、低并发方式；此为部署建议，尚未进行 OCR 或批量解析负载测试。不建议在没有性能验证时直接加装重型本地 OCR/视觉模型。论文文件、缓存权限、项目记忆必须与用户/任务隔离一起设计，不能仅依赖前端账号。

第二阶段再建立文献筛选、结构化证据表、综述和实验设计工作流。优先让输出明确声明证据范围：仅看摘要时不能声称已核查方法细节，未获得实验数据时不能编造实验结果。仅凭少量搜索结果不足以确认研究空白。

第三阶段做模型对照：固定同一批文献、相同检索工具与提示，对比 DeepSeek/GPT 的检索执行成功率、引用准确率、全文证据定位、方法提取质量、耗时及成本。再决定是否将复杂综述/设计任务路由到更强模型。此次调研没有证据支持“只换 GPT 就能完成科研工作站”。

建议验收至少覆盖：跨库同篇去重、摘要与全文状态准确、下载失败明确反馈、引用可定位、检索可重放、两账号相同提问资料不串用。当前仅完成渠道调研和连通性验证，上述服务尚未部署。
