# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals

import unittest

from coaster.db import db
from coaster.gfm import markdown
from coaster.sqlalchemy import BaseMixin, MarkdownColumn

from .test_sqlalchemy_models import app1, app2


class MarkdownData(BaseMixin, db.Model):
    __tablename__ = 'md_data'
    value = MarkdownColumn('value', nullable=False)


class MarkdownHtmlData(BaseMixin, db.Model):
    __tablename__ = 'md_html_data'
    value = MarkdownColumn('value', nullable=False, options={'html': True})


def fake_markdown(text):
    return 'fake-markdown'


class FakeMarkdownData(BaseMixin, db.Model):
    __tablename__ = 'fake_md_data'
    value = MarkdownColumn('value', nullable=False, markdown=fake_markdown)


# -- Tests --------------------------------------------------------------------


class TestMarkdownColumn(unittest.TestCase):
    app = app1

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_markdown_column(self):
        text = """# this is going to be h1.\n- Now a list. \n- 1\n- 2\n- 3"""
        data = MarkdownData(value=text)
        self.session.add(data)
        self.session.commit()
        assert data.value.html == markdown(text)
        assert data.value.text == text
        assert data.value.__str__() == text
        assert data.value.__html__() == markdown(text)

    def test_does_not_render_on_load(self):
        text = "This is the text"
        real_html = markdown(text)
        fake_html = "This is not the text"
        data = MarkdownData(value=text)
        self.session.add(data)

        # Insert fake rendered data for commit to db
        data.value._html = fake_html
        data.value.changed()
        self.session.commit()
        del data

        # Reload from db and confirm HTML is exactly as committed
        data = MarkdownData.query.first()
        assert data.value.text == text
        assert data.value.html == fake_html
        assert data.value.__str__() == text
        assert data.value.__html__() == fake_html

        # Edit text and confirm HTML was regenerated, saved and reloaded
        data.value.text = text
        db.session.commit()
        del data

        data = MarkdownData.query.first()
        assert data.value.text == text
        assert data.value.html == real_html
        assert data.value.__str__() == text
        assert data.value.__html__() == real_html

    def test_raw_value(self):
        text = "This is the text"
        data = MarkdownData()
        self.session.add(data)
        data.value = text
        self.session.commit()

    def test_empty_value(self):
        doc = MarkdownData(value=None)
        assert not doc.value
        assert doc.value.text is None
        assert doc.value.html == ''

    def test_html_customization(self):
        """Markdown columns may specify custom Markdown processor options."""
        text = "Allow <b>some</b> HTML"
        d1 = MarkdownData(value=text)
        d2 = MarkdownHtmlData(value=text)

        assert d1.value.text == d2.value.text
        assert d1.value != d2.value
        assert d1.value.html == '<p>Allow &lt;b&gt;some&lt;/b&gt; HTML</p>'
        assert d2.value.html == '<p>Allow <b>some</b> HTML</p>'

    def test_custom_markdown_processor(self):
        """Markdown columns may specify their own markdown processor."""
        doc = FakeMarkdownData(value="This is some text")
        assert doc.value.text == "This is some text"
        assert doc.value.html == 'fake-markdown'


class TestMarkdownColumn2(TestMarkdownColumn):
    app = app2
