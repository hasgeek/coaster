from coaster.gfm import markdown

sample_markdown = '''
This is a sample piece of text and represents a paragraph.

This is the second paragraph.
It has a newline break here.

Here is some **bold text** and some *emphasized text*. It also works with __bold text__ and _emphasized text_.

In addition, we support ^^insertions^^, ~~deletions~~ and ==markers==.

Innocuous HTML tags are allowed when `html=True` is used: <b>Hello!</b>

Dangerous tags are always removed: <script>window.alert('Hello!')</script>

#This is not a header

# This is a header in text-only mode

### This is a header in HTML and text mode

A list:

2. Starts at two, because why not?
3. 2^10^ = 1024
4. Water is H~2~O
5. :smile:
6. Symbols (ignored): (tm) (c) (r) c/o
7. Symbols (converted): +/- --> <-- <--> =/= 1/2 1/4 1st 2nd 3rd 4th 42nd

An [inline link](https://www.example.com/)

A naked link: https://www.example.com/

Un-prefixed naked links: hasgeek.in python.py

Python/Paraguay link, prefixed: http://python.py

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
<p>Dangerous tags are always removed: &lt;script&gt;window.alert(&lsquo;Hello!&rsquo;)&lt;/script&gt;</p>
<p>#This is not a header</p>
<h1>This is a header in text-only mode</h1>
<h3>This is a header in HTML and text mode</h3>
<p>A list:</p>
<ol start="2">
<li>Starts at two, because why not?</li>
<li>2<sup>10</sup> = 1024</li>
<li>Water is H<sub>2</sub>O</li>
<li>😄</li>
<li>Symbols (ignored): (tm) (c) (r) c/o</li>
<li>Symbols (converted): &plusmn; &rarr; &larr; &harr; &ne; &frac12; &frac14; 1<sup>st</sup> 2<sup>nd</sup> 3<sup>rd</sup> 4<sup>th</sup> 42<sup>nd</sup></li>
</ol>
<p>An <a href="https://www.example.com/" rel="nofollow">inline link</a></p>
<p>A naked link: <a href="https://www.example.com/" rel="nofollow">https://www.example.com/</a></p>
<p>Un-prefixed naked links: <a href="http://hasgeek.in" rel="nofollow">hasgeek.in</a> python.py</p>
<p>Python/Paraguay link, prefixed: <a href="http://python.py" rel="nofollow">http://python.py</a></p>
<div class="highlight"><pre><span></span><code><span class="hll"><span class="k">def</span> <span class="nf">foo</span><span class="p">():</span>
</span>    <span class="k">return</span> <span class="s1">&amp;#39;https://www.example.com/&amp;#39;</span>
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
<p>#This is not a header</p>

This is a header in text-only mode
<h3>This is a header in HTML and text mode</h3>
<p>A list:</p>
<ol start="2">
<li>Starts at two, because why not?</li>
<li>2<sup>10</sup> = 1024</li>
<li>Water is H<sub>2</sub>O</li>
<li>😄</li>
<li>Symbols (ignored): (tm) (c) (r) c/o</li>
<li>Symbols (converted): &plusmn; &rarr; &larr; &harr; &ne; &frac12; &frac14; 1<sup>st</sup> 2<sup>nd</sup> 3<sup>rd</sup> 4<sup>th</sup> 42<sup>nd</sup></li>
</ol>
<p>An <a href="https://www.example.com/" rel="nofollow">inline link</a></p>
<p>A naked link: <a href="https://www.example.com/" rel="nofollow">https://www.example.com/</a></p>
<p>Un-prefixed naked links: <a href="http://hasgeek.in" rel="nofollow">hasgeek.in</a> python.py</p>
<p>Python/Paraguay link, prefixed: <a href="http://python.py" rel="nofollow">http://python.py</a></p>

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


def test_markdown():
    """Markdown rendering."""
    assert markdown('hello') == '<p>hello</p>'


def test_text_markdown():
    """Markdown rendering with HTML disabled (default)."""
    assert (
        markdown('hello <del>there</del>')
        == '<p>hello &lt;del&gt;there&lt;/del&gt;</p>'
    )


def test_html_markdown():
    """Markdown rendering with HTML enabled."""
    assert (
        markdown('hello <del>there</del>', html=True) == '<p>hello <del>there</del></p>'
    )


def test_markdown_javascript_link():
    """Markdown rendering should strip `javascript:` protocol links."""
    # Markdown's link processor can't handle `javascript:alert("Hello")` so it loses
    # link3 entirely, mashing it into link2.
    assert markdown(
        '[link1](http://example.com) '
        '[link2](javascript:alert(document.cookie) '
        '[link3](javascript:alert("Hello"))'
    ) == (
        '<p><a href="http://example.com" rel="nofollow">link1</a> '
        '<a title="Hello">link2</a>)</p>'
    )


def test_markdown_javascript_link_html():
    """Markdown rendering should strip `javascript:` protocol links."""
    # Markdown's link processor can't handle `javascript:alert("Hello")` so it loses
    # link3 entirely, mashing it into link2.
    assert markdown(
        '[link1](http://example.com) '
        '[link2](javascript:alert(document.cookie) '
        '[link3](javascript:alert("Hello"))',
        html=True,
    ) == (
        '<p><a href="http://example.com" rel="nofollow">link1</a> '
        '<a title="Hello">link2</a>)</p>'
    )


def test_empty_markdown():
    """Don't choke on None."""
    assert markdown(None) is None


def test_sample_markdown():
    """Confirm sample Markdown rendering is stable."""
    assert markdown(sample_markdown) == sample_output


def test_sample_markdown_html():
    """Confirm sample Markdown rendering in HTML mode is stable."""
    # In HTML mode, many characters are converted to HTML entities (by Bleach; side
    # effect), and Pygments code highlighting is dropped, as we cannot safely
    # distinguish between markdown highlighting and malicious user input.
    assert markdown(sample_markdown, html=True) == sample_output_html


linkify_text = '''
This is a naked link in a line: https://example.com

This is a Markdown link in a line. <https://example.com>

This is an unprefixed link: example.com
'''.strip()

linkify_html = '''
<p>This is a naked link in a line: <a href="https://example.com" rel="nofollow">https://example.com</a></p>
<p>This is a Markdown link in a line. <a href="https://example.com" rel="nofollow">https://example.com</a></p>
<p>This is an unprefixed link: <a href="http://example.com" rel="nofollow">example.com</a></p>
'''.strip()

nolinkify_html = '''
<p>This is a naked link in a line: https://example.com</p>
<p>This is a Markdown link in a line. <a href="https://example.com">https://example.com</a></p>
<p>This is an unprefixed link: example.com</p>
'''.strip()


def test_linkify():
    """Optional Linkify flag controls linkification."""
    # Linkify is also responsible for adding `nofollow` on all links
    assert markdown(linkify_text) == linkify_html
    assert markdown(linkify_text, linkify=True) == linkify_html
    assert markdown(linkify_text, linkify=False) == nolinkify_html
