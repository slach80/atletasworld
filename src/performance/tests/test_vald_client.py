"""
Tests for performance.vald_client.

All HTTP is mocked — never hits real VALD APIs.
"""
import pytest
import responses
from unittest.mock import patch

from django.conf import settings
from django.core.cache import caches

from performance.vald_client import (
    get_vald_token,
    vald_base_url,
    vald_get,
    list_forcedecks_tests,
    ValdAPIError,
)


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clear_vald_cache():
    """Clear VALD token cache before each test."""
    caches['vald'].clear()
    yield
    caches['vald'].clear()


class TestGetValdToken:
    """Test OAuth2 token fetch and caching."""

    @responses.activate
    def test_token_fetch_success(self):
        """Fetch a new token from VALD auth."""
        responses.add(
            responses.POST,
            f'{settings.VALD_AUTH_URL}/oauth/token',
            json={'access_token': 'token-abc-123', 'expires_in': 3600},
            status=200,
        )

        token = get_vald_token()

        assert token == 'token-abc-123'
        assert len(responses.calls) == 1

    @responses.activate
    def test_token_cache_hit(self):
        """Second call uses cached token (no HTTP)."""
        responses.add(
            responses.POST,
            f'{settings.VALD_AUTH_URL}/oauth/token',
            json={'access_token': 'token-cached', 'expires_in': 3600},
            status=200,
        )

        token1 = get_vald_token()
        token2 = get_vald_token()

        assert token1 == token2 == 'token-cached'
        assert len(responses.calls) == 1  # Only one HTTP call

    @responses.activate
    def test_token_fetch_failure(self):
        """Handle auth failure."""
        responses.add(
            responses.POST,
            f'{settings.VALD_AUTH_URL}/oauth/token',
            json={'error': 'invalid_client'},
            status=401,
        )

        with pytest.raises(ValdAPIError, match='OAuth token fetch failed'):
            get_vald_token()


class TestValdBaseUrl:
    """Test region-specific base URL resolution."""

    def test_known_system_and_region(self):
        """Resolve base URL for forcedecks + current region."""
        with patch.object(settings, 'VALD_REGION', 'use'):
            url = vald_base_url('forcedecks')
            assert url == 'https://prd-use-api-extforcedecks.valdperformance.com'

    def test_unknown_system(self):
        """Raise error for unknown system."""
        with pytest.raises(ValdAPIError, match='No base URL'):
            vald_base_url('unknown_system')


class TestValdGet:
    """Test authenticated GET with 429 backoff."""

    @responses.activate
    @patch('performance.vald_client.get_vald_token', return_value='token-test')
    def test_get_success(self, mock_token):
        """Successful GET request."""
        responses.add(
            responses.GET,
            'https://prd-use-api-extforcedecks.valdperformance.com/tests',
            json=[{'testId': 't1'}],
            status=200,
        )

        resp = vald_get('forcedecks', '/tests', params={'tenantId': 'tenant-123'})

        assert resp.status_code == 200
        assert resp.json() == [{'testId': 't1'}]
        assert len(responses.calls) == 1
        assert 'Bearer token-test' in responses.calls[0].request.headers['Authorization']

    @responses.activate
    @patch('performance.vald_client.get_vald_token', return_value='token-test')
    @patch('time.sleep', return_value=None)  # Skip actual sleep
    def test_429_retry_success(self, mock_sleep, mock_token):
        """Retry on 429, succeed on second attempt."""
        responses.add(
            responses.GET,
            'https://prd-use-api-extforcedecks.valdperformance.com/tests',
            status=429,
            headers={'Retry-After': '2'},
        )
        responses.add(
            responses.GET,
            'https://prd-use-api-extforcedecks.valdperformance.com/tests',
            json=[{'testId': 't2'}],
            status=200,
        )

        resp = vald_get('forcedecks', '/tests')

        assert resp.status_code == 200
        assert len(responses.calls) == 2
        mock_sleep.assert_called_once_with(2)

    @responses.activate
    @patch('performance.vald_client.get_vald_token', return_value='token-test')
    @patch('time.sleep', return_value=None)
    def test_429_retry_exhausted(self, mock_sleep, mock_token):
        """Raise error after max retries on 429."""
        for _ in range(4):  # initial + 3 retries
            responses.add(
                responses.GET,
                'https://prd-use-api-extforcedecks.valdperformance.com/tests',
                status=429,
            )

        with pytest.raises(ValdAPIError, match='failed after 3 retries'):
            vald_get('forcedecks', '/tests')


class TestListForceDecksTests:
    """Test ForceDecks /tests cursor pagination."""

    @responses.activate
    @patch('performance.vald_client.get_vald_token', return_value='token-test')
    def test_list_tests_success(self, mock_token):
        """Fetch tests with cursor."""
        responses.add(
            responses.GET,
            'https://prd-use-api-extforcedecks.valdperformance.com/tests',
            json={'tests': [
                {'testId': 't1', 'modifiedDateUtc': '2026-07-20T10:00:00.000Z'},
                {'testId': 't2', 'modifiedDateUtc': '2026-07-20T11:00:00.000Z'},
            ]},
            status=200,
        )

        tests = list_forcedecks_tests(
            tenant_id='tenant-123',
            modified_from_utc='2026-07-01T00:00:00.000Z',
        )

        assert len(tests) == 2
        assert tests[0]['testId'] == 't1'

    @responses.activate
    @patch('performance.vald_client.get_vald_token', return_value='token-test')
    def test_list_tests_204_termination(self, mock_token):
        """Return empty list on 204 No Content."""
        responses.add(
            responses.GET,
            'https://prd-use-api-extforcedecks.valdperformance.com/tests',
            status=204,
        )

        tests = list_forcedecks_tests(
            tenant_id='tenant-123',
            modified_from_utc='2026-07-25T00:00:00.000Z',
        )

        assert tests == []
