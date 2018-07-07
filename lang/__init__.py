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


def get_lang_and_code(lang):
    '''Determine the language name and 2-letter code of `lang`.'''
    try:
        # if `lang` is a language code
        code = lang.lower()
        lang = WIKI_LANGUAGES[code]

    except KeyError:

        try:
            # if `lang` is the name of a language
            lang = lang.title()
            code = WIKI_LANGUAGES.inv[lang]

        except KeyError:
            raise NameError('Unsupported language: %s.' % lang)

    return lang, code
