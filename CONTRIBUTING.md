# Contributing

Small, focused contributions are welcome. Explain the user-visible problem, test with synthetic data, and include the command used to verify the change.

1. Fork and create a branch.
2. Use Python 3.12+ and install `python -m pip install -e ".[analysis,dev]"`.
3. Run `python -m pytest -q` and `python -m build`.
4. Update English and Russian user-facing documentation together.
5. Open a pull request with behavior, validation and limitations.

Never attach a real profile, account data, downloaded Reel, cookie file or model weights. A failing Instagram operation is not permission to add a different browser/network backend. Discuss changes to authentication and action semantics before implementation.

By contributing you agree to license your contribution under MIT. Third-party code must retain its original license and notices.

Русский: описывайте конкретную проблему, используйте синтетические данные, обновляйте обе версии документации. Не прикладывайте cookies, личную переписку, сохранённое и видео из аккаунта.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report accessibility barriers as described in [ACCESSIBILITY.md](ACCESSIBILITY.md).
