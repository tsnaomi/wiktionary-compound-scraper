import re

from os.path import commonprefix
from sys import stderr
from urllib.error import HTTPError
from urllib.request import urlopen

from bs4 import BeautifulSoup


# FINNISH: https://en.wiktionary.org/wiki/Category:Finnish_language
# GERMAN: https://en.wiktionary.org/wiki/Category:German_language
# AFRIKAANS: https://en.wiktionary.org/wiki/Category:Afrikaans_language
# LANG > LANG terms by etymology > LANG compound words


WIKI_URL = 'https://en.wiktionary.org'

LANG_URL = {
    'fi': 'https://fi.wiktionary.org/wiki/'
}

LANGUAGES = {
    'Finnish': 'fi',
    'Afrikaans': 'af',
    'German': 'de',
    'English': 'en',
}

AFFIXES = [
    'prefix',
    'prefiksit',
    'infix',
    'infiksit',
    'suffix',
    'suffiksit',
]


POS = {
    'fi': [
        'noun',
        'adjective',
        'pronoun',
        'proper noun',
        'adverb',
        'verb',
        'interjection',
        'conjunction',
        'numeral',
        'phrase',
    ]
}


def commonsuffix(texts):
    ''' '''
    return commonprefix([t[::-1] for t in texts])[::-1]


