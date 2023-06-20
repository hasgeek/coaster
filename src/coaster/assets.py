"""
Assets
======

Coaster provides a simple asset management system for semantically versioned assets
using the semantic_version_ and webassets_ libraries. Many popular libraries such as
jQuery are not semantically versioned, so you will have to be careful about assumptions
you make around them.

Coaster also provides a WebpackManifest extension for Flask if your assets are
built through Webpack_ and referenced in a manifest.json file. This file is expected to
be found in your app's static folder, alongside the built assets.

.. _semantic_version: http://python-semanticversion.readthedocs.org/en/latest/
.. _webassets: http://elsdoerfer.name/docs/webassets/
.. _Webpack: https://webpack.js.org/
"""

from __future__ import annotations

import os.path
import re
import typing as t
import warnings
from collections import defaultdict
from collections.abc import Mapping

from flask import Flask, current_app
from flask_assets import Bundle
from semantic_version import SimpleSpec, Version

_VERSION_SPECIFIER_RE = re.compile('[<=>!*]')

# Version is not used here but is made available for others to import from
__all__ = ['Version', 'SimpleSpec', 'VersionedAssets', 'AssetNotFound']


def split_namespec(namespec: str) -> t.Tuple[str, SimpleSpec]:
    find_mark = _VERSION_SPECIFIER_RE.search(namespec)
    if find_mark is None:
        name = namespec
        spec = SimpleSpec('*')
    else:
        name = namespec[: find_mark.start()]
        spec = SimpleSpec(namespec[find_mark.start() :])
    return name, spec


class AssetNotFound(Exception):  # noqa: N818
    """No asset with this name."""


