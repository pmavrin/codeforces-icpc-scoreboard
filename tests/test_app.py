import json
import socket
import unittest
from unittest.mock import MagicMock, patch

import public_http
import server


class ApplicationTests(unittest.TestCase):
    def test_environment_aliases_override_file_defaults(self):
        aliases = {'Delft University of Technology': 'TU Delft'}
        with patch.dict(server.os.environ, {'UNIVERSITY_ALIASES': json.dumps(aliases)}, clear=True), \
                patch.object(server, 'CONFIG_PATH') as path:
            path.exists.return_value = True
            path.read_text.return_value = json.dumps({'university_aliases': {'Old University': 'Old'}})
            self.assertEqual(server.load_raw_config()['university_aliases'], aliases)

    def test_environment_aliases_survive_source_and_url_overrides(self):
        aliases = {'Delft University of Technology': 'TU Delft'}
        with patch.dict(server.os.environ, {'UNIVERSITY_ALIASES': json.dumps(aliases)}, clear=True), \
                patch.object(server, 'CONFIG_PATH') as path:
            path.exists.return_value = False
            for source in ['codeforces', 'opentrains', 'domjudge']:
                with self.subTest(source=source):
                    config = server.load_request_config({'source': [source], 'url': ['https://example.org/public']})
                    public = server.app_public_config(config)
                    self.assertEqual(public['universityAliases'], aliases)
                    self.assertEqual(public['sources'][source]['universityAliases'], aliases)

    def test_no_config_required(self):
        with patch.object(server, 'load_raw_config', return_value={}):
            config = server.load_config()
            self.assertEqual(config['source'], 'codeforces')
            public = server.app_public_config(config)
            self.assertEqual(set(public['sources']), {'codeforces', 'opentrains', 'domjudge'})
            self.assertFalse(public['authRequired'])

    def test_legacy_source_alias_and_url_override(self):
        config = {'source': 'opencup', 'opencup_url': 'https://old.example/res'}
        with patch.object(server, 'load_raw_config', return_value=config):
            result = server.load_request_config({'source': ['opencup'], 'url': ['https://new.example/res']})
            self.assertEqual(result['source'], 'opentrains')
            self.assertEqual(server.opencup_public_config(result)['standingsUrl'], 'https://new.example/res')
            self.assertEqual(server.request_source({'source': ['opentrains']}), 'opentrains')

    def test_public_configuration_never_contains_secrets(self):
        public = server.app_public_config({'source': 'domjudge', 'api_key': 'PRIVATE_KEY', 'api_secret': 'PRIVATE_SECRET'})
        self.assertNotIn('PRIVATE', json.dumps(public))



class PublicHTTPTests(unittest.TestCase):
    def test_private_dns_addresses_are_rejected(self):
        for address in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1', '0.0.0.0']:
            with self.subTest(address=address):
                records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 80))]
                with patch.object(socket, 'getaddrinfo', return_value=records), patch.object(socket, 'socket') as connect:
                    with self.assertRaisesRegex(ValueError, 'public Internet'):
                        public_http.public_connection(('example.org', 80))
                    connect.assert_not_called()

    def test_connection_uses_validated_ip(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        with patch.object(socket, 'getaddrinfo', return_value=records), patch.object(socket, 'socket') as factory:
            connection = public_http.public_connection(('example.org', 443))
            self.assertIs(connection, factory.return_value)
            connection.connect.assert_called_once_with(('8.8.8.8', 443))

    def test_invalid_urls(self):
        for url in ['file:///etc/passwd', 'https://user:pass@example.org/', 'http://example.org:8080/']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_http.read_public_html(url)

    def test_response_limit_and_redirect_validation(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'x' * (public_http.MAX_RESPONSE_BYTES + 1)
        with patch.object(public_http.http.client, 'HTTPConnection') as factory:
            factory.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(ValueError, 'size limit'):
                public_http.read_public_html('http://example.org/')
            factory.return_value.close.assert_called_once()
        response.status = 302
        response.getheader.return_value = 'file:///etc/passwd'
        with patch.object(public_http.http.client, 'HTTPConnection') as factory:
            factory.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(ValueError, 'HTTP or HTTPS'):
                public_http.read_public_html('http://example.org/')


if __name__ == '__main__':
    unittest.main()
