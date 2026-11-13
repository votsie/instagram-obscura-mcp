# Analytics and measurement

[Русский](ru/analytics.md) · [GitHub repository insights](https://github.com/votsie/instagram-obscura-mcp/graphs/traffic)

## Website

The public project website uses [Cloudflare Web Analytics](https://developers.cloudflare.com/web-analytics/) for page views, visits, sources and page performance. Sign in to the Cloudflare dashboard and open **Web Analytics**, then choose the `votsie.github.io` site. Results can take time to appear after a visit.

The local loader requests Cloudflare's official beacon only on HTTPS pages hosted at `votsie.github.io` under `/instagram-obscura-mcp/`. It does not run on localhost, another domain, another GitHub Pages project, or if a visitor enables Global Privacy Control or Do Not Track. The site still works if JavaScript or the beacon is blocked. Browser extensions, network failures and privacy settings may prevent a visit from being counted.

Cloudflare reports page and referrer dimensions and browser performance. Cloudflare states that Web Analytics does not log query strings, does not support UTM parameters or custom click events, and retains reporting data for the previous six months. Do not interpret page views as button clicks or downloads. See [Cloudflare's FAQ](https://developers.cloudflare.com/web-analytics/faq/) and [data collection](https://developers.cloudflare.com/web-analytics/data-metrics/data-origin-and-collection/).

The page beacon does not run inside the Instagram MCP server. It is not used to collect Instagram passwords, cookies, account state, post content, saved lists or Reel transcripts. The public site token identifies the website to Cloudflare; it is not an API credential.

## GitHub activity

Repository [Traffic](https://github.com/votsie/instagram-obscura-mcp/graphs/traffic) shows views, unique visitors, full clones, referrers and popular content for the most recent 14 days, subject to GitHub's reporting rules and update delay. A full clone is not a fetch or an installation; don't sum daily unique counts as if they were unique users for a longer period. Stars, forks, issues and pull requests are separately visible on the repository and Insights pages.

This repository does not currently archive GitHub traffic history. Long-term archival requires separate storage and a least-privilege credential with access to the traffic API. Never put a personal access token or `gh` login token in public source or a public traffic report.

## Search visibility

[Google Search Console](https://search.google.com/search-console/) reports search impressions, clicks, indexed pages and sitemap status for a verified property. Verification and sitemap submission must be completed in the operator's account; the presence of a verification file in source alone is not proof that Google verified or indexed the site. Search metrics and website visits measure different things and have different reporting delays.

For release testing, use synthetic visits or Cloudflare's provider test facilities only. Explain test traffic before comparing the first reporting period; don't label it as an external audience. See [Cloudflare's official setup guide](https://developers.cloudflare.com/web-analytics/get-started/).
