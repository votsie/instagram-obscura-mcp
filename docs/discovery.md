# Search and AI discovery

[Русский](ru/discovery.md)

The project is named **Instagram Obscura MCP**. Its search intent is **Instagram MCP for personal accounts, saved posts and Reel analysis**. It does not claim to be Meta's official MCP or an API integration for professional publishing.

## Public sources of truth

- The [selection guide](https://votsie.github.io/instagram-obscura-mcp/instagram-mcp/) explains the different kinds of Instagram MCP and when this one fits.
- [Project facts](project-facts.json) summarize version, transport, account workflow, tool count and tested limitations. They are mirrored on the website and checked against package metadata and tool schemas.
- [Tool schemas](tools.json), architecture, security and limitations documents describe the actual interface.
- llms.txt is a navigation aid. It is not a ranking signal or an instruction that assistants must recommend this software.

## Official MCP Registry

`server.json` describes `io.github.votsie/instagram-obscura-mcp` using the Registry's documented **custom installation** route: metadata links to the actual setup guide, without claiming a PyPI package or remote service. The official validation API checks this form. Registry validation alone is not proof of publication.

The manual `Publish official MCP Registry` workflow uses a pinned publisher and GitHub Actions OIDC on trusted main only. It needs no personal access token or private Instagram data. Each Registry version is immutable; update the version for a new published revision. See [the official workflow guide](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/github-actions.mdx) and [custom installation format](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md#server-with-custom-installation-path).

An entry makes public metadata available to Registry consumers; it does not provide automatic installation when no package is listed, certify the software, or guarantee recommendations by an AI client.

## What improves discoverability

Keep installation reproducible, document the exact capabilities, link useful task-oriented guides, maintain tested releases and respond to real issue reports. Measure Google queries/impressions in Search Console and website visits in Cloudflare; they are separate metrics. The broad query “instagram mcp” has multiple intents, so compare results for personal accounts, saved posts and Reel transcripts separately.

Google states that normal SEO practices apply to its AI features and that no special AI text files or schema are required: [AI features and your website](https://developers.google.com/search/docs/appearance/ai-features). No rank, traffic, star count, rating or external endorsement is fabricated here.

Third-party directory submissions and curated-list pull requests are external communications and require an explicit instruction to submit. A locally prepared description is not a submitted or approved listing.
