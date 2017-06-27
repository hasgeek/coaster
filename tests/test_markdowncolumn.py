# -*- coding: utf-8 -*-

from __future__ import absolute_import

import unittest

from coaster.db import db
from coaster.gfm import markdown
from coaster.sqlalchemy import BaseMixin, MarkdownColumn

from .test_models import app1, app2


class MarkdownData(BaseMixin, db.Model):
    __tablename__ = 'md_data'
    value = MarkdownColumn('value', nullable=False)


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
        text = u"""# this is going to be h1.\n- Now a list. \n- 1\n- 2\n- 3"""
        data = MarkdownData(value=text)
        self.session.add(data)
        self.session.commit()
        self.assertEqual(data.value.html, markdown(text))
        self.assertEqual(data.value.text, text)
        self.assertEqual(data.value.__str__(), text)
        self.assertEqual(data.value.__html__(), markdown(text))

    def test_does_not_render_on_load(self):
        text = u"This is the text"
        real_html = markdown(text)
        fake_html = u"This is not the text"
        data = MarkdownData(value=text)
        self.session.add(data)

        # Insert fake rendered data for commit to db
        data.value._html = fake_html
        data.value.changed()
        self.session.commit()
        del data

        # Reload from db and confirm HTML is exactly as committed
        data = MarkdownData.query.first()
        self.assertEqual(data.value.text, text)
        self.assertEqual(data.value.html, fake_html)
        self.assertEqual(data.value.__str__(), text)
        self.assertEqual(data.value.__html__(), fake_html)

        # Edit text and confirm HTML was regenerated, saved and reloaded
        data.value.text = text
        db.session.commit()
        del data

        data = MarkdownData.query.first()
        self.assertEqual(data.value.text, text)
        self.assertEqual(data.value.html, real_html)
        self.assertEqual(data.value.__str__(), text)
        self.assertEqual(data.value.__html__(), real_html)

    def test_raw_value(self):
        text = u"This is the text"
        data = MarkdownData()
        self.session.add(data)
        data.value = text
        self.session.commit()


class TestMarkdownColumn2(TestMarkdownColumn):
    app = app2
