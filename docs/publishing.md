# Release preparation

The repository is staged locally for review. Creating a public GitHub repository, pushing the initial commit and deploying Pages require the owner's final approval.

## Intended metadata

- Repository: `votsie/instagram-obscura-mcp`
- Description: `Instagram MCP for personal accounts: Reels, saved posts, multilingual speech and frames. Playwright login, Obscura browsing, local analysis.`
- Homepage after deployment: `https://votsie.github.io/instagram-obscura-mcp/`
- Topics: `instagram`, `mcp`, `mcp-server`, `model-context-protocol`, `reels`, `obscura`, `playwright`, `whisper`, `speech-to-text`, `multilingual`, `ai-agents`, `python`.
- Default branch: `main`. Default documentation language: English. License: MIT.

## Review order

1. Review the staged file list and independent sanitization report. No account runtime, private media or original Git history may enter the repository.
2. Confirm unit tests, clean wheel installation, public document checks and desktop/mobile site inspection.
3. Approve the proposed initial commit, public repository creation and push.
4. Set repository description/topics. Enable private vulnerability reporting if available.
5. Enable GitHub Pages with GitHub Actions and run `Publish project pages` manually. Verify both locales, assets, canonical URLs and sitemap after deployment.
6. Upload `docs/assets/hero.png` as a repository social preview using GitHub's repository settings if desired. There is no invented automatic REST endpoint for this setting.

The site is fully static, with no analytics, tracking, remote fonts or JavaScript bundle. It uses a lossless WebP hero for the page, PNG for social metadata, descriptive alternatives, localized URLs, reciprocal hreflang, canonical links, a sitemap, robots.txt and matching SoftwareSourceCode JSON-LD.

PyPI/MCP Registry publication, submissions to community directories and outreach are separate actions and are not claimed here. Do not create fake stars, downloads, reviews or compatibility badges.
