# Compatibility and limitations

- Experimental, unofficial Instagram web integration. Instagram can change page data and UI.
- Windows is the platform with real-engine validation. Other platforms require an appropriate Obscura binary and their own compatibility checks; CI unit tests do not prove a live account works there.
- Live development checks exercised login handoff, account identification, saved links, post metadata, a carousel image and a complete Reel with local speech/frame analysis. Public tests use synthetic fixtures only.
- Real Direct sends, publishing, follows, likes and deletions were not performed as release tests. They use UI primitives and may be unsupported for a specific interface.
- Saved lists reflect currently loaded content, not a guaranteed full export. A first displayed item is not an independent proof of save chronology.
- Some Instagram GraphQL operations returned error 1357054 during development. Unsupported operations report errors; there is no silent backend switch.
- A narrow missing ServiceWorkerRegistration type shim helps Instagram feature detection in Obscura; it does not emulate working service workers.
- Reels are bounded to 200 MiB. Analysis uses sampled frames and can miss brief actions; extract additional frames locally when needed.
- Speech quality varies by model, language and recording. There is no universal-language guarantee or bundled translation model.
- Profiles and completed analysis artifacts persist locally. They are not automatically purged.
- This repository is not an official Meta product and does not bundle an Instagram Graph API integration.
