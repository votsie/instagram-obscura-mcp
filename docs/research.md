# Packaging research

Snapshot: 2026-11-14. Star counts are a point-in-time observation, not a quality or security guarantee.

| Reference | GitHub stars | Pattern adopted |
| --- | ---: | --- |
| [MCP reference servers](https://github.com/modelcontextprotocol/servers) | 91,971 | Capability-oriented navigation and protocol context |
| [Context7](https://github.com/upstash/context7) | 64,757 | Strong cover, concise value proposition, short installation path |
| [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) | 55,360 | Clear requirements, client setup, first prompt and tool reference |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | 39,605 | Client configuration examples and detailed capability documentation |
| [Obscura](https://github.com/h4ckf0r0day/obscura) | 34,911 | Existing runtime, retained rather than reimplemented |

Decision: **Extend/Compose** the working Instagram MCP, the official MCP SDK, Obscura, Playwright and local faster-whisper/FFmpeg. No upstream README text, artwork or branding was copied.

Search covered the source repository and adjacent projects, authenticated GitHub repository inventory and code search, public GitHub sorted by stars, npm, PyPI, installed ECC skills, MCP tools and skills.sh. Existing Instagram packages mainly target the Graph API or hosted public-data access and do not replace the required personal-account Playwright → Obscura flow. The author's existing ssh-mcp and wata-mcp were also reviewed for reuse. GitHub code search depends on indexing and cannot prove that every private file was searched.

SEO work follows [GitHub topics guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics) and [Google's localized-page guidance](https://developers.google.com/search/docs/specialty/international/localized-versions). llms.txt is a navigation aid, not a guarantee of indexing or model behavior.
