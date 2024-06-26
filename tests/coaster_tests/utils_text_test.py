"""Tests for text utilities."""

from coaster.utils import text_blocks

sample_html = """
This is some <em>sample</em> HTML<br>with various features.
<p>
  Here we have a paragraph&nbsp;with <a href="#">a link</a> embedded
  inside it.
</p>
<p>
  Let&rsquo;s make a list:
</p>
<ol>
  <li>This is the first item.</li>
  <li><p>Second item has a paragraph.</p></li>
</ol>
<pre>
  Ignore all <em>of</em> this.
</pre>
<p>
  Now for some fun, let's <!-- not? --> have a comment.
</p>
<p>
  <a href="#" class="btn">Submit</a> or
  <a href="#" class="btn">Cancel</a>
</p>
<DIV>
  Don't forget the capitalised tags.
</DIV>
"""

sample_text_blocks = [
    'This is some sample HTML\nwith various features.\n',
    'Here we have a paragraph with a link embedded\n  inside it.',
    'Let\u2019s make a list:',
    'This is the first item.',
    'Second item has a paragraph.',
    "Now for some fun, let's  have a comment.",
    "Submit or\n  Cancel",
    "Don't forget the capitalised tags.",
]


def test_extract_text() -> None:
    tb = text_blocks(sample_html, skip_pre=True)
    assert tb == sample_text_blocks
