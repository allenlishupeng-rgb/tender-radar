"""Host-scoped TLS interoperability without disabling certificate validation."""
import ssl

from requests.adapters import HTTPAdapter


class P256Adapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ecdh_curve('prime256v1')
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)


def configure_public_session(session):
    # This official host rejects the default curve negotiation. Keep hostname
    # and certificate checks enabled; do not apply to unrelated hosts.
    session.mount('https://hnsggzyjy.henan.gov.cn/', P256Adapter())
    return session
