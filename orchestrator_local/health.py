"""Metadata-only backend checks; never loads a model or starts generation."""
import httpx


def backend_status(settings):
    try:
        with httpx.Client(base_url=settings['ollama_url'], trust_env=False, timeout=3) as client:
            version = client.get('/api/version'); version.raise_for_status()
            tags = client.get('/api/tags'); tags.raise_for_status()
            found = next((m for m in tags.json()['models'] if m['name'] == settings['model']), None)
        return {'reachable': True, 'version': version.json().get('version'),
                'model_installed': bool(found),
                'digest_matches': bool(found) and (not settings.get('model_digest') or found['digest'] == settings['model_digest'])}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {'reachable': False, 'auto_start_on_job': settings.get('auto_start_ollama', False),
                'detail': type(exc).__name__}
