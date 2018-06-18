import json

from urllib.request import urlopen
from urllib.error import HTTPError, URLError

from bs4 import BeautifulSoup


EN_URL = 'https://en.wiktionary.org'

WIKI_URL = 'https://%s.wiktionary.org/wiki/'

LANGUAGE_LIST = 'https://en.wiktionary.org/wiki/Wiktionary:List_of_languages'


def curate_languages(fn='lang.json'):
    ''' '''
    table = BeautifulSoup(urlopen(LANGUAGE_LIST), 'html.parser') \
        .find('span', id='Two-letter_codes').parent \
        .find_next_sibling('table')

    languages = {}

    for row in table.find_all('tr')[1:]:  # skip header row
        code_tag = row.find('code')
        code = code_tag.text  # two-letter language code

        lang_tag = code_tag.parent.find_next_sibling('td')
        language = lang_tag.text.replace('\n', '')
        lemmas = EN_URL + lang_tag.find('a').get('href') \
            .replace('_language', '_lemmas')

        languages[code] = {'language': language, 'lemmas': lemmas}

        try:
            wiki_url = WIKI_URL % code
            page = BeautifulSoup(urlopen(wiki_url), 'html.parser')

            if 'This wiki has been closed' not in page.text:
                languages[code]['wiki'] = wiki_url

        except (HTTPError, URLError):
            continue

    with open(fn, 'w+') as f:
        json.dump(languages, f, indent=4)


if __name__ == '__main__':
    curate_languages()
