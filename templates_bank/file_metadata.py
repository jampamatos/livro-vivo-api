import hashlib
import mimetypes
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError


CONTENT_DISPOSITION_FILENAME_RE = re.compile(r'filename="?([^";]+)"?')


@dataclass(frozen=True)
class FileMetadata:
    file_name: str
    file_mime_type: str
    file_size_bytes: int
    file_sha256: str


def _normalize_mime(raw_content_type: str | None, file_name: str) -> str:
    normalized = (raw_content_type or '').split(';', 1)[0].strip().lower()
    if normalized:
        return normalized

    guessed, _encoding = mimetypes.guess_type(file_name)
    if guessed:
        return guessed.lower()

    return 'application/octet-stream'


def _extract_file_name_from_content_disposition(raw_content_disposition: str | None) -> str:
    if not raw_content_disposition:
        return ''

    match = CONTENT_DISPOSITION_FILENAME_RE.search(raw_content_disposition)
    if not match:
        return ''

    return unquote((match.group(1) or '').strip())


def _extract_file_name_from_url(file_url: str) -> str:
    parsed = urlparse(file_url)
    candidate = os.path.basename(parsed.path or '')
    return unquote(candidate).strip()


def _iter_file_chunks(file_obj, chunk_size: int = 1024 * 1024):
    if hasattr(file_obj, 'chunks'):
        yield from file_obj.chunks()
        return

    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        yield chunk


def extract_uploaded_file_metadata(uploaded_file) -> FileMetadata:
    if uploaded_file is None:
        raise ValidationError('Arquivo enviado invalido.')

    file_name = os.path.basename((getattr(uploaded_file, 'name', '') or '').strip()) or 'arquivo'
    content_type = getattr(uploaded_file, 'content_type', '')
    file_hash = hashlib.sha256()
    size = 0

    seek_position = None
    if hasattr(uploaded_file, 'tell') and hasattr(uploaded_file, 'seek'):
        try:
            seek_position = uploaded_file.tell()
            uploaded_file.seek(0)
        except Exception:
            seek_position = None

    for chunk in _iter_file_chunks(uploaded_file):
        size += len(chunk)
        file_hash.update(chunk)

    if seek_position is not None and hasattr(uploaded_file, 'seek'):
        try:
            uploaded_file.seek(seek_position)
        except Exception:
            pass

    reported_size = getattr(uploaded_file, 'size', None)
    if isinstance(reported_size, int) and reported_size >= 0:
        size = reported_size

    return FileMetadata(
        file_name=file_name,
        file_mime_type=_normalize_mime(content_type, file_name),
        file_size_bytes=size,
        file_sha256=file_hash.hexdigest(),
    )


def fetch_remote_file_metadata(
    file_url: str,
    *,
    timeout_seconds: int = 8,
    max_bytes: int = 30 * 1024 * 1024,
) -> FileMetadata:
    if not file_url:
        raise ValidationError('URL remota invalida.')

    request = Request(
        file_url,
        headers={'User-Agent': 'LivroVivoTemplatesBank/1.0'},
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            headers = response.headers
            content_disposition = headers.get('Content-Disposition', '')
            file_name = (
                _extract_file_name_from_content_disposition(content_disposition)
                or _extract_file_name_from_url(file_url)
                or 'arquivo-remoto'
            )

            declared_size = headers.get('Content-Length', '')
            if declared_size:
                try:
                    declared_size_value = int(declared_size)
                except (TypeError, ValueError):
                    declared_size_value = None
                if declared_size_value is not None and declared_size_value > max_bytes:
                    raise ValidationError('Arquivo remoto excede o limite permitido para leitura de metadados.')

            file_hash = hashlib.sha256()
            total_size = 0

            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_bytes:
                    raise ValidationError('Arquivo remoto excede o limite permitido para leitura de metadados.')
                file_hash.update(chunk)

            raw_mime = headers.get('Content-Type', '')

    except HTTPError as exc:
        raise ValidationError(f'Nao foi possivel acessar a URL remota (HTTP {exc.code}).') from exc
    except URLError as exc:
        raise ValidationError('Nao foi possivel acessar a URL remota informada.') from exc
    except TimeoutError as exc:
        raise ValidationError('Tempo limite excedido ao buscar metadados do arquivo remoto.') from exc

    return FileMetadata(
        file_name=file_name,
        file_mime_type=_normalize_mime(raw_mime, file_name),
        file_size_bytes=total_size,
        file_sha256=file_hash.hexdigest(),
    )
