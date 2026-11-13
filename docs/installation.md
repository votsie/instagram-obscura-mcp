# Installation

[Русский](ru/installation.md) · [Overview](../README.md)

## Requirements and source install

Use Python 3.12+, Google Chrome, FFmpeg and ffprobe. Chrome is used only for the visible manual login. Speech requires the analysis extra and a local multilingual Whisper model. The setup downloader uses **aria2c**; install it with your OS package manager. The automatic Obscura installer currently targets Windows x86-64. Other platforms need their appropriate upstream binary and separate verification.

```sh
git clone https://github.com/votsie/instagram-obscura-mcp.git
cd instagram-obscura-mcp
python -m venv .venv
```

Activate `.venv`: `.venv\Scripts\Activate.ps1` in PowerShell, or `source .venv/bin/activate` in a Unix shell. Then:

```sh
python -m pip install ".[analysis]"
instagram-mcp-setup --obscura --model
instagram-mcp-doctor
```

`--obscura` and `--model` can be run separately. The model is about 484 MB and the Windows browser archive about 69 MB. Setup uses up to 16 connections for large files and checks expected size and SHA-256 before accepting them. Metadata files are downloaded concurrently by Hugging Face's client. Hosts may limit connections; aria2c manages its native transfer pipeline. No custom segmented downloader is included.

Obscura is pinned to v0.2.6; multilingual `Systran/faster-whisper-small` is pinned to revision `536b0662742c02347bc0e980a01041f333bce120`. The exact URLs, sizes and SHA-256 values live in `src/instagram_mcp/bootstrap.py`. These downloads occur only on explicit setup. Models and binaries are not distributed in the package.

## Reuse an existing installation

Set absolute paths before starting the MCP host:

```powershell
$env:INSTAGRAM_OBSCURA_BINARY = 'C:/tools/obscura/obscura.exe'
$env:INSTAGRAM_WHISPER_MODEL = 'C:/models/faster-whisper-small'
instagram-mcp-doctor
```

```sh
export INSTAGRAM_OBSCURA_BINARY=/opt/obscura/obscura
export INSTAGRAM_WHISPER_MODEL=/opt/models/faster-whisper-small
instagram-mcp-doctor
```

Use a local converted faster-whisper model directory with model.bin and its tokenizer/config files. English-only `.en` models are unsuitable for multilingual analysis. The analyzer also checks the actual model's multilingual capability.

## Settings

| Environment variable | Default / meaning |
| --- | --- |
| `INSTAGRAM_MCP_HOME` | Private data root: `%LOCALAPPDATA%/instagram-obscura-mcp` on Windows; `$XDG_DATA_HOME/instagram-obscura-mcp` or `~/.local/share/instagram-obscura-mcp` elsewhere |
| `INSTAGRAM_OBSCURA_BINARY` | `<data-root>/obscura/obscura.exe` on Windows, `obscura` elsewhere |
| `INSTAGRAM_WHISPER_MODEL` | `<data-root>/models/whisper-small` |
| `INSTAGRAM_ALLOW_FILE_ACCESS` | `false`; explicit `true` enables uploads and Obscura's broader file:// access |

The data root holds `profile`, `jobs`, `uploads` and optional runtime/model files. Keep it private and outside the checkout. Do not copy another person's profile or commit this data.

## Connect an MCP client

See [JSON examples](../examples/) and the README. Use the absolute `instagram-mcp` executable from the installed venv; Windows uses `Scripts/instagram-mcp.exe`, Unix uses `bin/instagram-mcp`. Environment variables must be inherited by the MCP server or included in the client's server configuration. Restart the client if it has not refreshed the tool catalog.

Codex example after activating the venv:

```sh
codex mcp add instagram -- /absolute/path/to/.venv/bin/instagram-mcp
```

Generic clients that support `mcpServers` can use the README JSON. Client configuration formats differ; do not paste the generic object into a TOML-only client.

## Login and failures

Run health → login_start → manually complete login/2FA → login_finish → account_info. `login_status` readiness is not proof of a successful Obscura session; account_info performs that verification. If Instagram is still showing “save login” or a challenge, finish it in the visible login window.

Doctor reports local dependencies only and does not authenticate or access Instagram. It does not currently detect Chrome availability; if login fails, install Google Chrome and retry login_start. Missing model or recognition failure is an error, not silence. CAPTCHA or an unsupported Instagram feature is reported without silently switching engines.

## Optional file attachments

Read [security](security.md) first. Set `INSTAGRAM_ALLOW_FILE_ACCESS=true` only if you accept the engine's file:// capability. Place specifically requested media inside `<data-root>/uploads`, obtain a fresh file-input reference, then use upload with expected_account. File selection is not publication.

The upload directory is not created or permission-hardened automatically. Create `<data-root>/uploads` yourself and restrict its permissions to your user before staging media.
