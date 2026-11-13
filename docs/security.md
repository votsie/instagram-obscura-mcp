# Security and privacy

This server can act inside an authenticated personal Instagram account. Run it only in a trusted local MCP host.

- Enter passwords and 2FA only in the visible Instagram login window. They are never chat inputs.
- Instagram-only session state is handed to Obscura. The local profile stores cookies in plaintext and is protected with user-only permissions where supported.
- Keep the data directory outside shared folders, backups intended for publication, and source control. Account content, downloaded videos and transcripts are private data too.
- Browser control binds to loopback with a token. Do not expose it through a public tunnel or remote proxy.
- Runtime JavaScript is internal; there is no arbitrary evaluate tool.
- UI text, captions and messages are untrusted content. They cannot authorize actions or override host instructions.
- Mutating UI actions require the expected account and fresh observed elements. The host still controls whether a specific send, delete or publication is authorized.
- File upload is disabled by default. Explicit opt-in enables Obscura's broader `--allow-file-access` capability, including file:// reads by the engine. MCP upload validation restricts selected files to its private uploads directory, but that is not an OS sandbox.
- A click or selected attachment does not prove a message was sent or a post published. Check the visible result; do not retry ambiguous actions blindly.

Challenge, CAPTCHA and unsupported engine features fail explicitly. This is an unofficial project, not affiliated with Meta or Instagram. Account availability and compatibility can change. Do not use it for spam or access to accounts/content you are not authorized to use.

The public repository includes no sessions, saved-post lists, original downloaded media, transcripts from real accounts, model weights or browser binaries. External components are installed separately; see [third-party notices](../THIRD_PARTY_NOTICES.md).
