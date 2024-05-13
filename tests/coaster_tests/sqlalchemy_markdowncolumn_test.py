"""Test Markdown composite column."""

from typing import Optional

from coaster.sqlalchemy import BaseMixin, MarkdownColumn
from coaster.utils import markdown

from .conftest import AppTestCase, Model, db


class MarkdownData(BaseMixin, Model):
    __tablename__ = 'md_data'
    __allow_unmapped__ = True  # Required for value_text and value_html without Mapped[]

    value = MarkdownColumn('value', nullable=False)
    value_text: Optional[str]
    value_html: Optional[str]


class MarkdownHtmlData(BaseMixin, Model):
    __tablename__ = 'md_html_data'
    __allow_unmapped__ = True  # Required for value_text and value_html without Mapped[]

    value = MarkdownColumn('value', nullable=False, options={'html': True})
    value_text: Optional[str]
    value_html: Optional[str]


def fake_markdown(_text: str) -> str:
    return 'fake-markdown'


class FakeMarkdownData(BaseMixin, Model):
    __tablename__ = 'fake_md_data'
    __allow_unmapped__ = True  # Required for value_text and value_html without Mapped[]

    value = MarkdownColumn('value', nullable=False, markdown=fake_markdown)
    value_text: Optional[str]
    value_html: Optional[str]


# -- Tests --------------------------------------------------------------------


class TestMarkdownColumn(AppTestCase):
    def test_markdown_column(self) -> None:
        # pylint: disable=unnecessary-dunder-call
        text = """# this is going to be h1.\n- Now a list. \n- 1\n- 2\n- 3"""
        data = MarkdownData(value=text)
        self.session.add(data)
        self.session.commit()
        assert data.value.html == markdown(text)
        assert data.value.text == text
        assert data.value.__str__() == text
        assert data.value.__html__() == markdown(text)

    def test_does_not_render_on_load(self) -> None:
        # pylint: disable=unnecessary-dunder-call
        text = "This is the text"
        real_html = markdown(text)
        fake_html = "This is not the text"
        data1 = MarkdownData(value=text)
        self.session.add(data1)

        # Insert fake rendered data for commit to db
        data1.value._html = fake_html  # pylint: disable=protected-access
        data1.value.changed()
        self.session.commit()
        del data1

        # Reload from db and confirm HTML is exactly as committed
        data2 = MarkdownData.query.first()
        assert data2 is not None
        assert data2.value.text == text
        assert data2.value.html == fake_html
        assert data2.value.__str__() == text
        assert data2.value.__html__() == fake_html

        # Edit text and confirm HTML was regenerated, saved and reloaded
        data2.value.text = text
        db.session.commit()
        del data2

        data3 = MarkdownData.query.first()
        assert data3 is not None
        assert data3.value.text == text
        assert data3.value.html == real_html
        assert data3.value.__str__() == text
        assert data3.value.__html__() == real_html

    def test_raw_value(self) -> None:
        text = "This is the text"
        data = MarkdownData()
        self.session.add(data)
        # If the composite is assigned a text value, it'll be coerced into a composite
        data.value = text  # type: ignore[assignment]
        self.session.commit()
        assert data.value.text == text
        assert data.value.html == '<p>' + text + '</p>'

    def test_none_value(self) -> None:
        doc = MarkdownData(value=None)
        assert not doc.value
        assert doc.value.text is None
        assert doc.value_text is None
        assert doc.value.html is None
        assert doc.value_html is None
        assert str(doc.value) == ''
        assert doc.value.__html__() == ''

    def test_empty_value(self) -> None:
        doc = MarkdownData(value='')
        assert not doc.value
        assert doc.value.text == ''
        assert doc.value_text == ''
        assert doc.value.html == ''
        assert doc.value_html == ''

    def test_nonstr_value(self) -> None:
        doc = MarkdownData(value=1)
        assert doc.value.text == '1'
        assert doc.value_text == '1'
        assert doc.value.html == '<p>1</p>'
        assert doc.value_html == '<p>1</p>'

    def test_html_customization(self) -> None:
        """Markdown columns may specify custom Markdown processor options."""
        text = "Allow <b>some</b> HTML"
        d1 = MarkdownData(value=text)
        d2 = MarkdownHtmlData(value=text)

        assert d1.value.text == d2.value.text
        assert d1.value != d2.value
        assert d1.value.html == '<p>Allow &lt;b&gt;some&lt;/b&gt; HTML</p>'
        assert d2.value.html == '<p>Allow <b>some</b> HTML</p>'

    def test_custom_markdown_processor(self) -> None:
        """Markdown columns may specify their own markdown processor."""
        doc = FakeMarkdownData(value="This is some text")
        assert doc.value.text == "This is some text"
        assert doc.value.html == 'fake-markdown'
