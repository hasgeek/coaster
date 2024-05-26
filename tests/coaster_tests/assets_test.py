"""Tests for asset management helpers."""

# pylint: disable=redefined-outer-name

import json
import logging
import re
from io import StringIO
from typing import Optional
from unittest.mock import patch

import pytest
from flask import Flask
from jinja2.exceptions import UndefinedError

from coaster.assets import AssetNotFound, Version, VersionedAssets, WebpackManifest
from coaster.compat import render_template_string

# --- VersionedAssets tests ------------------------------------------------------------


@pytest.fixture
def assets() -> VersionedAssets:
    """Sample asset fixture."""
    _assets = VersionedAssets()
    _assets['jquery.js'][Version('1.7.1')] = 'jquery-1.7.1.js'
    _assets['jquery.js'][Version('1.8.3')] = 'jquery-1.8.3.js'
    _assets['jquery.some.js'][Version('1.8.3')] = {
        'provides': 'jquery.js',
        'requires': 'jquery.js',
        'bundle': None,
    }
    _assets['jquery.form.js'][Version('2.96.0')] = (
        'jquery.js',
        'jquery.form-2.96.js',
    )
    _assets['jquery.form.1.js'][Version('2.96.0')] = {
        'requires': 'jquery.js>=1.8.3',
        'provides': 'jquery.form.js',
    }
    _assets['old-lib.js'][Version('1.0.0')] = (
        'jquery.js<1.8.0',
        'old-lib-1.0.0.js',
    )
    return _assets


def test_asset_unversioned(assets: VersionedAssets) -> None:
    """Assets can be loaded without a version specifier to get the latest."""
    bundle = assets.require('jquery.js')
    assert bundle.contents == ('jquery-1.8.3.js',)


def test_asset_versioned(assets: VersionedAssets) -> None:
    """Specific versions can be requested."""
    bundle = assets.require('jquery.js==1.7.1')
    assert bundle.contents == ('jquery-1.7.1.js',)
    bundle = assets.require('jquery.js<1.8.0')
    assert bundle.contents == ('jquery-1.7.1.js',)
    bundle = assets.require('jquery.js>=1.8.0')
    assert bundle.contents == ('jquery-1.8.3.js',)


def test_missing_asset(assets: VersionedAssets) -> None:
    """A missing asset raises an exception."""
    with pytest.raises(AssetNotFound):
        assets.require('missing.js')


def test_single_requires(assets: VersionedAssets) -> None:
    """An asset can be specified as a tuple containing all requirements."""
    # See fixture for how the asset is described
    bundle = assets.require('jquery.form.js')
    assert bundle.contents == ('jquery-1.8.3.js', 'jquery.form-2.96.js')


def test_single_requires_which_is_dict(assets: VersionedAssets) -> None:
    """An asset can be specified as a dictionary."""
    # See fixture for how the asset is described
    bundle = assets.require('jquery.form.1.js')
    assert bundle.contents == ('jquery-1.8.3.js',)


def test_provides_requires(assets: VersionedAssets) -> None:
    """An asset can claim provide another asset."""
    # See fixture for how the asset is described
    bundle = assets.require('jquery.some.js', 'jquery.form.js')
    assert bundle.contents == ('jquery-1.8.3.js', 'jquery.form-2.96.js')


def test_version_copies(assets: VersionedAssets) -> None:
    """Asset versions are NOT resolved automatically, requiring some care."""
    # First asset will load highest available version of the requirement, which
    # conflicts with the second requested version. The same asset can't be requested
    # twice
    with pytest.raises(
        ValueError,
        match='jquery.js==.*? does not match already requested asset jquery.js==.*?',
    ):
        assets.require('jquery.form.js', 'jquery.js==1.7.1')


def test_version_conflict(assets: VersionedAssets) -> None:
    """Asset version conflicts will cause an error."""
    # First asset will load highest available version of the requirement, which
    # conflicts with the second requested version. The same asset can't be requested
    # twice
    with pytest.raises(
        ValueError,
        match='jquery.js<.*? is not compatible with already requested version 1.8.3',
    ):
        assets.require('jquery.form.js', 'old-lib.js')


