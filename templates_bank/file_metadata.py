import hashlib
import ipaddress
import mimetypes
import os
import re
import socket
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.core.exceptions import ValidationError


CONTENT_DISPOSITION_FILENAME_RE = re.compile(r'filename="?([^";]+)"?')
ALLOWED_REMOTE_FILE_SCHEMES = {'http', 'https'}


def _is_public_ip(ip_value) -> bool:
    return not (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_multicast
        or ip_value.is_reserved
        or ip_value.is_unspecified
    )


def _validate_remote_file_url(file_url: str) -> None:
    parsed = urlparse(file_url or '')
    scheme = (parsed.scheme or '').strip().lower()
    host = (parsed.hostname or '').strip()

    if scheme not in ALLOWED_REMOTE_FILE_SCHEMES:
        raise ValidationError('A URL remota deve usar HTTP ou HTTPS.')
    if not host:
        raise ValidationError('A URL remota precisa informar um host valido.')
    if parsed.username or parsed.password:
        raise ValidationError('A URL remota nao pode conter credenciais embutidas.')

    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None

    if host_ip and not _is_public_ip(host_ip):
        raise ValidationError('A URL remota aponta para um endereço de rede não permitido.')

    target_port = parsed.port or (443 if scheme == 'https' else 80)
    try:
        addr_infos = socket.getaddrinfo(host, target_port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValidationError('Nao foi possivel resolver o host da URL remota.') from exc

    for addr_info in addr_infos:
        resolved_ip = ipaddress.ip_address(addr_info[4][0])
        if not _is_public_ip(resolved_ip):
            raise ValidationError('A URL remota resolve para um endereço de rede não permitido.')


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_remote_file_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_remote_url(request: Request, *, timeout_seconds: int):
    opener = build_opener(_SafeRedirectHandler())
    return opener.open(request, timeout=timeout_seconds)


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
    _validate_remote_file_url(file_url)

    request = Request(
        file_url,
        headers={'User-Agent': 'LivroVivoTemplatesBank/1.0'},
    )

    try:
        with _open_remote_url(request, timeout_seconds=timeout_seconds) as response:
            _validate_remote_file_url(response.geturl())
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
