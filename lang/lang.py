import json

from urllib.request import urlopen
from urllib.error import HTTPError, URLError

from bidict import bidict
from bs4 import BeautifulSoup


WIKI_EN_URL = 'https://en.wiktionary.org'


def get_lang_data(fn='lang.json'):
    '''Create a LANGUAGE_DATA dict, write it to `fn`, and return in.

    LANGUAGE_DATA maps language codes (e.g., 'fi') to dictionaries containing
    the given language's name (e.g., 'Finnish'), a link to the language's
    lemmas on the English Wiktionary, and, if available, a link to the
    language's Wiktionary:

        LANGUAGE_DATA = {
            "fi": {
                "language": "Finnish",
                "lemmas", "https://...",
                "wiki": "https://...",
            }
        }

    LANGUAGE_DATA only includes the languages with two-letter language codes
    covered on Wiktionary:
        https://en.wiktionary.org/wiki/Wiktionary:List_of_languages

    LANGUAGE_DATA is dumped to a json file named `fn`.
    '''
    lang_list = 'https://en.wiktionary.org/wiki/Wiktionary:List_of_languages'
    table = BeautifulSoup(urlopen(lang_list), 'html.parser') \
        .find('span', id='Two-letter_codes').parent \
        .find_next_sibling('table')

    LANGUAGE_DATA = {}

    for row in table.find_all('tr')[1:]:  # skip header row
        code_tag = row.find('code')
        code = code_tag.text  # two-letter language code

        lang_tag = code_tag.parent.find_next_sibling('td')
        language = lang_tag.text.replace('\n', '')
        lemmas = WIKI_EN_URL + lang_tag.find('a').get('href') \
            .replace('_language', '_lemmas')

        LANGUAGE_DATA[code] = {'language': language, 'lemmas': lemmas}

        try:
            wiki_url = 'https://%s.wiktionary.org' % code
            page = BeautifulSoup(urlopen(wiki_url), 'html.parser')

            if 'This wiki has been closed' not in page.text:
                LANGUAGE_DATA[code]['wiki'] = wiki_url + '/wiki/'

        except (HTTPError, URLError):
            continue

    with open(fn, 'w+') as f:
        json.dump(LANGUAGE_DATA, f, indent=4)

    return LANGUAGE_DATA


def get_wiki_languages(LANGUAGE_DATA):
    '''Create a bidict WIKI_LANGUAGES mapping language codes to language names.

    E.g.,
            >>> WIKI_LANGUAGES['fi']
            'Finnish'

            >>> WIKI_LANGUAGES.inv['Finnish']
            'fi'
    '''
    return bidict({k: v['language'] for k, v in LANGUAGE_DATA.items()})


if __name__ == '__main__':
    get_lang_data()
