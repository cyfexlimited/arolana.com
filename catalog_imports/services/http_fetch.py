import ipaddress
import os
import socket
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
REDIRECT_CODES = {301, 302, 303, 307, 308}


class UnsafeURL(ValueError):
    pass


class FetchBlocked(RuntimeError):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    text: str


@dataclass
class BinaryFetchResult:
    url: str
    status: int
    content_type: str
    data: bytes


def _configured_ca_bundle() -> str:
    """Return an explicitly configured CA bundle path when available."""
    env_path = str(os.environ.get("CATALOG_IMPORTS_CA_BUNDLE", "") or "").strip()
    if env_path:
        return env_path

    try:
        from django.conf import settings

        settings_path = str(getattr(settings, "CATALOG_IMPORTS_CA_BUNDLE", "") or "").strip()
        if settings_path:
            return settings_path
    except Exception:
        # The service is also imported in isolated unit tests before Django is configured.
        pass

    return ""


def _build_ssl_context() -> ssl.SSLContext:
    """
    Build a certificate-verifying TLS context.

    macOS framework Python installations can have an empty/incomplete OpenSSL
    trust store even though the browser trusts the site. Prefer an explicitly
    configured CA bundle, then certifi's Mozilla CA bundle, and finally the
    operating-system/Python defaults. Verification is never disabled.
    """
    ca_bundle = _configured_ca_bundle()
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        return ssl.create_default_context()


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("Only public http/https product URLs are allowed.")
    host = parsed.hostname
    try:
        addresses = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise FetchBlocked(f"Could not resolve source hostname: {host}") from exc
    for info in addresses:
        address = info[4][0]
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeURL(
                "Private, loopback, link-local, reserved, and internal source addresses are blocked."
            )


class ControlledRedirectHandler(HTTPRedirectHandler):
    """Disable urllib auto-follow so redirect policy is enforced explicitly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _redirect_target(current_url: str, status: int, headers) -> str:
    location = ""
    if headers is not None:
        location = str(headers.get("Location") or headers.get("URI") or "").strip()

    if not location:
        raise FetchBlocked(
            f"Source returned HTTP {status} without a redirect target."
        )

    target = urljoin(current_url, location)
    _validate_public_url(target)

    current = urlparse(current_url)
    redirected = urlparse(target)
    if current.scheme == "https" and redirected.scheme != "https":
        raise FetchBlocked("Unsafe HTTPS-to-HTTP source redirect was blocked.")

    return target


def _make_request(url: str, user_agent: str) -> Request:
    return Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "en-NG,en;q=0.8",
        },
    )


def fetch_html(
    url: str,
    *,
    timeout: int = 12,
    max_bytes: int = MAX_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    user_agent: str = "ArolanaProductImporter/2.2 (+https://arolana.com)",
) -> FetchResult:
    _validate_public_url(url)

    # Redirects are intentionally handled by our loop instead of urllib so
    # every hop is revalidated and redirect loops/downgrades can be blocked.
    opener = build_opener(
        ControlledRedirectHandler(),
        HTTPSHandler(context=_build_ssl_context()),
    )

    current_url = url
    visited = {current_url}

    for redirect_count in range(max_redirects + 1):
        request = _make_request(current_url, user_agent)

        try:
            with opener.open(request, timeout=timeout) as response:
                final_url = response.geturl() or current_url
                _validate_public_url(final_url)
                content_type = response.headers.get_content_type() or ""
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise FetchBlocked(
                        f"Unsupported source content type: {content_type or 'unknown'}"
                    )
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise FetchBlocked("Source page exceeded the 5 MB safety limit.")
                charset = response.headers.get_content_charset() or "utf-8"
                return FetchResult(
                    url=final_url,
                    status=getattr(response, "status", 200),
                    content_type=content_type,
                    text=raw.decode(charset, errors="replace"),
                )

        except HTTPError as exc:
            if exc.code in REDIRECT_CODES:
                if redirect_count >= max_redirects:
                    raise FetchBlocked(
                        f"Source exceeded the {max_redirects}-redirect safety limit."
                    ) from exc

                target = _redirect_target(current_url, exc.code, exc.headers)
                if target in visited:
                    raise FetchBlocked("Source redirect loop detected and blocked.") from exc

                visited.add(target)
                current_url = target
                try:
                    exc.close()
                except Exception:
                    pass
                continue

            if exc.code in {401, 403, 429}:
                raise FetchBlocked(
                    f"Source website refused automated access (HTTP {exc.code}). "
                    "Use an allowed API/feed or another permitted source method."
                ) from exc

            raise FetchBlocked(f"Source returned HTTP {exc.code}.") from exc

        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise FetchBlocked(
                    "TLS certificate verification failed while connecting to the source. "
                    "The importer kept SSL verification enabled. Check the local/server CA bundle."
                ) from exc
            raise FetchBlocked(f"Could not fetch source page: {reason}") from exc

    raise FetchBlocked("Source redirect handling stopped unexpectedly.")



def fetch_binary(
    url: str,
    *,
    timeout: int = 12,
    max_bytes: int = 15 * 1024 * 1024,
    max_redirects: int = MAX_REDIRECTS,
    user_agent: str = "ArolanaProductImporter/4.2 (+https://arolana.com)",
    allowed_content_types=None,
    accept_header=None,
) -> BinaryFetchResult:
    """Fetch a bounded binary public resource with the same SSRF/TLS/redirect policy.

    This is used only for official manufacturer documents such as datasheets.
    Certificate verification remains enabled and every redirect hop is validated.
    """
    _validate_public_url(url)
    allowed = set(allowed_content_types or {"application/pdf"})
    opener = build_opener(
        ControlledRedirectHandler(),
        HTTPSHandler(context=_build_ssl_context()),
    )
    current_url = url
    visited = {current_url}

    for redirect_count in range(max_redirects + 1):
        request = Request(
            current_url,
            headers={
                "User-Agent": user_agent,
                "Accept": accept_header or "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
                "Accept-Language": "en-NG,en;q=0.8",
            },
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                final_url = response.geturl() or current_url
                _validate_public_url(final_url)
                content_type = response.headers.get_content_type() or ""
                if content_type not in allowed:
                    raise FetchBlocked(
                        f"Unsupported official-document content type: {content_type or 'unknown'}"
                    )
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise FetchBlocked("Official manufacturer document exceeded the safety size limit.")
                return BinaryFetchResult(
                    url=final_url,
                    status=getattr(response, "status", 200),
                    content_type=content_type,
                    data=raw,
                )
        except HTTPError as exc:
            if exc.code in REDIRECT_CODES:
                if redirect_count >= max_redirects:
                    raise FetchBlocked(
                        f"Source exceeded the {max_redirects}-redirect safety limit."
                    ) from exc
                target = _redirect_target(current_url, exc.code, exc.headers)
                if target in visited:
                    raise FetchBlocked("Source redirect loop detected and blocked.") from exc
                visited.add(target)
                current_url = target
                try:
                    exc.close()
                except Exception:
                    pass
                continue
            if exc.code in {401, 403, 429}:
                raise FetchBlocked(
                    f"Official manufacturer document refused automated access (HTTP {exc.code})."
                ) from exc
            raise FetchBlocked(f"Official manufacturer document returned HTTP {exc.code}.") from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise FetchBlocked(
                    "TLS certificate verification failed while fetching the official manufacturer document."
                ) from exc
            raise FetchBlocked(f"Could not fetch official manufacturer document: {reason}") from exc

    raise FetchBlocked("Official manufacturer document redirect handling stopped unexpectedly.")
