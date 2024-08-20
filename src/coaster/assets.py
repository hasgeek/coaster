"""
Assets.

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
# spell-checker:ignore webassets sourcecode endassets

from __future__ import annotations

import os
import re
import warnings
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final, Optional, Union
from urllib.parse import urljoin

from flask_assets import Bundle
from semantic_version import SimpleSpec, Version

from .compat import SansIoApp, current_app

_VERSION_SPECIFIER_RE = re.compile('[<=>!*]')

# Version is not used here but is made available for others to import from
__all__ = [
    'Version',
    'SimpleSpec',
    'VersionedAssets',
    'AssetNotFound',
    'AssetNotFoundError',
    'WebpackManifest',
]


def split_namespec(namespec: str) -> tuple[str, SimpleSpec]:
    find_mark = _VERSION_SPECIFIER_RE.search(namespec)
    if find_mark is None:
        name = namespec
        spec = SimpleSpec('*')
    else:
        name = namespec[: find_mark.start()]
        spec = SimpleSpec(namespec[find_mark.start() :])
    return name, spec


class AssetNotFoundError(Exception):
    """No asset with this name."""


AssetNotFound = AssetNotFoundError


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
            'jquery.js',
            'js/jquery.form-2.96.js',
        )

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

    def _require_recursive(self, *namespecs: str) -> list[tuple[str, Version, str]]:
        asset_versions: dict[str, Version] = {}  # Name: version
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
                    requires: Union[list[str], tuple[str, ...], str]
                    provides: Union[list[str], tuple[str, ...], str]
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
                                    f"{req} required by {namespec} is not compatible"
                                    f" with already requested version"
                                    f" {asset_versions[req_name]}"
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
                        asset_versions[req_name] = req_version  # noqa: PERF403
                    if bundle is not None:
                        bundles.append((name, version, bundle))
            else:
                raise AssetNotFoundError(namespec)
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


EXTENSION_KEY: Final[str] = 'manifest.json'


def _get_assets_for_current_app() -> dict[str, str]:
    """Get assets from current_app's extension registry (internal use only)."""
    return current_app.extensions.get(EXTENSION_KEY, {})


