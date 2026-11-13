# Languages

Documentation is available in English and Russian. Content processing is not limited to those languages.

| Layer | Behavior |
| --- | --- |
| Captions and posts | Unicode text is preserved in its original language |
| Speech | Local multilingual Whisper; auto-detection when language is omitted |
| Explicit speech language | Use a language code supported by the installed multilingual model |
| Transcript | Original-language transcription, not automatic English translation |
| Frames and on-screen text | The host assistant inspects images; this server has no dedicated OCR engine |
| Explanation and translation | Ask your assistant in the language you prefer; quality depends on that host model |

Use a multilingual model such as `small`; English-only `.en` models cannot meet this project's multilingual workflow. Models and speech recognition have uneven language coverage and accuracy. Dialects, code-switching, rare languages, music, overlapping voices and short clips can be difficult. Auto-detection is not guaranteed to correctly segment every language switch. Correct names and numbers against frames/audio when accuracy matters.

Do not label unsupported language, failed recognition or missing models as silence. `no_audio` and `no_speech` describe different outcomes.

Examples: “Analyze this Reel in Spanish and explain it in English”; «Разбери японскую речь и объясни по-русски»; “Summarize the Arabic captions and compare them with what is visible.” These are workflow examples, not claims of live validation in every language.

Русский: язык документации не ограничивает язык контента. Речь распознаётся многоязычной моделью с автоопределением или явным кодом языка. Транскрипт сохраняется в оригинале; перевод и разбор выполняет ИИ-клиент. Поддержка буквально каждого языка не гарантируется.
