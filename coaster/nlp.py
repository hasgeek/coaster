# -*- coding: utf-8 -*-

"""
Natural language processing
===========================

Provides a wrapper around NLTK to extract named entities from HTML text::

    from coaster.utils import text_blocks
    from coaster.nlp import extract_named_entities

    html = "<p>This is some HTML-formatted text.</p><p>In two paragraphs.</p>"
    textlist = text_blocks(html)  # Returns a list of paragraphs.
    entities = extract_named_entities(textlist)
"""

import nltk
from .utils import text_blocks as extract_text_blocks  # XXX: Deprecated  # NOQA


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
