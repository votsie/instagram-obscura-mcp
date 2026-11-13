# Tool reference / Инструменты

The live MCP JSON schema is authoritative. English tool names are stable across content languages. / Точная схема параметров доступна через MCP.

## Read and orient / Чтение и навигация

| Tool | Purpose / Назначение |
| --- | --- |
| `instagram_health` | Local dependencies and capabilities / Зависимости и возможности |
| `instagram_guide` | overview, auth, reels, actions / Справка по сценарию |
| `instagram_account_info` | Verified current account, no cookies / Проверка аккаунта без cookies |
| `instagram_read_post` | url → caption, owner, slide metadata / Подпись и слайды |
| `instagram_post_image` | url, slide → image / Изображение слайда |
| `instagram_saved_list` | account, limit, offset → loaded links / Загруженные сохранённые ссылки |

## Manual login / Ручной вход

| Tool | Purpose / Назначение |
| --- | --- |
| `instagram_login_start` | Open visible login / Открыть окно входа |
| `instagram_login_status` | Read handoff readiness / Готовность входа |
| `instagram_login_finish` | Transfer state and close Playwright / Передать сессию |
| `instagram_login_cancel` | Close login window / Закрыть окно |

## Reel jobs / Задания Reels

| Tool | Purpose / Назначение |
| --- | --- |
| `instagram_reel_start` | url, frames, language, refresh → job_id / Начать |
| `instagram_reel_status` | job_id → job state / Состояние |
| `instagram_reel_cancel` | job_id → cancellation / Отменить |
| `instagram_reel_artifact` | job_id, name → text/image / Получить результат |

## Observed UI / Работа с интерфейсом

| Tool | Purpose / Назначение |
| --- | --- |
| `instagram_open` | Instagram URL → observed UI / Открыть страницу |
| `instagram_snapshot` | Fresh refs and text / Свежие элементы и текст |
| `instagram_screenshot` | Current viewport / Снимок экрана |
| `instagram_click` | ref, expected_account / Нажать |
| `instagram_fill` | ref, text, expected_account / Заполнить |
| `instagram_press` | ref, key, expected_account / Клавиша |
| `instagram_scroll` | direction, expected_account / Прокрутить |
| `instagram_upload` | ref, files, expected_account / Прикрепить |

## Reel workflow / Разбор Reel

`reel_start(url)` → `reel_status(job_id)` → `reel_artifact(job_id, "transcript.txt")`, `manifest.json`, `contact.jpg`, `frame_NNN.jpg`.

Omit language to auto-detect. Original-language speech is preserved; the host explains in the requested language. Completed cache entries are integrity-checked. Poll at reasonable intervals; use refresh only when required. Missing audio, no speech and failure are distinct outcomes.

Не задавайте language без необходимости. Просматривайте кадры, сверяйте имена и числа, отличайте речь от видимого и выводов. Разбор и перевод выполняет ИИ-клиент.

## Actions / Действия

Use a fresh snapshot before each action. The account must be verifiable and match expected_account. Click/fill/press/upload are potentially destructive host actions. Upload paths must be inside the private uploads folder; file access must be explicitly enabled. A successful primitive does not prove Instagram accepted a send or publication.

Свежие refs обязательны. Проверяйте нужный аккаунт и видимый результат. Не повторяйте неизвестный результат отправки вслепую. Пароли и OTP через fill запрещены.

[Machine-readable tool schemas / JSON-схемы](tools.json) are exported from the actual MCP catalog.