def test_blacklist(assets: VersionedAssets) -> None:
    """An asset can be removed from the bundle using a ``!`` prefix."""
    bundle = assets.require('!jquery.js', 'jquery.form.js')
    assert bundle.contents == ('jquery.form-2.96.js',)
    bundle = assets.require('jquery.form.js', '!jquery.js')
    assert bundle.contents == ('jquery.form-2.96.js',)


# --- WebpackManifest tests ------------------------------------------------------------


# --- Fixtures
# The `app` fixture from conftest has module scope, so we have function-scoped fixtures
# for the tests here


@pytest.fixture
def app1() -> Flask:
    """First Flask app fixture."""
    return Flask(__name__)


@pytest.fixture
def app2() -> Flask:
    """Second Flask app fixture."""
    return Flask(__name__)


# --- Tests: basic operations, object can be created, methods can be called


def test_create_empty_manifest() -> None:
    """An empty manifest can exist and works without an app."""
    manifest = WebpackManifest()
    assert len(manifest) == 0
    assert not list(iter(manifest))
    assert 'random' not in manifest
    assert manifest('random') == 'data:,'
    assert manifest('random', 'default-value') == 'default-value'
    assert manifest.get('random') is None
    assert manifest.get('random', 'default-value') == 'default-value'
    with pytest.raises(KeyError):
        _ = manifest['random']


def test_unaffiliated_manifest(app1: Flask) -> None:
    """A manifest not affiliated with an app will work in the app's context."""
    manifest = WebpackManifest()
    with app1.app_context():
        assert len(manifest) == 0
        assert not list(iter(manifest))
        assert manifest('random') == 'data:,'
        assert manifest('random', 'default-value') == 'default-value'
        assert manifest.get('random') is None
        assert manifest.get('random', 'default-value') == 'default-value'
        with pytest.raises(KeyError):
            _ = manifest['random']


@pytest.mark.parametrize(
    ('filepath', 'error'),
    [
        (None, "No such file or directory: '.*?/static/manifest.json'"),
        ('does-not-exist.json', "No such file or directory: '.*?/does-not-exist.json'"),
    ],
)
def test_manifest_filepath(app1: Flask, filepath: Optional[str], error: str) -> None:
    """If the manifest file is missing, FileNotFoundError is raised."""
    if filepath is None:
        with pytest.raises(FileNotFoundError, match=error):
            # Confirm the error message indicates the default filepath
            WebpackManifest(app1)
    else:
        with pytest.raises(FileNotFoundError, match=error):
            WebpackManifest(app1, filepath=filepath)


def test_load_manifest_from_file(app1: Flask) -> None:
    """A test manifest file is loaded correctly, with substitutions."""
    manifest = WebpackManifest(app1, filepath='test-manifest.json')
    assert len(manifest) == 0
    with app1.app_context():
        assert len(manifest) == 6
        assert 'test.css' in manifest
        assert 'other.css' not in manifest
        assert 'index.scss' in manifest
        assert 'index.css' in manifest
        assert (
            manifest['test.css']
            == manifest('test.css')
            == manifest.get('test.css')
            == 'test-asset.css'
        )
        assert (
            manifest['index.scss']
            == manifest('index.scss')
            == manifest.get('index.scss')
            == manifest['index.css']
            == manifest('index.css')
            == manifest.get('index.css')
            == 'test-index.css'
        )
        # Call iter(manifest) to confirm it works, then recast as set for comparison
        assert set(iter(manifest)) == {
            'index.css',  # index.css was created as a substitute name for index.scss
            'index.scss',
            'test.css',
            'test.jpg',
            'test.js',
            'test.png',
        }
        # Since other.css is not present, a default value is returned
        assert manifest('other.css') == 'data:,'
        assert manifest('other.css', 'default-value') == 'default-value'
        assert manifest.get('other.css') is None
        assert manifest.get('other.css', 'default-value') == 'default-value'
        with pytest.raises(KeyError):
            _ = manifest['other.css']


