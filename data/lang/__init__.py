__all__ = ['LANGUAGE_DATA', 'WIKI_EN_URL', 'WIKI_LANGUAGES']


import json
import os

from .lang import get_lang_data, get_wiki_languages, WIKI_EN_URL

try:
    with open(os.path.dirname(__file__) + '/lang.json', 'r+') as f:
        LANGUAGE_DATA = json.load(f)

except FileNotFoundError:
    LANGUAGE_DATA = get_lang_data()

WIKI_LANGUAGES = get_wiki_languages(LANGUAGE_DATA)
