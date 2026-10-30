"""Bounded HTTPS reads with certificate verification and an official-host list."""
from dataclasses import dataclass
import os
import subprocess
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

HOSTS = {'ec.europa.eu', 'bpstat.bportugal.pt', 'data-api.ecb.europa.eu'}
LIMIT = 10 * 1024 * 1024


def check_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:
        raise ValueError('HTTPS URL on a reviewed official host required')
    if parsed.port not in (None, 443):
        raise ValueError('Unexpected port')


@dataclass(frozen=True)
class Response:
    status: int
    final_url: str
    content_type: str
    raw: bytes
    transport: str


def get(url, timeout=40):
    check_url(url)
    if os.name == 'nt':
        # Schannel uses Windows' certificate-chain building, including AIA.
        # Python/OpenSSL on some Windows installations lacks intermediates.
        # Never use -k or an unverified SSL context.
        result = subprocess.run(
            ['curl.exe', '--silent', '--show-error', '--location', '--max-redirs', '3',
             '--proto', '=https', '--proto-redir', '=https', '--max-time', str(timeout),
             '--max-filesize', str(LIMIT), '--write-out',
             '\n__GWIX_RESPONSE__%{http_code}\t%{url_effective}\t%{content_type}', url],
            capture_output=True, timeout=timeout+5, check=True)
        raw, tail = result.stdout.rsplit(b'\n__GWIX_RESPONSE__', 1)
        status, final, content = tail.decode('utf-8').split('\t', 2)
        response = Response(int(status), final, content, raw, 'curl/Windows_Schannel_TLS_verified')
    else:
        try:
            stream = urlopen(Request(url, headers={'User-Agent': 'GWI-X-official-validation/1.2'}), timeout=timeout)
        except HTTPError as exc:
            stream = exc
        with stream:
            response = Response(stream.status, stream.geturl(), stream.headers.get('Content-Type', ''),
                                stream.read(LIMIT+1), 'urllib/system_CA_TLS_verified')
    check_url(response.final_url)
    if len(response.raw) > LIMIT:
        raise ValueError('Response exceeds size limit')
    return response