def test_manifest_limited_to_app_with_context(app1: Flask, app2: Flask) -> None:
    """A manifest loaded for one app is not available in another app's context."""
    manifest = WebpackManifest(
        app1, filepath='test-manifest.json', urlpath='/test-prefix/'
    )
    assert len(manifest) == 0
    with app1.app_context():
        assert len(manifest) == 6
        assert (
            manifest['test.css']
            == manifest('test.css')
            == manifest.get('test.css')
            == '/test-prefix/test-asset.css'
        )
    with app2.app_context():
        assert len(manifest) == 0
        # But we can fake the content and the extension works
        app2.extensions['manifest.json'] = {'test-entry': 'test-value'}
        assert len(manifest) == 1
        assert manifest['test-entry'] == '/test-prefix/test-value'


# --- Tests for options: custom base path, substitute asset names


def test_load_manifest_from_file_with_custom_basepath(app1: Flask) -> None:
    """A base path is added to the values in the manifest."""
    manifest = WebpackManifest(app1, filepath='test-manifest.json', urlpath='/static/')
    assert len(manifest) == 0
    with app1.app_context():
        assert len(manifest) == 6
        assert 'test.css' in manifest
        assert 'other.css' not in manifest
        assert 'index.scss' in manifest
        assert 'index.css' in manifest
        assert (
            manifest['test.css']
            == manifest('test.css')
            == manifest.get('test.css')
            == '/static/test-asset.css'
        )
        assert (
            manifest['index.scss']
            == manifest('index.scss')
            == manifest.get('index.scss')
            == manifest['index.css']
            == manifest('index.css')
            == manifest.get('index.css')
            == '/static/test-index.css'
        )
        # Since other.css is not present, the base path is not prefixed to default value
        assert manifest('other.css') == 'data:,'
        assert manifest('other.css', 'default-value') == 'default-value'
        assert manifest.get('other.css') is None
        assert manifest.get('other.css', 'default-value') == 'default-value'
        with pytest.raises(KeyError):
            _ = manifest['other.css']


def test_manifest_disable_substitutions(app1: Flask, app2: Flask) -> None:
    """Asset name substitutions can be disabled by passing an empty list."""
    manifest1 = WebpackManifest(app1, filepath='test-manifest.json')
    manifest2 = WebpackManifest(
        app2, filepath='test-manifest.json', substitutes=[], urlpath='/nosub/'
    )
    # Manifest instances can be used interchangeably with app instances
    # Manifest1 is linked to App1 with default substitutions and no base path
    # Manifest2 is linked to App2 with no substitutions and a base path
    with app1.app_context():
        assert len(manifest1) == 6
        assert len(manifest2) == 6
        assert manifest1['test.css'] == 'test-asset.css'
        assert manifest2['test.css'] == '/nosub/test-asset.css'
        assert 'index.css' in manifest1
        assert 'index.css' in manifest2
        assert manifest1['index.scss'] == manifest1['index.css'] == 'test-index.css'
        assert (
            manifest2['index.scss'] == manifest2['index.css'] == '/nosub/test-index.css'
        )
    # App2 will not have the substitutes
    with app2.app_context():
        assert len(manifest1) == 5
        assert len(manifest2) == 5
        assert manifest1['test.css'] == 'test-asset.css'
        assert manifest2['test.css'] == '/nosub/test-asset.css'
        assert 'index.css' not in manifest1
        assert 'index.css' not in manifest2
        assert manifest1['index.scss'] == 'test-index.css'
        assert manifest2['index.scss'] == '/nosub/test-index.css'
        with pytest.raises(KeyError):
            _ = manifest1['index.css']
        with pytest.raises(KeyError):
            _ = manifest2['index.css']


def test_compiled_regex_substitutes(app1: Flask) -> None:
    """Substitutions can be specified as compiled regex patterns."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(json.dumps({'test.jpg': 'img/test.jpg'}))
        manifest = WebpackManifest(app1, substitutes=[(re.compile(r'\.jpg$'), '.jpeg')])
        with app1.app_context():
            assert set(manifest) == {'test.jpg', 'test.jpeg'}
            assert manifest['test.jpg'] == manifest['test.jpeg'] == 'img/test.jpg'


def test_multiple_substitutes(app1: Flask) -> None:
    """One asset can have multiple substitute names."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(
            json.dumps({'test.jpg': 'img/test.jpg', 'test.png': 'img/test.png'})
        )
        manifest = WebpackManifest(
            app1,
            substitutes=[
                (re.compile(r'\.jpg$'), '.jpeg'),
                (r'\.jpg$', '.jpeg-image'),
                (r'\.png$', '.png-image'),
            ],
        )
        with app1.app_context():
            assert set(manifest) == {
                'test.jpg',
                'test.jpeg',
                'test.jpeg-image',
                'test.png',
                'test.png-image',
            }
            assert (
                manifest['test.jpg']
                == manifest['test.jpeg']
                == manifest['test.jpeg-image']
                == 'img/test.jpg'
            )


