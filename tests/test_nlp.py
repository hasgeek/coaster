import unittest
from coaster.nlp import extract_text_blocks


sample_html = u"""
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
    u'This is some sample HTML\nwith various features.\n',
    u'Here we have a paragraph with a link embedded\n  inside it.',
    u'Let\u2019s make a list:',
    u'This is the first item.',
    u'Second item has a paragraph.',
    u"Now for some fun, let's  have a comment.",
    u"Submit or\n  Cancel",
    u"Don't forget the capitalised tags.",
    ]


class TestExtractText(unittest.TestCase):
    def test_extract_text(self):
        text_blocks = extract_text_blocks(sample_html, skip_pre=True)
        self.assertEqual(text_blocks, sample_text_blocks)