class Extract:
    ''' '''

    def __init__(self, lang, url=None):
        self.lang = lang.title()
        self.code = LANGUAGES[self.lang]
        self.pos_p = re.compile(r'^(%s)' % r'|'.join(POS[self.code]), re.I)
        self.walk(url=url)

    # extraction --------------------------------------------------------------

    def walk(self, url=None):
        '''Take a walk through Wikitionary's compounds...'''
        if not url:
            url = WIKI_URL + '/wiki/Category:%s_compound_words' % self.lang

        soup = BeautifulSoup(urlopen(url), 'html.parser')
        page = 'Category:%s compound words' % self.lang
        page = soup.find_all('a', attrs={'title': page})[-1]
        words = soup.find_all('div', attrs={'class': 'mw-category-group'})

        del soup

        for div in words:
            for a in div.find_all('a'):
                try:
                    self.extract(a.text, a.get('href'))

                except Exception as error:
                    print('%s (%s) %s: %s' % (
                        a.text,                     # word
                        WIKI_URL + a.get('href'),   # full href
                        type(error).__name__,       # error type
                        str(error),                 # error message
                        ), file=stderr)             # noqa

        if page.text == 'next page':
            return self.walk(WIKI_URL + page.get('href'))

    def extract(self, orth, href):
        '''Extract the compound segmentation and POS of the word `orth`.'''
        soup = BeautifulSoup(urlopen(WIKI_URL + href), 'html.parser')
        pos = self.get_pos(soup)
        declensions = self.get_declensions(soup, orth, pos)
        compounds = self.get_compound(orth, soup)

        del soup

        if declensions:
            for compound in compounds:
                annotation = ' ; '.join([orth, compound, pos])
                print(annotation)

                for _orth, _compound in self.split_declensions(
                        compound, orth, pos, declensions):
                    annotation = ' ; '.join([_orth, _compound, pos])
                    print(annotation)

        else:
            for compound in compounds:
                annotation = ' ; '.join([orth, compound, pos])
                print(annotation)

    # compound segmentation ---------------------------------------------------

    def get_compound(self, orth, soup):
        '''Identify the word boundaries in `orth` from the word's etymology.'''
        for etymology in self.get_etymology(orth, soup):
            goal = self.baseify(orth)

            if not self.samesies(etymology, goal):
                etymology = self.reconcile_etymology(etymology, goal)

            if not self.samesies(etymology, goal):
                raise ExtractionError('%s != %s' % (orth, etymology))

            yield re.sub(r'[-=]{2,}', '', '='.join(etymology))

    def get_etymology(self, orth, soup):
        '''Return the etymology(ies) of `orth` as a list of words/morphemes.'''
        pattern = r'([a-z0-9\-äö]+(?: +\+ +[a-z0-9\-äö]+)+)'
        error = ExtractionError('No candidates.')
        propser = False

        for etym in soup.find_all(
                class_='mw-headline',
                string=re.compile(r'^Etymology')):

            etym = etym.find_parent(['h3', 'h4']).find_next_sibling(['p'])

            for span in etym.find_all('span'):
                span.decompose()

            text = etym.text.replace('\u200e', '')
            candidates = re.findall(pattern, text.lower())

            for candidate in candidates:
                split = re.findall(r'-|[^\s\-+]+', candidate)

                try:
                    if '-' in candidate:
                        for i, comp in enumerate(split):
                            if '-' != comp:
                                p = re.compile(r'-?%s-?' % comp, re.I)
                                a_tag = etym.find('i', string=p).find('a')

                                if not a_tag or self.is_word(comp, a_tag):
                                    split[i] = comp.replace('-', '')

                    propser = True

                    yield split

                except ExtractionError as error:

                    if not propser and candidate == candidates[-1]:
                        raise error

    def reconcile_etymology(self, split, orth):
        '''Reconcile the etymology (`split`) with `orth`.'''
        compound = []
        base = orth

        for comp in reversed(split):

            if comp == '-':
                compound.append(comp)

            else:
                while comp:
                    try:
                        index = base.rindex(comp)
                        base, comp = base[:index], base[index:]
                        compound.append(comp)
                        break

                    except ValueError:
                        comp = comp[:-1]

                else:
                    raise ExtractionError(
                        'Could not reconcile: %s & %s' % (split, orth))

        return compound[::-1]

    def is_word(self, morph, a_tag):
        '''Confirm that `morph` is a word and not an affix.

        This method first attempts to look up `morph` in the English Wiktionary
        url (https://en.wiktionary.org/<morph>) provided in `a_tag`. If this
        fails, it tries to look up `morph` in the given language's Wiktionary
        (e.g., for Finnish: https://fi.wiktionary.org/<morph>).
        '''
        url = WIKI_URL + a_tag.get('href')

        if 'new' in a_tag.get('class', []):
            url = LANG_URL[self.code] + morph

        try:
            soup = BeautifulSoup(urlopen(url), 'html.parser')
            headers = soup.find_all('span', class_='mw-headline')

            return all([h.text.lower() not in AFFIXES for h in headers])

        except HTTPError:
            raise ExtractionError('Could not verify word: %s' % a_tag.text)

    def samesies(self, etymology, goal):
        '''Determine if `etymology` and `goal` are essentially equivalent.'''
        return self.baseify(''.join(etymology)) == goal

    def baseify(self, text):
        '''Strip `text` of orthographic delimiters and make it lowercase.'''
        return text.replace('-', '').replace(' ', '').lower()

    # part of speech ----------------------------------------------------------

    def get_pos(self, soup):
        '''Return the (first) part of speech listed in `soup`.'''
        pos = soup.find_all('span', class_='mw-headline', string=self.pos_p)

        if pos:
            return ' '.join([p.text for p in pos]).lower()

        raise ExtractionError('Could not identify part of speech.')

    # declensions -------------------------------------------------------------

    def get_declensions(self, soup, orth, pos):
        '''Extract the various conjugations of `orth` from `soup`.'''
        DECLENSIONS = []

        for table in soup.find_all('table', class_='inflection-table'):
            try:
                declensions = table.find_all('span', class_='Latn')
                declensions = list([d.text for d in declensions])

                # for adjectives, include comparative and superlative forms
                if 'adjective' in pos:
                    declensions.extend(re.findall(
                        r'(?:comparative|superlative) ([a-z0-9\-äö]+)',
                        soup.text))

                # for verbs, strip auxiliaries/modals
                elif 'verb' in pos:
                    n = orth.count(' ')
                    declensions = [
                        d.split(' ', d.count(' ')-n)[-1] for d in declensions]

                DECLENSIONS.extend(declensions)

            except AttributeError:
                pass

        # attempt to remove the default orthography (which is most likely the
        # nominative singular form), so that it can print first in
        # self.extract() without duplication
        try:
            DECLENSIONS.remove(orth)

        except ValueError:
            pass

        return list(set(DECLENSIONS))

    def split_declensions(self, compound, orth, pos, declensions):
        '''Mark the word boundaries in each declension.'''
        prefix = commonprefix(declensions)
        i, j = len(prefix), len(orth)
        prefix = compound[:-(j - i)] if j > i else compound

        for _orth in declensions:
            yield _orth, prefix + _orth[i:]

    # -------------------------------------------------------------------------


class ExtractionError(Exception):
    '''My very own Extraction Error.'''
    pass


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--lang', default='Finnish')
    parser.add_argument('-u', '--url', default=None)
    args = parser.parse_args()

    Extract(args.lang, args.url)
