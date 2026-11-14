# Accessibility

[Русский](docs/ru/accessibility.md)

We aim to make Instagram Obscura MCP and its documentation usable by people with different abilities and assistive technologies. This is an evolving project; no formal WCAG conformance or screen-reader certification is claimed.

## Supported surfaces

- The public English and Russian website uses semantic headings, a skip link, native links and expandable sections, visible keyboard focus, descriptive image alternatives, responsive layouts and reduced-motion preferences.
- MCP tools return structured data and text transcripts where applicable. Speech transcripts are preserved in the original language; the host assistant can explain or translate them.
- Markdown documentation and setup commands can be read without running the website's optional analytics script.
- Website layouts were checked at 390px and 1440px widths. This does not replace an assistive-technology audit.

## Known limitations

- Reel frames, screenshots and contact sheets are visual evidence. A speech transcript is not an equivalent description of all visual events; useful image descriptions depend on the connected assistant.
- There is no dedicated OCR or audio-description engine. Transcription accuracy varies by language, model and recording.
- Instagram, manual login/2FA, Obscura rendering and the MCP host have their own accessibility constraints. This project cannot certify those third-party interfaces.
- The website currently uses a dark theme. Some brand artwork and architecture diagrams contain English text even on Russian pages.
- Keyboard-only, screen-reader and high-zoom coverage is not yet comprehensive.

## Report a barrier

Open an [accessibility issue](https://github.com/votsie/instagram-obscura-mcp/issues/new?template=bug.yml) with the affected page/tool, expected and actual behavior, OS/browser or MCP host, assistive technology and steps to reproduce. Synthetic examples are preferred. Do not attach account cookies, private Instagram content, credentials or unredacted screenshots.

For a private report, email [the maintainer](mailto:aafeklisto@gmail.com). Reports will be reviewed and prioritized by impact and feasibility; no response-time SLA is promised. Contributions that improve accessibility are welcome under [CONTRIBUTING.md](CONTRIBUTING.md).
