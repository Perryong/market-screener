"""Regression coverage for provider TLS on Python installs without CA files."""
import io
import ssl
import urllib.error
import urllib.request
import urllib.response
from unittest.mock import patch

import pytest

from screener.shared import DataError, get_json


def test_provider_trust_available_without_system_ca_bundle(tmp_path):
    # Remove the system CA source, as on the affected macOS Python install.
    # Only the actual network exchange is replaced; inspect its real TLS policy.
    def open_request(handler, request):
        context = handler._context or ssl.create_default_context()
        assert context.cert_store_stats()['x509_ca'] > 0
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        response = urllib.response.addinfourl(io.BytesIO(b'{"price": 42}'), {}, request.full_url, 200)
        response.msg = 'OK'
        return response

    with patch.dict('os.environ', {'SSL_CERT_FILE': str(tmp_path/'missing.pem'),
                                  'SSL_CERT_DIR': str(tmp_path)}), \
         patch.object(urllib.request.HTTPSHandler, 'https_open', open_request):
        assert get_json('https://example.com/price') == {'price': 42}


def test_certificate_failure_is_specific_and_not_retried():
    failure = urllib.error.URLError(ssl.SSLCertVerificationError('private upstream detail'))
    with patch.object(urllib.request.OpenerDirector, 'open', side_effect=failure), \
         patch('screener.shared.time.sleep', side_effect=AssertionError('TLS trust is not transient')):
        with pytest.raises(DataError, match='certificate verification failed') as caught:
            get_json('https://example.com/price')
    assert 'private upstream detail' not in str(caught.value)
