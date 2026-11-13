# Установка

[English](../installation.md) · [Обзор](../../README.ru.md)

Нужны Python 3.12+, Google Chrome, FFmpeg/ffprobe и aria2c. Chrome используется только для видимого ручного входа. Речь требует зависимостей analysis и локальной многоязычной Whisper. Автоустановка Obscura сейчас рассчитана на Windows x86-64; для других ОС нужен подходящий бинарник и отдельная проверка.

```sh
git clone https://github.com/votsie/instagram-obscura-mcp.git
cd instagram-obscura-mcp
python -m venv .venv
```

Активируйте `.venv\Scripts\Activate.ps1` в PowerShell или `source .venv/bin/activate` в Unix.

```sh
python -m pip install ".[analysis]"
instagram-mcp-setup --obscura --model
instagram-mcp-doctor
```

Можно установить только `--obscura` или `--model`. Архив Windows около 69 МБ, модель около 484 МБ. Крупные файлы скачиваются aria2c с 16 соединениями и проверкой размера и SHA-256; небольшие файлы модели — параллельно штатным клиентом Hugging Face. Серверы могут ограничивать соединения. Загрузки выполняются явно при установке, а не при первом MCP-вызове.

Закреплены Obscura v0.2.6 и Systran/faster-whisper-small revision `536b0662742c02347bc0e980a01041f333bce120`. Точные URL, размеры и контрольные суммы — в `src/instagram_mcp/bootstrap.py`. Бинарники и веса не включены в репозиторий.

## Свои пути

```powershell
$env:INSTAGRAM_OBSCURA_BINARY = 'C:/tools/obscura/obscura.exe'
$env:INSTAGRAM_WHISPER_MODEL = 'C:/models/faster-whisper-small'
instagram-mcp-doctor
```

В Unix задайте эти переменные через export. Папка модели должна содержать model.bin, конфигурацию и токенизатор. Модель `.en` не подходит; анализатор также проверяет реальную многоязычность модели.

| Переменная | Значение |
| --- | --- |
| `INSTAGRAM_MCP_HOME` | Каталог приватных данных; по умолчанию `%LOCALAPPDATA%/instagram-obscura-mcp` в Windows или `$XDG_DATA_HOME/instagram-obscura-mcp` / `~/.local/share/instagram-obscura-mcp` в Unix |
| `INSTAGRAM_OBSCURA_BINARY` | Путь к Obscura; по умолчанию подпапка obscura внутри каталога данных |
| `INSTAGRAM_WHISPER_MODEL` | Путь к модели; по умолчанию models/whisper-small внутри каталога данных |
| `INSTAGRAM_ALLOW_FILE_ACCESS` | По умолчанию false. Явное true разрешает прикрепление и более широкий доступ движка к file:// |

В каталоге данных сохраняются profile, jobs и uploads. Храните его приватно и вне Git. Не переносите чужой профиль.

## Подключение и вход

Укажите в MCP-клиенте абсолютный путь `.venv/Scripts/instagram-mcp.exe` для Windows или `.venv/bin/instagram-mcp` для Unix. Пример JSON — в [README](../../README.ru.md), дополнительные [конфигурации](../../examples/). Клиент должен передать переменные окружения серверу; после регистрации иногда нужен перезапуск клиента.

Для Codex: `codex mcp add instagram -- /absolute/path/to/instagram-mcp`. Форматы настроек клиентов различаются: общий JSON mcpServers не подходит для TOML-конфига.

Последовательность: health → login_start → самостоятельный вход и 2FA в открытом окне → login_finish → account_info. Готовность status не доказывает работу сессии в Obscura: это проверяет account_info. Завершите предложение сохранить вход или проверку Instagram, если они остались.

Doctor проверяет локальные зависимости без запуска браузера и сетевых запросов. Наличие Chrome пока не диагностируется: установите его отдельно при ошибке login_start. Отсутствие модели, ошибка распознавания и отсутствие речи — разные результаты. При CAPTCHA или несовместимости движок скрытно не заменяется.

Прикрепление файлов включайте только после чтения [безопасности](security.md). Файлы должны быть в `<data-root>/uploads`; нужны свежий ref и правильный expected_account. Прикрепление не публикует пост.

Папка uploads не создаётся и не защищается автоматически. Создайте `<data-root>/uploads` самостоятельно и ограничьте её права своим пользователем до размещения медиа.
