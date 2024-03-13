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

from __future__ import annotations

from collections.abc import Iterable

import nltk


def extract_named_entities(text_blocks: Iterable[str]) -> set[str]:
    """Return a set of named entities extracted from the provided text blocks."""
    sentences = []
    for text in text_blocks:
        sentences.extend(nltk.sent_tokenize(text))

    tokenized_sentences = [nltk.word_tokenize(sentence) for sentence in sentences]
    tagged_sentences = [nltk.pos_tag(sentence) for sentence in tokenized_sentences]
    chunked_sentences = nltk.ne_chunk_sents(tagged_sentences, binary=True)

    def extract_entity_names(tree: nltk.Tree) -> list[str]:
        entity_names = []

        if hasattr(tree, 'label'):
            if tree.label() == 'NE':
                entity_names.append(' '.join(child[0] for child in tree))
            else:
                for child in tree:
                    entity_names.extend(extract_entity_names(child))

        return entity_names

    entity_names = []
    for tree in chunked_sentences:
        entity_names.extend(extract_entity_names(tree))

    return set(entity_names)
