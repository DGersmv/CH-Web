"""Расшифровка голосовых сообщений в текст (speech-to-text).

Два движка, выбор через ``SPEECH_TO_TEXT_BACKEND``:

* ``local`` (по умолчанию) — faster-whisper прямо в контейнере. Бесплатно, без
  ключей и прокси. Модель (``SPEECH_TO_TEXT_LOCAL_MODEL``, по умолчанию ``small``)
  один раз скачивается с HuggingFace и кэшируется. ``small`` уверенно понимает
  русский на CPU; ``base`` быстрее и легче, ``medium`` точнее и тяжелее.
* ``api`` — любой OpenAI-совместимый эндпоинт ``/audio/transcriptions``
  (сам OpenAI ``whisper-1``, Groq ``whisper-large-v3``, локальный whisper.cpp-сервер).
  Включается, если задан ``SPEECH_TO_TEXT_URL``.

Сбои — TranscribeError. Вызывающий код не должен слать умнику «немой» ogg:
умник читает только текст вопроса.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import tempfile
import urllib.error
import urllib.request
import uuid

from django.conf import settings

log = logging.getLogger('deals.telegram')

_LOCAL_BACKENDS = {'local', 'faster-whisper', 'faster_whisper', 'whisper'}


class TranscribeError(RuntimeError):
    pass


def _backend() -> str:
    value = (getattr(settings, 'SPEECH_TO_TEXT_BACKEND', '') or 'local').strip().lower()
    return value or 'local'


def is_configured() -> bool:
    if _backend() in _LOCAL_BACKENDS:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True
    return bool((getattr(settings, 'SPEECH_TO_TEXT_URL', '') or '').strip())


def is_local_backend() -> bool:
    return _backend() in _LOCAL_BACKENDS


def local_model_loaded() -> bool:
    return _local_model is not None


def _apply_hf_proxy():
    """HuggingFace качает модель через HTTPS — на этой сети нужен тот же прокси, что у Telegram."""
    proxy = (getattr(settings, 'SPEECH_TO_TEXT_PROXY', '') or '').strip()
    if not proxy:
        return
    os.environ.setdefault('HTTP_PROXY', proxy)
    os.environ.setdefault('HTTPS_PROXY', proxy)
    extra = 'db,redis,localhost,127.0.0.1,host.docker.internal'
    current = os.environ.get('NO_PROXY') or os.environ.get('no_proxy') or ''
    parts = {p.strip() for p in current.split(',') if p.strip()}
    parts.update(extra.split(','))
    joined = ','.join(sorted(parts))
    os.environ['NO_PROXY'] = joined
    os.environ['no_proxy'] = joined


def _audio_suffix(filename: str, mime: str) -> str:
    low = (filename or '').lower()
    for ext in ('.ogg', '.oga', '.opus', '.mp3', '.m4a', '.wav', '.webm', '.mp4', '.flac', '.aac'):
        if low.endswith(ext):
            return ext
    mime_l = (mime or '').lower()
    if 'mpeg' in mime_l or 'mp3' in mime_l:
        return '.mp3'
    if 'mp4' in mime_l or mime_l.startswith('video/'):
        return '.mp4'
    return '.ogg'


# --------------------------------------------------------------------------- local

_local_model = None
_local_model_key: tuple | None = None


def _get_local_model():
    global _local_model, _local_model_key
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise TranscribeError('faster-whisper не установлен (pip install faster-whisper)') from exc

    name = (getattr(settings, 'SPEECH_TO_TEXT_LOCAL_MODEL', '') or 'small').strip()
    device = (getattr(settings, 'SPEECH_TO_TEXT_DEVICE', '') or 'cpu').strip()
    compute = (getattr(settings, 'SPEECH_TO_TEXT_COMPUTE', '') or 'int8').strip()
    key = (name, device, compute)
    if _local_model is None or _local_model_key != key:
        log.info('faster-whisper: загружаю модель %s (%s/%s)', name, device, compute)
        _apply_hf_proxy()
        try:
            _local_model = WhisperModel(name, device=device, compute_type=compute)
        except Exception as exc:  # noqa: BLE001 - сеть/диск HuggingFace
            raise TranscribeError(f'не удалось загрузить модель {name}: {exc}') from exc
        _local_model_key = key
        log.info('faster-whisper: модель %s готова', name)
    return _local_model


def _transcribe_local(data: bytes, language: str, *, filename: str, mime: str) -> str:
    model = _get_local_model()
    suffix = _audio_suffix(filename, mime)
    tmp_path = ''
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        segments, _info = model.transcribe(
            tmp_path,
            language=language or None,
            vad_filter=True,
        )
        return ' '.join(seg.text.strip() for seg in segments if seg.text).strip()
    except TranscribeError:
        raise
    except Exception as exc:  # noqa: BLE001 - PyAV/CTranslate2 кидают что угодно
        raise TranscribeError(f'faster-whisper: {exc}') from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# --------------------------------------------------------------------------- api

def _opener():
    proxy = (getattr(settings, 'SPEECH_TO_TEXT_PROXY', '') or '').strip()
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
        )
    return urllib.request.build_opener()


def _transcribe_api(data: bytes, *, filename: str, mime: str, language: str) -> str:
    url = (getattr(settings, 'SPEECH_TO_TEXT_URL', '') or '').strip()
    if not url:
        return ''

    key = (getattr(settings, 'SPEECH_TO_TEXT_KEY', '') or '').strip()
    model = (getattr(settings, 'SPEECH_TO_TEXT_MODEL', '') or 'whisper-1').strip()
    timeout = float(getattr(settings, 'SPEECH_TO_TEXT_TIMEOUT', 120) or 120)

    name = (filename or 'audio.ogg').replace('"', '').replace('\r', '').replace('\n', '')
    content_type = mime or mimetypes.guess_type(name)[0] or 'application/octet-stream'

    fields = {'model': model, 'response_format': 'json'}
    if language:
        fields['language'] = language

    boundary = '----crmstt' + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key_name, value in fields.items():
        chunks.append(
            (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="{key_name}"\r\n\r\n{value}\r\n'
            ).encode('utf-8')
        )
    ascii_name = name.encode('ascii', 'replace').decode('ascii') or 'audio.ogg'
    chunks.append(
        (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="{ascii_name}"\r\n'
            f'Content-Type: {content_type}\r\n\r\n'
        ).encode('utf-8')
    )
    chunks.append(data + b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode('ascii'))
    body = b''.join(chunks)

    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')

    try:
        with _opener().open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8')[:300]
        except Exception:  # noqa: BLE001 - тело ошибки не обязательно читается
            pass
        raise TranscribeError(f'HTTP {exc.code}: {detail}'.strip()) from exc
    except urllib.error.URLError as exc:
        raise TranscribeError(str(exc.reason)) from exc
    except (TimeoutError, ValueError) as exc:
        raise TranscribeError(str(exc)) from exc

    if isinstance(payload, dict):
        return (payload.get('text') or '').strip()
    return ''


# --------------------------------------------------------------------------- entry

def transcribe(data: bytes, *, filename: str = 'audio.ogg', mime: str = 'audio/ogg') -> str:
    """Байты аудио -> распознанный текст ('' если STT не настроен или ответ пустой)."""
    if not data:
        return ''

    max_mb = float(getattr(settings, 'SPEECH_TO_TEXT_MAX_MB', 25) or 25)
    if len(data) > max_mb * 1024 * 1024:
        raise TranscribeError(f'аудио больше {max_mb:g} МБ — расшифровку пропускаю')

    language = (getattr(settings, 'SPEECH_TO_TEXT_LANGUAGE', '') or '').strip()

    if _backend() in _LOCAL_BACKENDS:
        return _transcribe_local(data, language, filename=filename, mime=mime)
    return _transcribe_api(data, filename=filename, mime=mime, language=language)
