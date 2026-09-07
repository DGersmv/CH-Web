# Вложения в чате умника — что получает умник

Входящий API умника (чтение/правка сделок): [umnik-crm-api.md](umnik-crm-api.md).
Бот диспетчерской: [telegram-bot.md](telegram-bot.md).

CRM шлёт POST на `${UMNIK_URL}/crm/chat`. В теле — поле `attachments` (список).
Раньше там были только метаданные и container-путь, недоступный умнику с другой
машины. Теперь по каждому вложению приходит:

```json
{
  "id": 42,
  "name": "4МД Денис Орехово В1.pdf",
  "mime": "application/pdf",
  "size": 1834221,
  "is_image": false,
  "is_pdf": true,
  "path": "/app/crm_files/umnik_chat/7/20260902_101500__4МД...pdf",
  "url": "/api/umnik/chat-attachments/42/",
  "download_url": "http://192.168.1.10:8000/api/umnik/chat-attachments/42/",
  "shared_path": "D:\\CH-CRM\\crm_files\\umnik_chat\\7\\20260902_101500__4МД...pdf",
  "content_b64": "JVBERi0xLjQK...",   // только если файл <= UMNIK_CHAT_INLINE_MAX_MB
  "encoding": "base64"
}
```

## Как умнику получить файл

1. **Вариант B (общая папка).** Если задан `UMNIK_SHARED_ROOT`, в каждом вложении
   приходит `shared_path` — путь к тому же файлу глазами машины умника (UNC
   `\\SERVER\CH-CRM\crm_files\...` или подключённый сетевой диск). Открывать
   напрямую, без скачивания и base64.
2. Если есть `content_b64` — декодировать base64 и работать с байтами напрямую
   (PDF → текст/страницы, изображение → vision).
3. Иначе — скачать `download_url` с заголовком `Authorization: Bearer <UMNIK_TOKEN>`
   (тот же токен, что и для остальных `/api/umnik/*`). Эндпоинт отдаёт файл как
   attachment с правильным `Content-Type`.

`path` оставлен для обратной совместимости — container-путь CRM, умнику недоступен.

## Настройки CRM (.env)

- `UMNIK_SHARED_ROOT` — папка вложений чата (== `CRM_FILES_ROOT`) глазами машины
  умника. На том же компьютере — `D:\CH-CRM\crm_files`. На другом — UNC/сетевой диск.
- `UMNIK_CRM_BASE_URL` — базовый URL CRM, видимый с машины умника (для `download_url`).
- `UMNIK_CHAT_INLINE_MAX_MB` — порог для inline-base64 (по умолчанию 15).

## Ответ умника с файлами

Без изменений: умник может вернуть `attachments` — список путей в разрешённых
корнях (`D:\Общая_Рабочая`, `D:\Scan_Pdf`, `D:\CH-CRM\crm_files`), CRM сам
скопирует их в папку чата.
