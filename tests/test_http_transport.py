import ssl

import requests

from utils.http_transport import P256Adapter, configure_public_session


def test_tls_compatibility_is_host_scoped_and_verified():
    with requests.Session() as session:
        configure_public_session(session)
        adapter = session.get_adapter('https://hnsggzyjy.henan.gov.cn/jyxx/')
        assert isinstance(adapter, P256Adapter)
        context = adapter.poolmanager.connection_pool_kw['ssl_context']
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        assert not isinstance(session.get_adapter('https://example.com'), P256Adapter)