class VersionedAssets(defaultdict):
    """
    Semantic-versioned asset registry.

    To use, initialize a container for your assets::

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

    def __init__(self) -> None:
        # Override dict's __init__ to prevent parameters
        super().__init__(dict)

    def _require_recursive(self, *namespecs: str) -> t.List[t.Tuple[str, Version, str]]:
        asset_versions: t.Dict[str, Version] = {}  # Name: version
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
                    for req_name, req_version, _req_bundle in req_bundles:
                        asset_versions[req_name] = req_version
                    if bundle is not None:
                        bundles.append((name, version, bundle))
            else:
                raise AssetNotFound(namespec)
        return bundles

    def require(self, *namespecs: str) -> Bundle:
        """Return a bundle of the requested assets and their dependencies."""
        blacklist = {n[1:] for n in namespecs if n.startswith('!')}
        not_blacklist = [n for n in namespecs if not n.startswith('!')]
        return Bundle(
            *(
                bundle
                for name, _version, bundle in self._require_recursive(*not_blacklist)
                if name not in blacklist
            )
        )


MANIFEST_KEY = 'manifest.json'
DEFAULT_VALUE = 'data:,'


class WebpackManifest(Mapping):
    """
    Webpack asset manifest extension for Flask and Jinj2.

    WebpackManifest loads a ``manifest.json`` file produced by Webpack_, and makes the
    contents available to Jinja2 templates as ``{{ manifest['asset_name.ext'] }}``. Call
    syntax is also supported, allowing for use as ``{{ 'asset_name.ext'|manifest }}``.

    WebpackManifest searches for the file at these locations relative to the app folder:

    1. ``static/manifest.json``
    2. ``static/build/manifest.json``

    To look elsewhere, provide a list of paths as the :attr:`search_paths` parameter.
    Webpack plugins and cache can sometimes interfere with asset names. An asset named
    ``app.scss`` may remain ``app.scss`` on a clean build, but turn into ``app.css`` on
    a rebuild. To counter this, WebpackManifest allows for asset name substitutions via
    the :attr:`substitutions` parameter. This is a list of tuples of regex pattern and
    substitute strings. The default substitutions are:

    1. ``.scss`` -> ``.css``
    2. ``.sass`` -> ``.css``
    3. ``.ts`` -> ``.js``

    Substitutions complement the original asset names, which continue to be available.
    If a substitute overlaps an existing asset, the original is preserved and a
    :warn:`RuntimeWarning` is emitted.

    WebpackManifest does not hold the asset data. It loads and stores it as
    ``app.config['manifest.json']`` during the :meth:`init_app` call, and therefore
    requires an app context to retrieve the path. If an unknown asset is requested, it
    will return the static string ``data:,`` instead of raising an exception. Browsers
    should parse this as a valid URI with an empty body.

    :param app: Flask app, can be supplied later by calling :meth:`init_app`
    :param search_paths: Paths to the ``manifest.json`` file, relative to app folder
    :param substitutes: Regex substitutions for asset names
    :param detect_legacy_webpack: Older Webpack versions produce a manifest that has a
        single top-level ``assets`` key and all assets under that. Set this to False to
        turn off auto-detection

    .. _Webpack: https://webpack.js.org/
    """

    search_paths: t.Sequence[str] = [
        'static/manifest.json',
        'static/build/manifest.json',
    ]
    substitutes: t.Sequence[t.Tuple[t.Union[str, re.Pattern], str]] = [
        (r'\.scss$', '.css'),
        (r'\.sass$', '.css'),
        (r'\.ts$', '.js'),
    ]

    def __init__(
        self,
        app: t.Optional[Flask] = None,
        search_paths: t.Optional[t.Sequence[str]] = None,
        substitutes: t.Optional[
            t.Sequence[t.Tuple[t.Union[str, re.Pattern], str]]
        ] = None,
        base_path: t.Optional[str] = None,
        detect_legacy_webpack: bool = True,
    ) -> None:
        if search_paths is not None:
            self.search_paths = search_paths
        if substitutes is not None:
            self.substitutes = substitutes
        self.base_path = base_path
        self.detect_legacy_webpack = detect_legacy_webpack
        if app is not None:
            self.init_app(app, _warning_stack_level=3)

    def init_app(self, app: Flask, _warning_stack_level: int = 2) -> None:
        """Configure WebpackManifest on a Flask app."""
        if 'manifest.json' in app.config:
            warnings.warn(
                f"`app.config[{MANIFEST_KEY!r}]` already exists and will be overridden",
                RuntimeWarning,
                stacklevel=2,
            )

        app.config[MANIFEST_KEY] = {}
        # Install as both a Jinja2 global and filter. These are different namespaces.
        # Global: {{ manifest['...'] }} or {{ manifest('...') }}
        # Filter: {{ '...'|manifest }}
        app.jinja_env.globals['manifest'] = app.jinja_env.filters['manifest'] = self

        resource = None
        path = None
        for path in self.search_paths:
            try:
                resource = app.open_resource(path)
            except FileNotFoundError:
                continue
            else:
                break
        if resource is None:
            raise FileNotFoundError(
                f"No asset manifest found in locations {self.search_paths!r}"
            )

        # Use ``json.loads`` because a substitute JSON implementation (eg: orjson) may
        # not support the ``load`` method
        manifest = app.json.loads(resource.read())
        resource.close()
        if not isinstance(manifest, dict):
            raise ValueError(f"File `{path}` must contain a JSON object at root level")
        if (
            self.detect_legacy_webpack
            and 'assets' in manifest
            # Use [] instead of .get so mypy and pyright will detect the type correctly
            and isinstance(manifest['assets'], dict)
        ):
            # Legacy Webpack manifest.json has all assets in a sub-object named 'assets'
            manifest = manifest['assets']

        for asset_name, asset_value in list(manifest.items()):
            if not isinstance(asset_value, str):
                raise ValueError(
                    f"Expected string value for `{path}:{asset_name}`, got"
                    f" {asset_value!r}"
                )
            for sub_re, sub_replacement in self.substitutes:
                if isinstance(sub_re, re.Pattern):
                    new_name = sub_re.sub(sub_replacement, asset_name)
                else:
                    new_name = re.sub(sub_re, sub_replacement, asset_name)
                if new_name != asset_name:
                    # Only process if there's a match
                    if new_name in manifest:
                        warnings.warn(
                            f"Asset {asset_name} substitute {new_name} is already in"
                            f" the manifest",
                            RuntimeWarning,
                            stacklevel=_warning_stack_level,
                        )
                    else:
                        manifest[new_name] = asset_value

        app.config[MANIFEST_KEY].update(manifest)

    def __call__(self, asset: str) -> str:
        """Return an asset path. In future this may accept options."""
        return self[asset]

    def __getitem__(self, key: str) -> str:
        """Return an asset value, falling back to a safe default."""
        if not current_app:
            return DEFAULT_VALUE
        assets = current_app.config.get(MANIFEST_KEY, {})
        asset_value = assets.get(key)
        if asset_value is None:
            return DEFAULT_VALUE
        if self.base_path is not None:
            return os.path.join(self.base_path, asset_value)
        return asset_value

    def get(self, key: str, default: t.Optional[t.Any] = None) -> t.Any:
        """
        Get an asset if it exists, returning default otherwise.

        Unlike :meth:`__getitem__`, this method's default is `None`, matching the
        behaviour of :meth:`collections.defaultdict.get`.
        """
        if not current_app:
            return default
        assets = current_app.config.get(MANIFEST_KEY, {})
        if key not in assets:
            return default
        asset_value = assets[key]
        if self.base_path is not None:
            return os.path.join(self.base_path, asset_value)
        return asset_value

    # These methods will typically not be used but are present for the Mapping ABC

    def __contains__(self, key: t.Any) -> bool:
        if not current_app:
            return False
        return key in current_app.config.get(MANIFEST_KEY, {})

    def __iter__(self) -> t.Iterator[str]:
        if not current_app:
            return iter({})
        return iter(current_app.config.get(MANIFEST_KEY, {}))

    def __len__(self) -> int:
        if not current_app:
            return 0
        return len(current_app.config.get(MANIFEST_KEY, {}))