def test_substitute_overlap_warning(app1: Flask) -> None:
    """If a substitute name is already present, a warning is raised."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(
            json.dumps({'test.jpg': 'img/test.jpg', 'test.png': 'img/test.png'})
        )
        with pytest.warns(RuntimeWarning):
            manifest = WebpackManifest(
                app1,
                substitutes=[
                    (r'\.jpg$', '.image'),
                    (r'\.png$', '.image'),
                ],
            )
        with app1.app_context():
            assert set(manifest) == {'test.jpg', 'test.png', 'test.image'}
            assert manifest['test.jpg'] == manifest['test.image'] == 'img/test.jpg'
            assert manifest['test.png'] == 'img/test.png'


# --- Tests for misuse: dupe init, invalid manifest content, legacy manifest detection


def test_dupe_init_app(app1: Flask) -> None:
    """Calling init_app twice will raise a warning but will work."""
    manifest1 = WebpackManifest(app1, filepath='test-manifest.json', substitutes=[])
    with app1.app_context():
        assert len(manifest1) == 5
        assert 'index.css' not in manifest1

    with pytest.warns(RuntimeWarning):
        manifest1.init_app(app1)
    with app1.app_context():
        assert len(manifest1) == 5

    manifest2 = WebpackManifest(filepath='test-manifest.json', urlpath='/2/')
    with pytest.warns(RuntimeWarning):
        manifest2.init_app(app1)

    with app1.app_context():
        assert len(manifest1) == 6  # Length increased because manifest2 added a subst.
        assert len(manifest2) == 6
        assert 'index.css' in manifest1
        assert 'index.css' in manifest2
        assert manifest1['index.css'] == 'test-index.css'
        assert manifest2['index.css'] == '/2/test-index.css'


def test_manifest_must_be_valid_json(app1: Flask) -> None:
    """The manifest file must be valid JSON."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO('This is not JSON')
        with pytest.raises(json.JSONDecodeError):
            WebpackManifest(app1)


def test_manifest_json_must_be_dict(app1: Flask) -> None:
    """The manifest file must contain a JSON object."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(json.dumps(["This", "is", "a", "list"]))
        with pytest.raises(
            ValueError, match='must contain a JSON object at the root level'
        ):
            WebpackManifest(app1)


def test_legacy_webpack(app1: Flask) -> None:
    """Legacy webpack manifest detection is on by default."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(
            json.dumps({'assets': {'app': 'js/app.version.js'}})
        )
        manifest1 = WebpackManifest(app1)
        with app1.app_context():
            assert len(manifest1) == 1
            assert set(manifest1) == {'app'}
            assert manifest1['app'] == 'js/app.version.js'


def test_legacy_no_false_alarm(app1: Flask) -> None:
    """Legacy detection will not be confused by an asset named ``assets``."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(
            json.dumps({'assets': 'why-is-this-called-assets.css'})
        )
        manifest1 = WebpackManifest(app1, urlpath='/test/')
        with app1.app_context():
            assert len(manifest1) == 1
            assert set(manifest1) == {'assets'}
            assert manifest1['assets'] == '/test/why-is-this-called-assets.css'


def test_legacy_detection_disabled_on_legacy_file(app1: Flask) -> None:
    """Legacy detection must not be disabled when processing a legacy manifest."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(
            json.dumps({'assets': {'app': 'js/app.version.js'}})
        )
        # If legacy detection is disabled, WebpackManifest will complain that the value
        # is not a string
        with pytest.raises(
            ValueError, match="Expected a string for `static/manifest.json:assets`"
        ):
            WebpackManifest(app1, detect_legacy_webpack=False)


