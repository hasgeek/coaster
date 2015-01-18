# -*- coding: utf-8 -*-

import nltk
import html5lib

__all__ = []

blockish_tags = set([
    'address', 'article', 'aside', 'audio', 'blockquote', 'canvas', 'dd', 'div', 'dl', 'dt', 'fieldset', 'figcaption',
    'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'li', 'noscript', 'ol',
    'output', 'p', 'pre', 'section', 'table', 'td', 'tfoot', 'th', 'tr', 'ul', 'video'])


def extract_text_blocks(html_text, skip_pre=True):
    # doc = html.fromstring(html_text)
    doc = html5lib.parseFragment(html_text)
    text_blocks = []

    def subloop(parent_tag, element, lastchild=False):
        if callable(element.tag):  # Comments have a callable tag. TODO: Find out, anything else?
            tag = '<!-->'
            text = ''
            tail = element.tail or u''
        else:
            tag = element.tag.split('}')[-1]  # Extract tag from namespace: {http://www.w3.org/1999/xhtml}html
            text = element.text or u''
            tail = element.tail or u''

        if tag == 'pre' and skip_pre:
            text = u''

        if tag in blockish_tags or tag == 'DOCUMENT_FRAGMENT':
            text = text.lstrip()  # Leading whitespace is insignificant in a block tag
            if not len(element):
                text = text.rstrip()  # No children? Then trailing whitespace is insignificant
            # If there's text, add it.
            # If there's no text but the next element is not a block tag, add a blank anyway
            # (unless it's a pre tag and we want to skip_pre, in which case ignore it again).
            if text:
                text_blocks.append(text)
            elif (len(element) and isinstance(element[0].tag, basestring) and
                    element[0].tag.split('}')[-1] not in blockish_tags and not (skip_pre and tag == 'pre')):
                text_blocks.append('')
        else:
            if not text_blocks:
                if text:
                    text_blocks.append(text)
            else:
                text_blocks[-1] += text

        if len(element) > 0 and not (skip_pre and tag == 'pre'):
            for child in element[:-1]:
                subloop(tag, child)
            subloop(tag, element[-1], lastchild=True)

        if tag in blockish_tags:
            tail = tail.lstrip()  # Leading whitespace is insignificant after a block tag
            if tail:
                text_blocks.append(tail)
        else:
            if parent_tag in blockish_tags and lastchild:
                tail = tail.rstrip()  # Trailing whitespace is insignificant before a block tag end
            if not text_blocks:
                if tail:
                    text_blocks.append(tail)
            else:
                if tag == 'br' and tail:
                    text_blocks[-1] += '\n' + tail
                else:
                    text_blocks[-1] += tail

    subloop(None, doc)
    # Replace &nbsp; with ' '
    text_blocks = [t.replace(u'\xa0', ' ') for t in text_blocks]
    return text_blocks


def extract_named_entities(text_blocks):
    """
    Return a list of named entities extracted from provided text blocks (list of text strings).
    """
    sentences = []
    for text in text_blocks:
        sentences.extend(nltk.sent_tokenize(text))

    tokenized_sentences = [nltk.word_tokenize(sentence) for sentence in sentences]
    tagged_sentences = [nltk.pos_tag(sentence) for sentence in tokenized_sentences]
    chunked_sentences = nltk.ne_chunk_sents(tagged_sentences, binary=True)

    def extract_entity_names(t):
        entity_names = []

        if hasattr(t, 'label'):
            if t.label() == 'NE':
                entity_names.append(' '.join([child[0] for child in t]))
            else:
                for child in t:
                    entity_names.extend(extract_entity_names(child))

        return entity_names

    entity_names = []
    for tree in chunked_sentences:
        entity_names.extend(extract_entity_names(tree))

    return set(entity_names)
