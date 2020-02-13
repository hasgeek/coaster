# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import six

import unittest

from coaster.gfm import markdown

sample_markdown = '''
This is a sample piece of text and represents a paragraph.

This is the second paragraph.
It has a newline break here.

Here is some **bold text** and some *emphasized text*. It also works with __bold text__ and _emphasized text_.

In addition, we support ^^insertions^^, ~~deletions~~ and ==markers==.

Innocuous HTML tags are allowed when `html=True` is used: <b>Hello!</b>

Dangerous tags are always removed: <script>window.alert('Hello!')</script>

A list:

2. Starts at two, because why not?
3. 2^10^ = 1024
4. Water is H~2~0
5. :smile:
6. Symbols (ignored): (tm) (c) (r) c/o
7. Symbols (converted): +/- --> <-- <--> =/= 1/2 1/4 1st 2nd 3rd 4th 42nd

A naked link: https://www.example.com/

An [inline link](https://www.example.com/)

```python hl_lines="1"
def foo():
    return 'https://www.example.com/'
```

| Item      | Value |
| --------- | -----:|
| Computer  | $1600 |
| Phone     |   $12 |
| Pipe      |    $1 |

| Function name | Description                    |
| ------------- | ------------------------------ |
| `help()`      | Display the help window.       |
| `destroy()`   | **Destroy your computer!**     |
'''

sample_output = '''
<p>This is a sample piece of text and represents a paragraph.</p>
<p>This is the second paragraph.<br>
It has a newline break here.</p>
<p>Here is some <strong>bold text</strong> and some <em>emphasized text</em>. It also works with <strong>bold text</strong> and <em>emphasized text</em>.</p>
<p>In addition, we support <ins>insertions</ins>, <del>deletions</del> and <mark>markers</mark>.</p>
<p>Innocuous HTML tags are allowed when <code>html=True</code> is used: &lt;b&gt;Hello!&lt;/b&gt;</p>
<p>Dangerous tags are always removed: &lt;script&gt;window.alert(‘Hello!’)&lt;/script&gt;</p>
<p>A list:</p>
<ol start="2">
<li>Starts at two, because why not?</li>
<li>2<sup>10</sup> = 1024</li>
<li>Water is H<sub>2</sub>0</li>
<li>😄</li>
<li>Symbols (ignored): (tm) (c) (r) c/o</li>
<li>Symbols (converted): ± → ← ↔ ≠ ½ ¼ 1<sup>st</sup> 2<sup>nd</sup> 3<sup>rd</sup> 4<sup>th</sup> 42<sup>nd</sup></li>
</ol>
<p>A naked link: <a href="https://www.example.com/" rel="nofollow">https://www.example.com/</a></p>
<p>An <a href="https://www.example.com/" rel="nofollow">inline link</a></p>
<div class="codehilite"><pre><span></span><code><span class="hll"><span class="k">def</span> <span class="nf">foo</span><span class="p">():</span>
</span>    <span class="k">return</span> <span class="s1">'https://www.example.com/'</span>
</code></pre></div>

<table>
<thead>
<tr>
<th>Item</th>
<th align="right">Value</th>
</tr>
</thead>
<tbody>
<tr>
<td>Computer</td>
<td align="right">$1600</td>
</tr>
<tr>
<td>Phone</td>
<td align="right">$12</td>
</tr>
<tr>
<td>Pipe</td>
<td align="right">$1</td>
</tr>
</tbody>
</table>
<table>
<thead>
<tr>
<th>Function name</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td><code>help()</code></td>
<td>Display the help window.</td>
</tr>
<tr>
<td><code>destroy()</code></td>
<td><strong>Destroy your computer!</strong></td>
</tr>
</tbody>
</table>
'''.strip()

sample_output_html = '''
<p>This is a sample piece of text and represents a paragraph.</p>
<p>This is the second paragraph.<br>
It has a newline break here.</p>
<p>Here is some <strong>bold text</strong> and some <em>emphasized text</em>. It also works with <strong>bold text</strong> and <em>emphasized text</em>.</p>
<p>In addition, we support <ins>insertions</ins>, <del>deletions</del> and <mark>markers</mark>.</p>
<p>Innocuous HTML tags are allowed when <code>html=True</code> is used: <b>Hello!</b></p>
<p>Dangerous tags are always removed: window.alert(&lsquo;Hello!&rsquo;)</p>
<p>A list:</p>
<ol start="2">
<li>Starts at two, because why not?</li>
<li>2<sup>10</sup> = 1024</li>
<li>Water is H<sub>2</sub>0</li>
<li>😄</li>
<li>Symbols (ignored): (tm) (c) (r) c/o</li>
<li>Symbols (converted): &plusmn; &rarr; &larr; &harr; &ne; &frac12; &frac14; 1<sup>st</sup> 2<sup>nd</sup> 3<sup>rd</sup> 4<sup>th</sup> 42<sup>nd</sup></li>
</ol>
<p>A naked link: <a href="https://www.example.com/" rel="nofollow">https://www.example.com/</a></p>
<p>An <a href="https://www.example.com/" rel="nofollow">inline link</a></p>
<pre><code>def foo():
    return &#39;https://www.example.com/&#39;
</code></pre>

<table>
<thead>
<tr>
<th>Item</th>
<th align="right">Value</th>
</tr>
</thead>
<tbody>
<tr>
<td>Computer</td>
<td align="right">$1600</td>
</tr>
<tr>
<td>Phone</td>
<td align="right">$12</td>
</tr>
<tr>
<td>Pipe</td>
<td align="right">$1</td>
</tr>
</tbody>
</table>
<table>
<thead>
<tr>
<th>Function name</th>
<th>Description</th>
</tr>
</thead>
<tbody>
<tr>
<td><code>help()</code></td>
<td>Display the help window.</td>
</tr>
<tr>
<td><code>destroy()</code></td>
<td><strong>Destroy your computer!</strong></td>
</tr>
</tbody>
</table>
'''.strip()


if six.PY2:
    # Pygments >= 2.4 (latest Py3 releases only) inserts "<code>" alongside "<pre>"
    # We strip it out under the older release in Py2. This is a hack.
    sample_output = (
        sample_output.replace('<pre><code>', '<pre>')
        .replace('</code></pre>', '</pre>')
        .replace('<pre><span></span><code>', '<pre><span></span>')
    )
    sample_output_html = (
        sample_output_html.replace('<pre><code>', '<pre>')
        .replace('</code></pre>', '</pre>')
        .replace('<pre><span></span><code>', '<pre><span></span>')
    )


class TestMarkdown(unittest.TestCase):
    def test_markdown(self):
        """Markdown rendering"""
        assert markdown('hello') == '<p>hello</p>'

    def test_text_markdown(self):
        """Markdown rendering with HTML disabled (default)"""
        assert (
            markdown('hello <del>there</del>')
            == '<p>hello &lt;del&gt;there&lt;/del&gt;</p>'
        )

    def test_html_markdown(self):
        """Markdown rendering with HTML enabled"""
        assert (
            markdown('hello <del>there</del>', html=True)
            == '<p>hello <del>there</del></p>'
        )

    def test_empty_markdown(self):
        """Don't choke on None"""
        assert markdown(None) is None

    def test_sample_markdown(self):
        assert markdown(sample_markdown) == sample_output

    def test_sample_markdown_html(self):
        # In HTML mode, many characters are converted to HTML entities (by Bleach; side effect),
        # and code highlighting is dropped, as we cannot safely distinguish between markdown
        # highlighting and malicious user input.
        assert markdown(sample_markdown, html=True) == sample_output_html