# --- Tests for use in Jinja2 templates


def test_jinja2_global(app1: Flask) -> None:
    """A Jinja2 global var is installed and can be used in templates."""
    manifest = WebpackManifest(app1, filepath='test-manifest.json')
    with app1.app_context():
        assert 'test.css' in manifest
        assert (
            render_template_string(
                '''<link rel="stylesheet" src="{{ manifest['test.css'] }}" />'''
            )
            == render_template_string(
                '''<link rel="stylesheet" src="{{ manifest('test.css') }}" />'''
            )
            == render_template_string(
                '''<link rel="stylesheet" src="{{ manifest.get('test.css') }}" />'''
            )
            == '<link rel="stylesheet" src="test-asset.css" />'
        )
        assert 'unknown.css' not in manifest
        # Jinja2 will cast KeyError as an Undefined type, represented as an empty string
        assert (
            render_template_string(
                '''<link rel="stylesheet" src="{{ manifest['unknown.css'] }}" />'''
            )
            == '<link rel="stylesheet" src="" />'
        )
        # Call access will return a default value ``'data:,'`` for missing assets
        assert (
            render_template_string(
                '''<link rel="stylesheet" src="{{ manifest('unknown.css') }}" />'''
            )
            == render_template_string(
                '''<link rel="stylesheet" src="{{ manifest.get('unknown.css','''
                ''' 'data:,') }}" />'''
            )
            == '<link rel="stylesheet" src="data:," />'
        )


def test_jinja2_global_rename_or_skip(app1: Flask, app2: Flask) -> None:
    """The Jinja2 global can be renamed or skipped."""
    manifest1 = WebpackManifest(
        app1, filepath='test-manifest.json', jinja_global='asset'
    )
    manifest2 = WebpackManifest(app2, filepath='test-manifest.json', jinja_global=None)

    # In app1, the global is registered as `asset` instead of the default `manifest`
    with app1.app_context():
        assert 'test.css' in manifest1

        with pytest.raises(UndefinedError, match="'manifest' is undefined"):
            render_template_string(
                '''<link rel="stylesheet" src="{{ manifest['test.css'] }}" />'''
            )

        assert (
            render_template_string(
                '''<link rel="stylesheet" src="{{ asset['test.css'] }}" />'''
            )
            == '<link rel="stylesheet" src="test-asset.css" />'
        )

    # In app2, there is no Jinja2 global at all
    with app2.app_context():
        assert 'test.css' in manifest2

        with pytest.raises(UndefinedError, match="'manifest' is undefined"):
            render_template_string(
                '''<link rel="stylesheet" src="{{ manifest['test.css'] }}" />'''
            )


def test_keyerror_caplog(caplog: pytest.LogCaptureFixture, app1: Flask) -> None:
    """A KeyError under an app context will be logged as an app error."""
    with patch('flask.app.Flask.open_resource') as mock:
        mock.return_value = StringIO(json.dumps({'exists.css': 'asset-exists.css'}))
        manifest = WebpackManifest(app1)

    caplog.clear()
    # Without an app context, KeyError will not be logged
    with pytest.raises(KeyError):
        _ = manifest['does-not-exist.css']
    assert caplog.record_tuples == []
    with app1.app_context():
        assert manifest['exists.css'] == 'asset-exists.css'
        # A successful lookup will not be logged
        assert caplog.record_tuples == []
        with pytest.raises(KeyError):
            _ = manifest['does-not-exist.css']
        assert caplog.record_tuples == [
            (
                __name__,
                logging.ERROR,
                'Manifest static/manifest.json does not have asset does-not-exist.css',
            )
        ]

        caplog.clear()
        assert caplog.record_tuples == []

        # Call access does not raise KeyError, but will still log an error
        assert manifest('does-not-exist.css') == 'data:,'
        assert caplog.record_tuples == [
            (
                __name__,
                logging.ERROR,
                'Manifest static/manifest.json does not have asset does-not-exist.css',
            )
        ]

        caplog.clear()
        assert caplog.record_tuples == []

        # The get() method does not raise KeyError and does not log an error
        assert manifest.get('does-not-exist.css') is None
        assert caplog.record_tuples == []
