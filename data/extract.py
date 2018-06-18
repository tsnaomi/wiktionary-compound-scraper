import json
import re

from os.path import commonprefix
from sys import stderr
from urllib.error import HTTPError
from urllib.request import quote, urlopen
from warnings import catch_warnings, warn

from bidict import bidict
from bs4 import BeautifulSoup
from jsmin import jsmin


# Languages -------------------------------------------------------------------

with open('lang/lang.json', 'r+') as f:
    LANG_DATA = json.load(f)

LANGUAGES = bidict({k: v['language'] for k, v in LANG_DATA.items()})


# URLs ------------------------------------------------------------------------

EN_URL = 'https://en.wiktionary.org'

WIKI_URL = 'https://%s.wiktionary.org/wiki/'

LEMMA_URL = EN_URL + '/w/index.php?title=Category:%s_lemmas&from=A'


# Compiled regexes ------------------------------------------------------------

ETYMOLOGY_P = re.compile(r'^Etymology')

BIG_KAHUNA_P = re.compile(
    r'<i[^>]+>(?:<a[^>]+>)?[\w-]+(?:</a>)?</i>(?:[\w\s]+\+[\w\s]+'
    r'<i[^>]+>(?:<a[^>]+>)?[\w-]+(?:</a>)?</i>)+')

WORDS_P = re.compile(r'<i[^>]+>(?:<a[^>]+>)?([\w-]+)(?:</a>)?</i>')

# COMPOUND_ETYMOLOGY = re.compile(r'([\w\d\-]+(?: +\+ +[\w\d\-]+)+)')

COMPOUND_SPLIT_P = re.compile(r'(-|=)')


# Extaction object ------------------------------------------------------------

