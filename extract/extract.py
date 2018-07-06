import json
import re

from os.path import commonprefix
from sys import stderr
from urllib.error import HTTPError, URLError
from urllib.request import quote, urlopen

from bs4 import BeautifulSoup
from jsmin import jsmin

from lang import LANGUAGE_DATA, WIKI_EN_URL, WIKI_LANGUAGES


class Extract:

    ETYMOLOGY_P = re.compile(r'^Etymology')

    # extract compound etymologies from nested i/a tags
    BIG_KAHUNA_P = re.compile(
        r'<i[^>]+>(?:<a[^>]+>)?[\w-]+(?:</a>)?</i>(?:[\w\s]+\+[\w\s]+'
        r'<i[^>]+>(?:<a[^>]+>)?[\w-]+(?:</a>)?</i>)+')

    WORDS_P = re.compile(r'<i[^>]+>(?:<a[^>]+>)?([\w-]+)(?:</a>)?</i>')

    COMPOUND_SPLIT_P = re.compile(r'(=|\+|-)')

    # require that words have minimally have one alphabetic character
    # (stricter MIN-WRD requirements can be imposed during post-processing)
    MIN_WORD_P = re.compile(r'\w+')

    HEADERS_P = re.compile(
        r'^(?!(?:pronunciation|etymology|derived terms|see also|usage notes|'
        r'synonyms|antonyms|letter|alternative forms|further reading|'
        r'related terms|references|inflection))^.+', re.I)

    ADJ_FORMS_P = re.compile(r'(?:comparative|superlative) (\w+)')

    NOUN_FORMS_P = re.compile(r'(?:genitive|plural) (\w+)')

    def __init__(self, lang, grammar_fn=None, debug_li=[], url=None,
                 find_headers=True):
        try:
            # if `lang` is a language code
            self.code = lang.lower()
            self.lang = WIKI_LANGUAGES[self.code]

        except KeyError:

            try:
                # if `lang` is the name of a language
                self.lang = lang.title()
                self.code = WIKI_LANGUAGES.inv[self.lang]

            except KeyError:
                raise ExtractionError('Unsupported language: %s.' % lang)

        # the language's Wiktionary url, e.g., https://fi.wiktionary.org/wiki/
        self.wiki = LANGUAGE_DATA[self.code].get('wiki')

        # the English Wiktionary's url to the language's lemmas
        self.lemmas = LANGUAGE_DATA[self.code]['lemmas']

        if not grammar_fn:
            grammar_fn = 'lang/%s.json' % self.code

        with open(grammar_fn, 'r+') as f:
            grammar = json.loads(jsmin(f.read()))  # jsmin removes comments

        # the name of the target language in the target language
        # (e.g., 'Suomi' is 'Finnish' in Finnish)
        self.native_lang = grammar['native_language']

        # this method takes in a part-of-speech category and returns its tag/
        # abbreviation (e.g., 'N' for 'Noun')
        self.get_tag = lambda pos: grammar['POS'][pos.lower()]

        # a regular expression that matches part-of-speech categories
        self.pos_p = re.compile(
            r'^(%s)' % r'|'.join(grammar['POS'].keys()), re.I)

        # self.auxiliaries = set(grammar.get('AUXILIARIES'))

        self.affixes = grammar.get('AFFIXES', [])

        self.interfixes = grammar.get('INTERFIXES', [])

        if self.interfixes:
            self.format_morpheme = self.format_morpheme_incl_interfixes

        else:
            self.format_morpheme = self.format_morpheme_excl_interfixes

        # if `debug_li` is given, only the words listed in `debug_wil` will get
        # extracted...
        if debug_li:
            self.debug(debug_li)

        # otherwise, scrape Wiktionary, beginning with `url`...
        else:

            # if no `url` is provided, begin with the target language's lemmas,
            # scraping them in alphabetical order
            if not url:
                url = WIKI_EN_URL + \
                    '/w/index.php?title=Category:%s_lemmas&from=%s' % \
                    (self.lang, grammar['first_letter'])

            if find_headers:
                self.headers = set()
                self.find_headers(url=url)

            else:
                return self.walk(url=url)

    # scrape ------------------------------------------------------------------

    def walk(self, url):
        '''Walk through Wiktionary, beginning with `url`.'''
        soup = BeautifulSoup(urlopen(url), 'html.parser')
        page = soup.find_all('a', title='Category:%s lemmas' % self.lang)[-1]
        words = soup.find('div', id='mw-pages') \
            .find_all('div', class_='mw-category-group')

        del soup

        for div in words:
            for a in div.find_all('a', string=Extract.MIN_WORD_P):
                href = WIKI_EN_URL + a.get('href')

                try:
                    self.extract(a.text,  href)

                except SilentError:  # some errors aren't worth mentioning
                    pass

                except Exception as error:
                    self.print_error(a.text, href, error)

        if page.text == 'next page':
            return self.walk(WIKI_EN_URL + page.get('href'))

    def extract(self, orth, url):
        '''Extract lexical information about `orth` from `url`.

        Lexical information includes part of speech, declensions, and
        compound segmentation(s).
        '''
        soup = self.get_finnish_soup(url, self.lang)
        pos = self.get_pos(soup)
        compounds = self.get_compounds(orth, soup)
        declensions = self.get_declensions(soup, orth, pos)

        del soup

        if compounds and declensions:
            for compound in compounds:
                self.print_annotation(orth, pos, compound)

                for _orth, _compound in self.split_declensions(
                        declensions, compound, orth):
                    self.print_annotation(_orth, pos, _compound)

        elif compounds:
            for compound in compounds:
                self.print_annotation(orth, pos, compound)

        else:
            self.print_annotation(orth, pos)

            for declension in declensions:
                self.print_annotation(declension, pos)

    def get_finnish_soup(self, url, lang):
        '''Return parsed HTML about the target language `lang` from `url.`

        Since a single Wiktionary page can address the meaning of the same
        word/string across different languages, this method returns the
        BeautifulSoup-parsed HTML section that pertains to the target language.
        '''
        soup = BeautifulSoup(urlopen(url), 'html.parser')
        section = soup.find('span', class_='mw-headline', id=lang)
        finnish = ''

        try:
            for tag in section.parent.next_siblings:
                if tag.name == 'h2':
                    break

                else:
                    finnish += str(tag)

            return BeautifulSoup(finnish, 'html.parser')

        except AttributeError:
            raise ExtractionError('No soup.')

    def find_headers(self, url):
        ''' '''
        soup = BeautifulSoup(urlopen(url), 'html.parser')
        page = soup.find_all('a', title='Category:%s lemmas' % self.lang)[-1]
        words = soup.find('div', id='mw-pages') \
            .find_all('div', class_='mw-category-group')

        del soup

        for div in words:
            for a in div.find_all('a', string=Extract.MIN_WORD_P):
                href = WIKI_EN_URL + a.get('href')
                soup = self.get_finnish_soup(href, self.lang)
                headers = soup.find_all(
                    'span', class_='mw-headline', string=self.HEADERS_P)
                self.headers.update(h.text for h in headers)

        if page.text == 'next page':
            return self.find_headers(WIKI_EN_URL + page.get('href'))

        else:
            print('\n'.join(sorted(list(self.headers))))

    def debug(self, debug_li):
        '''Print the annotations for the words listed in `debug_li`.

        This method is intended to help debug the scraper. If `debug_li` is a
        list, this method prints annotations for the words listed in
        `debug_li`. If `debug_li` is a string, it will treat the string as a
        filename and attempt to read a list of words from the file.
        '''
        if isinstance(debug_li, str):
            with open(debug_li, 'rb') as f:
                debug_li = f.readlines()

        for orth in debug_li:
            if orth:
                orth = orth.decode('utf-8').replace('\n', '')
                href = WIKI_EN_URL + '/wiki/' + quote(orth.replace(' ', '_'))

                try:
                    self.extract(orth, href)

                except ExtractionError as error:
                    self.print_error(orth, href, error)

                print()

    # part of speech ----------------------------------------------------------

    def get_pos(self, soup):
        '''Return the parts of speech listed in `soup`.'''
        pos = soup.find_all('span', class_='mw-headline', string=self.pos_p)

        if pos:
            tags = []

            for p in pos:
                tag = self.get_tag(p.text)

                # in lieu of calling `set()`, this preserves the order of the
                # tags listed in `soup`
                if tag not in tags:
                    tags.append(tag)

            return ' '.join(tags)

        raise SilentError('Unwanted POS.')

    # compound segmentation ---------------------------------------------------

    def get_compounds(self, orth, soup):  # noqa
        '''Identify the various compound segmentations for `orth` (if any).'''
        etymologies = soup.find_all(
            class_='mw-headline', string=Extract.ETYMOLOGY_P)

        # without any etymology, can't confirm if `orth` is simplex or complex
        if not etymologies:
            raise SilentError('No etymology. Boo.')

        compounds = []
        errors = []

        for etym in etymologies:
            etym = etym.find_parent(['h3', 'h4']).find_next_sibling(['p'])

            try:
                for span in etym.find_all('span'):
                    span.decompose()

            except AttributeError:
                continue

            for split in Extract.BIG_KAHUNA_P.findall(
                    str(etym).replace('\u200e', '')):

                try:
                    compounds.append(self.get_compound(orth, split, etym))

                except SilentError:
                    continue

                except ExtractionError as error:
                    errors.append(error)

        # raise the first encountered error if no compound structures were
        # successfully derived
        if errors and not compounds:
            raise errors[0]

        # return any successfully derived compound structures or an empty list
        # in the event of zero errors and no compounds
        return compounds

    def get_compound(self, orth, split, etymology_soup):
        '''Identify the word boundaries in `orth` from the word's etymology.

        Note that `split` is a list of strings derived from `etymology_soup`,
        the BeautifulSoup-parsed HTML containing the etymology of `orth`.
        '''
        might_affix = '>-' in split or '-<' in split
        split = Extract.WORDS_P.findall(split)
        affixes = 0
        errors = []

        # if there is a hyphen somewhere in the etymology, check that each
        # component containing a hyphen is a word and not an affix
        if might_affix:
            compound = ''

            for i, comp in enumerate(split):

                if '-' in comp:

                    a_tag = etymology_soup.find('a', string=comp)

                    if not a_tag or 'new' in a_tag.get('class', []):
                        url = self.wiki + quote(comp)
                        lang = self.native_lang

                    else:
                        url = WIKI_EN_URL + a_tag.get('href')
                        lang = self.lang

                    try:
                        soup = self.get_finnish_soup(url, lang)
                        headers = soup.find_all('span', class_='mw-headline')
                        comp, n = self.format_morpheme(headers, comp)
                        split[i] = comp
                        affixes += n

                        # # if `comp` is a standalone word, surround the word
                        # # with equal signs
                        # if self.is_word(headers):
                        #     split[i] = '=' + comp.replace('-', '') + '='

                        # # if `comp` is an interfix, surround the interfix with
                        # # plus signs
                        # elif self.is_interfix(headers, comp):
                        #     split[i] = '+' + comp.replace('-', '') + '+'
                        #     affixes += 1

                        # # if `comp` is an affix, leave in the hyphens
                        # else:
                        #     affixes += 1

                    except (HTTPError, URLError):
                        errors.append(
                            ExtractionError("Could not verify '%s'." % comp))

                else:
                    split[i] = '=' + comp.replace('-', '') + '='

            # if `split` contains all affixes and only one UNK, it is
            # necessarily simplex and should not raise an error
            if errors and affixes != len(split) - 1:
                raise errors[0]

            compound = self.format_compound(''.join(split))

        else:
            compound = '='.join(split)

        return self.verify_compound(orth, compound)

    def format_compound(self, compound):
        '''Format the delimiters in `compound`.'''
        if compound.startswith('='):
            compound = compound[1:]

        if compound.endswith('='):
            compound = compound[:-1]

        return compound \
            .replace('=+', '+') \
            .replace('+=', '+') \
            .replace('==', '=') \
            .replace('=-', '') \
            .replace('-=', '') \
            .replace('--', '')

    def verify_compound(self, orth, compound):
        ''' '''
        # toss simplex words
        if '=' not in compound and '+' not in compound:
            raise SilentError('False alarm. Not a compound.')

        goal = self.baseify(orth)

        if self.baseify(compound) != goal:
            compound = self.reconcile(compound, goal)

            # TODO: confirm that this step is (un)necessary
            if self.baseify(compound) != goal:
                raise ExtractionError('Unreconcilable compound structure.')

        return compound

    def baseify(self, text):
        '''Strip `text` of delimiters and make it lowercase.'''
        return text \
            .replace('-', '') \
            .replace(' ', '') \
            .replace('=', '') \
            .replace('+', '').lower()

    def reconcile(self, compound, orth):
        '''Split `orth` based on the split of `compound`.

        This method is invoked when the orthography or "baseified" form of
        `compound` does not match the orthography of `orth`. This method
        attempts to reconcile their differences to split `orth` appropriately.

        E.g., if the compound's etymology is 'aaltomainen=uus', but `orth` is
        `aaltomaisuus`, then this method will generate 'aaltomais=uus' as the
        segmentation of `orth`.
        '''
        split = Extract.COMPOUND_SPLIT_P.split(compound)
        compound = []
        base = orth

        for comp in reversed(split):

            if comp == '=' or comp == '+':
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

    # morphology --------------------------------------------------------------

    def format_morpheme_incl_interfixes(self, headers, morph):
        '''Format the delimiters surrounding `morph` and say if it is affixal.

        This method takes into consideration interfixes.

        This method surrounds interfixes with plus (+) signs, preserves hyphens
        (-) before/after affixes, and surrounds word stems with equal (=)
        signs.

        The method returns a 2-tuple, where the first element is the formatted
        morpheme and the second element is a boolean indicating if the morpheme
        is affixal. (Interfixes are considered affixes.)
        '''
        for label in headers:
            label = label.text.lower()

            if label == 'interfix':
                return '+' + morph.replace('-', '') + '+', True

            if label in self.affixes:
                return morph, 1

        if morph in self.interfixes:
            return '+' + morph.replace('-', '') + '+', True

        return '=' + morph.replace('-', '') + '=', False

    def format_morpheme_excl_interfixes(self, headers, morph):
        '''Format the delimiters surrounding `morph` and say if it is affixal.

        This method does NOT take into consideration interfixes.

        This method preserves hyphens (-) before/after affixes and surrounds
        word stems with equal (=) signs.

        The method returns a 2-tuple, where the first element is the formatted
        morpheme and the second element is a boolean indicating if the morpheme
        is affixal.
        '''
        for label in headers:

            if label.text.lower() in self.affixes:
                return morph, True

        return '=' + morph.replace('-', '') + '=', False

    # declensions -------------------------------------------------------------

    def get_declensions(self, soup, orth, pos):
        '''Extract the various conjugations of `orth` from `soup`.'''
        DECLENSIONS = []

        # for adjectives, include comparative and superlative forms
        if 'ADJ' in pos:
            DECLENSIONS.extend(Extract.ADJ_FORMS_P.findall(soup.text))

        for table in soup.find_all('table', class_='inflection-table'):
            try:
                declensions = table.find_all('span', class_='Latn')
                declensions = list([d.text for d in declensions])

                # strip any modifiers
                n = orth.count(' ')
                declensions = [
                    d.split(' ', d.count(' ') - n)[-1] for d in declensions]

                DECLENSIONS.extend(declensions)

            except AttributeError:
                pass

        # for nouns, include genitive and plural forms in the absence of a
        # declension table
        if not DECLENSIONS and 'N' in pos:
            DECLENSIONS.extend(Extract.NOUN_FORMS_P.findall(soup.text))

        DECLENSIONS = list(set(DECLENSIONS))

        # # remove any auxiliary verbs
        # if 'V' in pos and orth not in self.auxiliaries:
        #     DECLENSIONS = [d for d in DECLENSIONS if d not in self.auxiliaries]

        # remove the default orthography (most likely, the nominative singular
        # form), so that it prints first in self.extract() without duplication
        try:
            DECLENSIONS.remove(orth)

        except ValueError:
            pass

        return DECLENSIONS

    def split_declensions(self, declensions, compound, orth):
        '''Delimit the word boundaries in each declension with '='.'''
        prefix = commonprefix([orth, ] + declensions)
        i, j = len(prefix), len(orth)
        prefix = compound[:-(j - i)] if j > i else compound

        for _orth in declensions:
            yield _orth, prefix + _orth[i:]

    # print -------------------------------------------------------------------

    def print_error(self, orth, url, error):
        '''Print an informative error message for `orth`.'''
        print(
            '%s (%s) %s: %s' % (orth, url, type(error).__name__, str(error)),
            file=stderr)

    def print_annotation(self, *annotation):
        '''Format and print `annotation`.'''
        print(' ; '.join(annotation))


class ExtractionError(Exception):
    pass


class SilentError(ExtractionError):
    pass


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--lang', default='Finnish')
    parser.add_argument('-g', '--grammar_fn', default=None)
    parser.add_argument('-d', '--debug_li', nargs='*', default=[])
    parser.add_argument('-D', '--debug_fn', default='')
    parser.add_argument('-u', '--url', default=None)
    parser.add_argument('-H', '--find_headers', action='store_true')
    args = parser.parse_args()

    Extract(
        lang=args.lang,
        grammar_fn=args.grammar_fn,
        debug_li=args.debug_fn if args.debug_fn else args.debug_li,
        url=args.url,
        find_headers=args.find_headers
        )
