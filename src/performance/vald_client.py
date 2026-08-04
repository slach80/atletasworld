"""
VALD Performance API client.

Thin, stateless module for authenticating to VALD and fetching data.
Mirrors payments/stripe_utils.py pattern.
"""
import logging
import time
from typing import Dict, List, Optional

import requests
from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)


class ValdAPIError(Exception):
    """Base exception for VALD API errors."""
    pass


def get_vald_token() -> str:
    """
    Get a cached OAuth2 access token for VALD external APIs.

    Uses Redis cache (expires_in - 60s) to avoid re-auth across Celery workers.
    """
    cache_key = 'vald:access_token'
    token = caches['vald'].get(cache_key)

    if token:
        logger.debug('VALD token cache hit')
        return token

    logger.info('VALD token cache miss — fetching new token')

    try:
        resp = requests.post(
            f'{settings.VALD_AUTH_URL}/oauth/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': settings.VALD_CLIENT_ID,
                'client_secret': settings.VALD_CLIENT_SECRET,
                'audience': 'vald-api-external',
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        access_token = data['access_token']
        expires_in = data.get('expires_in', 3600)

        # Cache with 60s buffer
        caches['vald'].set(cache_key, access_token, timeout=expires_in - 60)

        return access_token

    except requests.RequestException as e:
        logger.exception('VALD token fetch failed')
        raise ValdAPIError(f'OAuth token fetch failed: {e}') from e


def vald_base_url(system: str) -> str:
    """
    Resolve the region-specific base URL for a VALD system.

    Raises ValdAPIError if system is unknown or VALD_REGION is misconfigured.
    """
    region = settings.VALD_REGION
    key = (system, region)

    base = settings.VALD_API_BASES.get(key)
    if not base:
        raise ValdAPIError(
            f"No base URL for system={system}, region={region}. "
            f"Check VALD_REGION and VALD_API_BASES in settings."
        )

    return base


def vald_get(system: str, path: str, params: Optional[Dict] = None) -> requests.Response:
    """
    Issue a GET request to a VALD external API with auth + 429 backoff.

    Args:
        system: VALD system ('forcedecks', 'smartspeed', 'profiles', etc.)
        path: API path (e.g. '/tests', '/resultdefinitions')
        params: Query parameters

    Returns:
        Response object (caller handles .json() / .status_code)

    Raises:
        ValdAPIError on auth failure, unknown system, or exhausted retries
    """
    base = vald_base_url(system)
    url = f"{base}{path}"
    token = get_vald_token()

    headers = {'Authorization': f'Bearer {token}'}

    retries = 0
    max_retries = 3
    backoff = 1  # seconds

    while retries <= max_retries:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)

            # 429 Too Many Requests — exponential backoff
            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', backoff))
                logger.warning(
                    f"VALD 429 rate limit hit: {url} — retrying after {retry_after}s "
                    f"(attempt {retries + 1}/{max_retries + 1})"
                )
                time.sleep(retry_after)
                retries += 1
                backoff *= 2
                continue

            # Other errors — raise immediately (no retry)
            resp.raise_for_status()
            return resp

        except requests.RequestException as e:
            logger.exception(f'VALD GET {url} failed')
            raise ValdAPIError(f'GET {path} failed: {e}') from e

    # Exhausted retries
    raise ValdAPIError(f'GET {path} failed after {max_retries} retries (429 rate limit)')


def list_tenants() -> List[Dict]:
    """
    Fetch all tenants from the External Tenants API.

    Returns:
        List of tenant objects: {id, name}.
    """
    resp = vald_get('tenants', '/tenants')
    return resp.json().get('tenants', [])


def list_profiles(tenant_id: str, since: Optional[str] = None) -> List[Dict]:
    """
    Fetch athlete profiles from the External Profiles API.

    Args:
        tenant_id: VALD tenant ID (required)
        since: ISO8601 timestamp for incremental sync (optional)

    Returns:
        List of profile objects: {profileId, givenName, familyName, dateOfBirth, ...}.
    """
    params = {'tenantId': tenant_id}
    if since:
        params['modifiedFromUtc'] = since

    resp = vald_get('profiles', '/profiles', params=params)
    return resp.json().get('profiles', [])


def list_forcedecks_tests(
    tenant_id: str,
    modified_from_utc: str,
    profile_id: Optional[str] = None
) -> List[Dict]:
    """
    Fetch ForceDecks tests from the External ForceDecks API.

    Uses cursor pagination: feed the last test's modifiedDateUtc as the next
    request's modified_from_utc. A 204 No Content response signals the end.

    Args:
        tenant_id: VALD tenant ID (required)
        modified_from_utc: ISO8601 cursor (required, even on first request)
        profile_id: Filter to a single athlete (optional)

    Returns:
        List of test objects (empty if 204, else parsed JSON array)
    """
    params = {
        'tenantId': tenant_id,
        'modifiedFromUtc': modified_from_utc,
    }
    if profile_id:
        params['profileId'] = profile_id

    resp = vald_get('forcedecks', '/tests', params=params)

    # 204 No Content = end of pagination
    if resp.status_code == 204:
        logger.debug(f'ForceDecks /tests cursor exhausted (204) at {modified_from_utc}')
        return []

    return resp.json().get('tests', [])


def list_forcedecks_trials(team_id: str, test_id: str) -> List[Dict]:
    """
    Fetch reps/trials for a single ForceDecks test.

    Args:
        team_id: VALD tenant ID (path param, same as tenantId in /tests)
        test_id: VALD test ID

    Returns:
        List of trial objects
    """
    resp = vald_get('forcedecks', f'/v2019q3/teams/{team_id}/tests/{test_id}/trials')
    return resp.json()


def list_result_definitions(system: str = 'forcedecks') -> List[Dict]:
    """
    Fetch all metric definitions for a system.

    VALD: "do not change frequently" — pull once, cache in DB.

    Args:
        system: 'forcedecks' | 'smartspeed' | ...

    Returns:
        List of resultDefinition objects
    """
    resp = vald_get(system, '/resultdefinitions')
    return resp.json().get('resultDefinitions', [])


def get_result_definition(result_id: str, system: str = 'forcedecks') -> Dict:
    """
    Fetch a single metric definition (on-demand refresh).

    Args:
        result_id: VALD resultId
        system: 'forcedecks' | 'smartspeed' | ...

    Returns:
        resultDefinition object
    """
    resp = vald_get(system, f'/resultdefinition/{result_id}')
    return resp.json()
