"""
Assets
======

Coaster provides a simple asset management system for semantically versioned
assets using the semantic_version_ and webassets_ libraries. Many popular
libraries such as jQuery are not semantically versioned, so you will have to
be careful about assumptions you make around them.

.. _semantic_version: http://python-semanticversion.readthedocs.org/en/latest/
.. _webassets: http://elsdoerfer.name/docs/webassets/
"""

from __future__ import annotations

from collections import defaultdict
import re

from flask_assets import Bundle
from webassets.filter import Filter, register_filter

# Version is not used here but is made available for others to import from
from semantic_version import SimpleSpec, Version

_VERSION_SPECIFIER_RE = re.compile('[<=>!*]')

__all__ = ['Version', 'SimpleSpec', 'VersionedAssets', 'AssetNotFound']


def split_namespec(namespec):
    find_mark = _VERSION_SPECIFIER_RE.search(namespec)
    if find_mark is None:
        name = namespec
        spec = SimpleSpec('*')
    else:
        name = namespec[: find_mark.start()]
        spec = SimpleSpec(namespec[find_mark.start() :])
    return name, spec


class AssetNotFound(Exception):  # noqa: N818
    """No asset with this name"""


class VersionedAssets(defaultdict):
    """
    Semantic-versioned assets. To use, initialize a container for your assets::

        from coaster.assets import VersionedAssets, Version
        assets = VersionedAssets()

    And then populate it with your assets. The simplest way is by specifying
    the asset name, version number, and path to the file (within your static
    folder)::

        assets['jquery.js'][Version('1.8.3')] = 'js/jquery-1.8.3.js'

    You can also specify one or more *requirements* for an asset by supplying
    a list or tuple of requirements followed by the actual asset::

        assets['jquery.form.js'][Version('2.96.0')] = (
            'jquery.js', 'js/jquery.form-2.96.js')

    You may have an asset that provides replacement functionality for another asset::

        assets['zepto.js'][Version('1.0.0-rc1')] = {
            'provides': 'jquery.js',
            'bundle': 'js/zepto-1.0rc1.js',
            }

    Assets specified as a dictionary can have three keys:

    :parameter provides: Assets provided by this asset
    :parameter requires: Assets required by this asset (with optional version
        specifications)
    :parameter bundle: The asset itself
    :type provides: string or list
    :type requires: string or list
    :type bundle: string or Bundle

    To request an asset::

        assets.require('jquery.js', 'jquery.form.js==2.96.0', ...)

    This returns a webassets Bundle of the requested assets and their dependencies.

    You can also ask for certain assets to not be included even if required if, for
    example, you are loading them from elsewhere such as a CDN. Prefix the asset name
    with '!'::

        assets.require('!jquery.js', 'jquery.form.js', ...)

    To use these assets in a Flask app, register the assets with an environment::

        from flask_assets import Environment
        appassets = Environment(app)
        appassets.register('js_all', assets.require('jquery.js', ...))

    And include them in your master template:

    .. sourcecode:: jinja

        {% assets "js_all" -%}
          <script type="text/javascript" src="{{ ASSET_URL }}"></script>
        {%- endassets -%}

    """

    def __init__(self):
        # Override dict's __init__ to prevent parameters
        super().__init__(dict)

    def _require_recursive(self, *namespecs):
        asset_versions = {}  # Name: version
        bundles = []
        for namespec in namespecs:
            name, spec = split_namespec(namespec)
            version = spec.select(list(self[name].keys()))
            if version:
                if name in asset_versions:
                    if asset_versions[name] not in spec:
                        raise ValueError(
                            f"{namespec} does not match already requested asset"
                            f" {name}=={asset_versions[name]}"
                        )
                else:
                    asset = self[name][version]
                    if isinstance(asset, (list, tuple)):
                        # We have (requires, bundle). Get requirements
                        requires = asset[:-1]
                        provides = []
                        bundle = asset[-1]
                    elif isinstance(asset, dict):
                        requires = asset.get('requires', [])
                        if isinstance(requires, str):
                            requires = [requires]
                        provides = asset.get('provides', [])
                        if isinstance(provides, str):
                            provides = [provides]
                        bundle = asset.get('bundle')
                    else:
                        provides = []
                        requires = []
                        bundle = asset
                    filtered_requires = []
                    for req in requires:
                        req_name, req_spec = split_namespec(req)
                        if req_name in asset_versions:
                            if asset_versions[req_name] not in req_spec:
                                # The version asked for conflicts with a version
                                # currently used.
                                raise ValueError(
                                    f"{req} is not compatible with already requested"
                                    f" version {asset_versions[req_name]}"
                                )
                        else:
                            filtered_requires.append(req)
                    # Get these requirements
                    req_bundles = self._require_recursive(*filtered_requires)
                    bundles.extend(req_bundles)
                    # Save list of provided assets
                    for provided in provides:
                        if provided not in asset_versions:
                            asset_versions[provided] = version
                    for req_name, req_version, req_bundle in req_bundles:
                        asset_versions[req_name] = req_version
                    if bundle is not None:
                        bundles.append((name, version, bundle))
            else:
                raise AssetNotFound(namespec)
        return bundles

    def require(self, *namespecs):
        """Return a bundle of the requested assets and their dependencies."""
        blacklist = {n[1:] for n in namespecs if n.startswith('!')}
        not_blacklist = [n for n in namespecs if not n.startswith('!')]
        return Bundle(
            *(
                bundle
                for name, version, bundle in self._require_recursive(*not_blacklist)
                if name not in blacklist
            )
        )


class UglipyJS(Filter):
    """Minifies Javascript using UgliPyJS, the Python wrapper for UglifyJS."""

    name = 'uglipyjs'

    def setup(self):
        import uglipyjs

        self.uglipyjs = uglipyjs  # pylint: disable=W0201

    def output(self, _in, out, **kw):
        out.write(str(self.uglipyjs.compile(_in.read()), 'utf-8'))


register_filter(UglipyJS)
