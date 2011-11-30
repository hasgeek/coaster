# -*- coding: utf-8 -*-

import urlparse
from flask import request, url_for

def get_next_url(referrer=False, external=False):
    """
    Get the next URL to redirect to. Don't return external URLs unless
    explicitly asked for. This is to protect the site from being an unwitting
    redirector to external URLs.
    """
    next_url = request.args.get('next', '')
    if not external:
        if next_url.startswith('http:') or next_url.startswith('https:') or next_url.startswith('//'):
            # Do the domains match?
            if urlparse.urlsplit(next_url).hostname != urlparse.urlsplit(request.url).hostname:
                next_url = ''
    if referrer:
        return next_url or request.referrer or url_for('index')
    else:
        return next_url or url_for('index')
