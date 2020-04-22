# -*- coding: utf-8 -*-

import six

import unittest

import pytest

from coaster.assets import AssetNotFound, UglipyJS, Version, VersionedAssets


class TestAssets(unittest.TestCase):
    def setUp(self):
        self.assets = VersionedAssets()
        self.assets['jquery.js'][Version('1.7.1')] = 'jquery-1.7.1.js'
        self.assets['jquery.js'][Version('1.8.3')] = 'jquery-1.8.3.js'
        self.assets['jquery.some.js'][Version('1.8.3')] = {
            'provides': 'jquery.js',
            'requires': 'jquery.js',
            'bundle': None,
        }
        self.assets['jquery.form.js'][Version('2.96.0')] = (
            'jquery.js',
            'jquery.form-2.96.js',
        )
        self.assets['jquery.form.1.js'][Version('2.96.0')] = {
            'requires': 'jquery.js>=1.8.3',
            'provides': 'jquery.form.js',
        }
        self.assets['old-lib.js'][Version('1.0.0')] = (
            'jquery.js<1.8.0',
            'old-lib-1.0.0.js',
        )

    def test_asset_unversioned(self):
        bundle = self.assets.require('jquery.js')
        assert bundle.contents == ('jquery-1.8.3.js',)

    def test_asset_versioned(self):
        bundle = self.assets.require('jquery.js==1.7.1')
        assert bundle.contents == ('jquery-1.7.1.js',)
        bundle = self.assets.require('jquery.js<1.8.0')
        assert bundle.contents == ('jquery-1.7.1.js',)
        bundle = self.assets.require('jquery.js>=1.8.0')
        assert bundle.contents == ('jquery-1.8.3.js',)

    def test_missing_asset(self):
        with pytest.raises(AssetNotFound):
            self.assets.require('missing.js')

    def test_single_requires(self):
        bundle = self.assets.require('jquery.form.js')
        assert bundle.contents == ('jquery-1.8.3.js', 'jquery.form-2.96.js')

    def test_single_requires_which_is_dict(self):
        bundle = self.assets.require('jquery.form.1.js')
        assert bundle.contents == ('jquery-1.8.3.js',)

    def test_provides_requires(self):
        bundle = self.assets.require('jquery.some.js', 'jquery.form.js')
        assert bundle.contents == ('jquery-1.8.3.js', 'jquery.form-2.96.js')

    def test_version_copies(self):
        # First asset will load highest available version of the requirement, which conflicts
        # with the second requested version. The same asset can't be requested twice
        with pytest.raises(ValueError):
            self.assets.require('jquery.form.js', 'jquery.js==1.7.1')

    def test_version_conflict(self):
        # First asset will load highest available version of the requirement, which conflicts
        # with the second requested version. The same asset can't be requested twice
        with pytest.raises(ValueError):
            self.assets.require('jquery.form.js', 'old-lib.js')

    def test_blacklist(self):
        bundle = self.assets.require('!jquery.js', 'jquery.form.js')
        assert bundle.contents == ('jquery.form-2.96.js',)
        bundle = self.assets.require('jquery.form.js', '!jquery.js')
        assert bundle.contents == ('jquery.form-2.96.js',)

    def test_uglipyjs(self):
        """Test the UglipyJS filter"""
        infile = six.StringIO(
            """
            function test() {
              alert("Hello, world!");
            };
            """
        )
        outfile = six.StringIO()
        afilter = UglipyJS()
        afilter.setup()
        afilter.output(infile, outfile)
        assert outfile.getvalue() == 'function test(){alert("Hello, world!")};'