class WebpackManifest(Mapping):
    """
    Webpack asset manifest extension for Flask/Quart and Jinja2.

    WebpackManifest loads a ``manifest.json`` file produced by Webpack_ and makes the
    content available in Jinja2 via a new global var ``manifest`` (customizable).

    Usage::

        app1 = Flask(__name__)
        app2 = Quart(__name__)
        manifest = WebpackManifest()
        manifest.init_app(app1)
        manifest.init_app(app2)

    In Jinja2 templates:

    .. sourcecode:: jinja

        1. As a callable: {{ manifest('asset_name.ext', optional_default_value) }}
        2. As a dict: {{ manifest['asset_name.ext'] }}
        3. Dict get: {{ manifest.get('asset_name.ext', optional_default_value) }}

    Call syntax has a browser-friendly default: ``data:,``. The standard dictionary
    method :meth:`get` defaults to the usual `None` and is not recommended in templates
    as it will render as a string ``'None'``. The three invocations have different
    behaviours when an unknown asset is requested:

    1. Dict access: raises KeyError, which Jinja2 will remap to an Undefined object,
        which renders as an empty string. This will also log an error with a traceback
        to the current app's logger.
    2. Call access: does not raise KeyError but instead returns the default value
        ``'data:,'`` or as provided. Also logs an error.
    3. :meth:`get` method: returns the default (`None` or as provided) and does not log
        an error. You should only use this method when supplying an explicit default,
        and when you do not consider a missing asset to be a log-worthy incident.

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
    :exc:`RuntimeWarning` is emitted.

    WebpackManifest does not hold the asset data. It loads and stores it as
    ``app.extensions['manifest.json']`` during the :meth:`init_app` call, and therefore
    requires an app context at runtime.

    :param app: Flask or Quart app, can be supplied later by calling :meth:`init_app`
    :param filepath: Path to the manifest JSON file relative to the app folder
        (default ``'static/manifest.json'``)
    :param substitutes: Regex substitutions for asset names as tuples of pattern and
        replacement
    :param urlpath: Optional URL path to prefix to asset path (typically
        ``'/static'``, but not required if Webpack is configured correctly)
    :param detect_legacy_webpack: Older Webpack versions produce a manifest that has a
        single top-level ``assets`` key. Set this to `False` to turn off auto-detection
        in case it's causing problems (default `True`)
    :param jinja_global: Install WebpackManifest as a Jinja2 global with this name
        (default ``'manifest'``, use ``None`` to not install to Jinja2)

    .. _Webpack: https://webpack.js.org/
    """

    substitutes: Sequence[tuple[Union[str, re.Pattern], str]] = [
        (r'\.scss$', '.css'),
        (r'\.sass$', '.css'),
        (r'\.ts$', '.js'),
    ]

    def __init__(
        self,
        app: Optional[SansIoApp] = None,
        *,
        filepath: str = 'static/manifest.json',
        urlpath: Optional[str] = None,
        substitutes: Optional[Sequence[tuple[Union[str, re.Pattern], str]]] = None,
        detect_legacy_webpack: bool = True,
        jinja_global: Optional[str] = 'manifest',
    ) -> None:
        self.filepath = filepath
        self.urlpath = urlpath
        if substitutes is not None:
            self.substitutes = substitutes
        self.detect_legacy_webpack = detect_legacy_webpack
        self.jinja_global = jinja_global
        if app is not None:
            self.init_app(app, _warning_stack_level=3)

    def init_app(self, app: SansIoApp, _warning_stack_level: int = 2) -> None:
        """Configure WebpackManifest on a Flask or Quart app."""
        # Step 1: Open manifest.json and validate basic structure (incl. legacy check)
        with open(os.path.join(app.root_path, self.filepath), 'rb') as resource:
            # Use ``json.loads`` because a substitute JSON implementation may not
            # support the ``load`` method (eg: orjson has ``loads`` but not ``load``)
            assets = app.json.loads(resource.read())
        if not isinstance(assets, dict):
            raise ValueError(
                f"File `{self.filepath}` must contain a JSON object at the root level"
            )
        if (
            self.detect_legacy_webpack
            and 'assets' in assets
            # Use [] instead of .get so mypy and pyright can identify the type as dict
            and isinstance(assets['assets'], dict)
        ):
            # Legacy Webpack manifest.json has all assets in a sub-object named 'assets'
            assets = assets['assets']

        # Step 2: Validate asset paths are strings and make substitute names for assets
        for asset_name, asset_path in list(assets.items()):
            if not isinstance(asset_path, str):
                raise ValueError(
                    f"Expected a string for `{self.filepath}:{asset_name}`, got"
                    f" {asset_path!r}"
                )
            for sub_re, sub_replacement in self.substitutes:
                if isinstance(sub_re, re.Pattern):
                    new_name = sub_re.sub(sub_replacement, asset_name)
                else:
                    new_name = re.sub(sub_re, sub_replacement, asset_name)
                if new_name != asset_name:
                    # Only process if there's a match
                    if new_name in assets:
                        warnings.warn(
                            f"Asset {asset_name} substitute {new_name} is already in"
                            f" the manifest",
                            RuntimeWarning,
                            stacklevel=_warning_stack_level,
                        )
                    else:
                        assets[new_name] = asset_path

        # Step 3: Install as a Jinja2 global if requested (but not as a filter)
        # This will work: ``{{ manifest['...'] }}`` or ``{{ manifest('...') }}``
        # This will not work: ``{{ '...'|manifest }}``
        if self.jinja_global:
            app.jinja_env.globals[self.jinja_global] = self

        # Step 4: Save to app.extensions, issuing a warning if there is existing content
        if EXTENSION_KEY in app.extensions:
            warnings.warn(
                f"`app.extensions[{EXTENSION_KEY!r}]` already exists and will be"
                f" overwritten",
                RuntimeWarning,
                stacklevel=_warning_stack_level,
            )

        app.extensions[EXTENSION_KEY] = assets

    def __getitem__(self, key: str) -> str:
        """Return an asset path if present, or log an app error and raise KeyError."""
        if not current_app:
            raise KeyError(key)
        assets = _get_assets_for_current_app()
        try:
            if self.urlpath is not None:
                return urljoin(self.urlpath, assets[key])
            return assets[key]
        except KeyError:
            current_app.logger.error(
                "Manifest %s does not have asset %s",
                self.filepath,
                key,
                stack_info=True,
            )
            raise

    def __call__(self, asset: str, default: str = 'data:,') -> str:
        """Return an asset path, falling back to a browser-friendly default."""
        try:
            return self[asset]
        except KeyError:
            return default

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """
        Get an asset if it exists, returning the default otherwise.

        This method does not wrap :meth:`__getitem__` as returning the default is not
        considered an error and should not be logged.
        """
        if not current_app:
            return default
        assets = _get_assets_for_current_app()
        if key not in assets:
            return default
        asset_value = assets[key]
        if self.urlpath is not None:
            return urljoin(self.urlpath, asset_value)
        return asset_value

    # These methods will typically not be used but are present for the Mapping ABC

    def __contains__(self, key: Any) -> bool:
        if not current_app:
            return False
        return key in _get_assets_for_current_app()

    def __iter__(self) -> Iterator[str]:
        if not current_app:
            return iter({})
        return iter(_get_assets_for_current_app())

    def __len__(self) -> int:
        if not current_app:
            return 0
        return len(_get_assets_for_current_app())