class Extract:

    def __init__(self, lang, grammar_fn=None, min_word=3, words=[], url=None):
        try:
            if len(lang) == 2:  # if `lang` is a language code
                self.code = lang.lower()
                self.lang = LANGUAGES[self.code]

            else:  # if `lang` is the name of a language
                self.lang = lang.title()
                self.code = LANGUAGES.inv[lang]

        except KeyError:
            raise ExtractionError('Unsupported language: %s.' % lang)

        # the language's Wiktionary url, e.g., https://fi.wiktionary.org/wiki/
        self.wiki = LANG_DATA[self.code].get('wiki')

        # the English Wiktionary's url to the language's lemmas
        self.lemmas = LANG_DATA[self.code]['lemmas']

        if not grammar_fn:
            grammar_fn = 'lang/%s.json' % self.code

        with open(grammar_fn, 'r+') as f:
            grammar = json.loads(jsmin(f.read()))  # jsmin removes comments

        # this method takes in a part-of-speech category and returns its tag/
        # abbreviation (e.g., 'N' for 'Noun')
        self.get_tag = lambda pos: grammar['TAGS'][pos.lower()]

        # a list of affixes in both English and the target language
        self.affixes = grammar['AFFIXES']

        # a regular expression that only captures words whose first constiuent
        # word is at least `min-word` in length
        self.min_word_p = re.compile(r'^\w{%i,}' % min_word)

        # a regular expression that matches part-of-speech categories
        self.pos_p = re.compile(r'^(%s)' % r'|'.join(grammar['POS']), re.I)

        # if `words` is given, only the words listed in `words` will get
        # extracted...
        if words:
            self.from_list(words)

        # otherwise, it's time to walk through Wiktionary...
        else:
            self.walk(url=url)

    # extraction --------------------------------------------------------------

    def walk(self, url=None):
        '''Take a walk through Wiktionary...'''
        if not url:
            url = LEMMA_URL % self.lang

        soup = BeautifulSoup(urlopen(url), 'html.parser')
        page = soup.find_all('a', title='Category:%s lemmas' % self.lang)[-1]
        words = soup.find('div', id='mw-pages') \
            .find_all('div', class_='mw-category-group')

        del soup

        for div in words:
            for a in div.find_all('a', string=self.min_word_p):
                href = EN_URL + a.get('href')

                try:
                    # some errors are non-fatal...
                    with catch_warnings(record=True) as w:
                        self.extract(a.text,  href)
                        print()

                        for warning in w:
                            self.print_warning(a.text, href, warning)

                # ...some errors aren't worth noting...
                except SilentError:
                    pass

                # ...while other errors are fatal
                except Exception as error:
                    self.print_error(a.text, href, error)

        if page.text == 'next page':
            return self.walk(EN_URL + page.get('href'))

    def from_list(self, words):
        ''' '''
        if isinstance(words, str):
            with open(words, 'r+') as f:
                words = f.readlines()

        words = [quote(w.replace('\n', '').replace(' ', '_')) for w in words]

        for orth in words:
            if orth:
                href = EN_URL + '/wiki/' + orth

                try:
                    # TODO: de-duplicate
                    with catch_warnings(record=True) as w:
                        self.extract(orth, href)

                        for warning in w:
                            self.print_warning(orth, href, warning)

                except ExtractionError as error:
                    self.print_error(orth, href, error)

                print()

    def extract(self, orth, url):
        ''' '''
        soup = self.get_finnish_soup(url)
        pos = self.get_pos(soup)
        compounds = self.get_compound(orth, soup)
        declensions = self.get_declensions(soup, orth, pos)

        del soup

        if compounds and declensions:
            for compound in compounds:
                self.print_annotation(orth, pos, compound)

                for _orth, _compound in self.split_declensions(
                        compound, orth, pos, declensions):
                    self.print_annotation(_orth, pos, _compound)

        elif compounds:
            for compound in compounds:
                self.print_annotation(orth, pos, compound)

        else:
            self.print_annotation(orth, pos)

            for declension in declensions:
                self.print_annotation(declension, pos)

    def get_finnish_soup(self, url):  # TODO: rename
        ''' '''
        soup = BeautifulSoup(urlopen(url), 'html.parser')
        section = soup.find('span', class_='mw-headline', id='Finnish')
        finnish = ''

        for tag in section.parent.next_siblings:
            if tag.name == 'h2':
                break

            else:
                finnish += str(tag)

        return BeautifulSoup(finnish, 'html.parser')

    # print -------------------------------------------------------------------

    def print_warning(self, orth, url, warning):
        ''' '''
        print(
            '%s (%s) ExtractionWarning: %s' %
            (orth, url, str(warning.message)))

    def print_error(self, orth, url, error):
        ''' '''
        print(
            '%s (%s) %s: %s' % (orth, url, type(error).__name__, str(error)),
            file=stderr)  # noqa

    def print_annotation(self, *annotation):
        '''Format and print `annotation`.'''
        print(' ; '.join(annotation))

    # part of speech ----------------------------------------------------------

    # TODO: Only include wanted POS categories in `grammar_fn`, then raise a
    # if `SilentIgnore` is no POS is found. No need to extract unwanted POS.
    def get_pos(self, soup):
        '''Return the (first) part of speech listed in `soup`.'''
        pos = soup.find_all('span', class_='mw-headline', string=self.pos_p)

        if pos:
            try:
                return ' '.join(list(set(self.get_tag(p.text) for p in pos)))

            except KeyError:
                raise SilentError('Unwanted POS.')

        raise ExtractionError('Could not identify POS.')

    # compound segmentation ---------------------------------------------------

    def get_compound(self, orth, soup):
        '''Identify the word boundaries in `orth` from the word's etymology.'''
        compounds = []
        yea = False
        goal = self.baseify(orth)

        for etymology in self.get_compound_etymology(orth, soup):

            if '=' in etymology:
                yea = True

                if self.baseify(etymology) != goal:
                    etymology = self.reconcile_etymology(etymology, goal)

                if self.baseify(etymology) != goal:
                    warn('%s != %s' % (orth, etymology), ExtractionWarning)

                compounds.append(etymology)

        if yea and not compounds:
            raise ExtractionError('Unreconcilable compound structure.')

        return compounds

    def get_compound_etymology(self, orth, soup):  # noqa WELP
        ''' '''
        compounds = 0
        errors = 0

        for etym in soup.find_all(class_='mw-headline', string=ETYMOLOGY_P):
            etym = etym.find_parent(['h3', 'h4']).find_next_sibling(['p'])

            try:
                for span in etym.find_all('span'):
                    span.decompose()

            except AttributeError:
                continue

            for split in BIG_KAHUNA_P.findall(str(etym).replace('\u200e', '')):
                split = WORDS_P.findall(split)

                try:
                    for i, comp in enumerate(split):
                        if '-' in comp:
                            _comp = comp.replace('-', '')
                            a = etym.find('a', string=re.compile(r'%s' % comp))

                            if self.is_word(comp, a):
                                split[i] = _comp

                    yield '='.join(split).replace('-=', '') \
                        .replace('=-', '').replace('-=-', '').lower()

                    compounds += 1

                except ExtractionError as error:
                    errors += 1
                    warn(str(error), ExtractionWarning)

        if errors and not compounds:
            raise ExtractionError('Could not identify compound composition.')

    def reconcile_etymology(self, compound, orth):
        '''Reconcile the etymology (`compound`) with `orth`.'''
        split = COMPOUND_SPLIT_P.split(compound)
        compound = []
        base = orth

        for comp in reversed(split):

            if comp == '=':
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
                        "Could not reconcile '%s' and '%s'." %
                        (orth, ''.join(split)))

        return ''.join(compound[::-1])

    def is_word(self, morph, a_tag=None):
        '''Confirm that `morph` is a word and not an affix.

        This method first attempts to look up `morph` in the English Wiktionary
        url (https://en.wiktionary.org/<morph>) provided in `a_tag`. If this
        fails, it tries to look up `morph` in the given language's Wiktionary
        (e.g., for Finnish: https://fi.wiktionary.org/<morph>).
        '''
        if not a_tag or 'new' in a_tag.get('class', []):
            url = self.wiki + quote(morph)

        else:
            url = EN_URL + a_tag.get('href')

        try:
            soup = BeautifulSoup(urlopen(url), 'html.parser')
            headers = soup.find_all('span', class_='mw-headline')

            return all([h.text.lower() not in self.affixes for h in headers])

        except HTTPError:
            raise ExtractionError("Could not verify '%s'." % morph)

    def baseify(self, text):
        '''Strip `text` of delimiters and make it lowercase.'''
        return text.replace('-', '').replace(' ', '').replace('=', '').lower()

    # declensions -------------------------------------------------------------

    def get_declensions(self, soup, orth, pos):
        '''Extract the various conjugations of `orth` from `soup`.'''
        DECLENSIONS = []

        for table in soup.find_all('table', class_='inflection-table'):
            try:
                declensions = table.find_all('span', class_='Latn')
                declensions = list([d.text for d in declensions])

                # for adjectives, include comparative and superlative forms
                if 'ADJ' in pos:
                    declensions.extend(re.findall(
                        r'(?:comparative|superlative) ([a-z0-9\-äö]+)',
                        soup.text))

                # for verbs, strip auxiliaries/modals
                elif 'V' in pos:
                    n = orth.count(' ')
                    declensions = [
                        d.split(' ', d.count(' ')-n)[-1] for d in declensions]

                DECLENSIONS.extend(declensions)

            except AttributeError:
                pass

        DECLENSIONS = list(set(DECLENSIONS))

        # attempt to remove the default orthography (which is most likely the
        # nominative singular form), so that it can print first in
        # self.extract() without duplication
        try:
            DECLENSIONS.remove(orth)

        except ValueError:
            pass

        return DECLENSIONS

    def split_declensions(self, compound, orth, pos, declensions):
        '''Mark the word boundaries in each declension.'''
        prefix = commonprefix(declensions)
        i, j = len(prefix), len(orth)
        prefix = compound[:-(j - i)] if j > i else compound

        for _orth in declensions:
            yield _orth, prefix + _orth[i:]


# Error handling --------------------------------------------------------------

class ExtractionWarning(Warning):
    '''My very own Extraction Warning.'''
    pass


class ExtractionError(Exception):
    '''My very own Extraction Error.'''
    pass


class SilentError(ExtractionError):
    '''An error unworthy of acknowledgement.'''
    pass

# -----------------------------------------------------------------------------


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--lang', default='Finnish')
    parser.add_argument('-g', '--grammar_fn', default=None)
    parser.add_argument('-m', '--min_word', type=int, default=3)
    parser.add_argument('-wl', '--words_li', nargs='*', default=[])
    parser.add_argument('-wf', '--word_fn', default='')
    parser.add_argument('-u', '--url', default=None)
    args = parser.parse_args()

    words = args.word_fn or args.words_li

    Extract(
        lang=args.lang,
        grammar_fn=args.grammar_fn,
        min_word=args.min_word,
        url=args.url,
        words=words,
        )
