import json
import re

from os.path import commonprefix
from sys import stderr
from urllib.error import HTTPError, URLError
from urllib.request import quote, urlopen

from bs4 import BeautifulSoup
from jsmin import jsmin

from lang import LANGUAGE_DATA, WIKI_EN_URL


class Extract:

    # for extracting 'Etymology' section headers
    ETYMOLOGY_P = re.compile(r'^Etymology')

    # for extracting compound etymologies from nested i/a tags
    BIG_KAHUNA_P = re.compile(
        r'<i[^>]+>(?:<a[^>]+>)?[\w-]+(?:</a>)?</i>(?:[\w\s]+\+[\w\s]+'
        r'<i[^>]+>(?:<a[^>]+>)?[\w-]+(?:</a>)?</i>)+')

    # for extracting the constituent words in a compound etymology
    WORDS_P = re.compile(r'<i[^>]+>(?:<a[^>]+>)?([\w-]+)(?:</a>)?</i>')

    # for extracting delimiters
    DELIMITERS_P = re.compile(r'(=|\+|-)')

    # for requiring that words have minimally have one alphabetic character
    # (stricter MIN-WRD requirements can be imposed during post-processing)
    MIN_WORD_P = re.compile(r'\w+')

    # for extracting parts of speech in the target language
    NON_POS_P = re.compile(
        r'^(?!(?:Decl|Etymo|Pronunci|Conjugat|[\w ]+s(?: \d)?$|See also'
        r'|Inflection|Hyponym|Hypernym|Antonym|Synonym|Reference|Further'
        r'|Alternative|Usage|Note|Compound.+|Holonym|Meronym)).')

    # for extracting comparitive and superlative forms
    ADJ_FORMS_P = re.compile(r'(?:comparative|superlative) (\w+)')

    def __init__(self, lang, code, grammar_fn=None):
        # set the language's name (`self.lang`) and 2-letter code (`self.code`)
        self.lang = lang
        self.code = code

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
        self.native_lang = grammar.pop('native_language')

        # a regular expression that matches part-of-speech categories
        self.pos_p = re.compile(r'^(%s)' % r'|'.join(grammar['POS'].keys()))

        # the default starting url for scraping in `self.walk()`
        self.start_url = '%s/w/index.php?title=Category:%s_lemmas&from=%s' % (
            WIKI_EN_URL, self.lang, grammar['first_letter'])

        # for any item in `grammar` whose key is entirely uppercase, store that
        # item on `self` (e.g., grammar['AFFIXES'] >>> self.affixes)
        for key in grammar.keys():
            if key.upper() == key:
                setattr(self, key.lower(), grammar[key])

    # scrape ------------------------------------------------------------------

    def walk(self, url):
        '''Walk through Wiktionary, beginning with `url`.'''
        if not url:
            url = self.start_url

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

                    if self.basify(_orth) == self.basify(_compound):
                        self.print_annotation(_orth, pos, _compound)

                    else:
                        self.print_error(orth, url, ExtractionError(
                            'Declension %s != %s' % (_orth, _compound)))

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

    def find_likely_pos(self, url=None):
        '''Scrape likely part-of-speech categories for the target language.'''
        try:
            if not url:
                self.headers = set()
                url = self.start_url

            soup = BeautifulSoup(urlopen(url), 'html.parser')
            page = soup.find_all(
                'a', title='Category:%s lemmas' % self.lang)[-1]
            words = soup.find('div', id='mw-pages').find_all(
                'div', class_='mw-category-group')

            del soup

            for div in words:
                for a in div.find_all('a', string=Extract.MIN_WORD_P):
                    href = WIKI_EN_URL + a.get('href')
                    soup = self.get_finnish_soup(href, self.lang)
                    headers = soup.find_all(
                        'span', class_='mw-headline', string=self.NON_POS_P)
                    self.headers.update(h.text for h in headers)

            if page.text == 'next page':
                return self.find_likely_pos(WIKI_EN_URL + page.get('href'))

        except KeyboardInterrupt:
            print(url)

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
                tag = self.pos[p.text]

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
            .replace('--', '').lower()

    def verify_compound(self, orth, compound):
        ''' '''
        # toss simplex words
        if '=' not in compound and '+' not in compound:
            raise SilentError('False alarm. Not a compound.')

        goal = self.basify(orth)

        if self.basify(compound) != goal:
            compound = self.reconcile(compound, goal)

            # TODO: confirm that this step is (un)necessary
            if self.basify(compound) != goal:
                raise ExtractionError('Unreconcilable compound structure.')

        return compound

    def basify(self, text):
        '''Strip `text` of delimiters and make it lowercase.'''
        return Extract.DELIMITERS_P.sub('', text).lower()

    def reconcile(self, compound, orth):
        '''Split `orth` based on the split of `compound`.

        This method is invoked when the orthography or "basified" form of
        `compound` does not match the orthography of `orth`. This method
        attempts to reconcile their differences to split `orth` appropriately.

        E.g., if the compound's etymology is 'aaltomainen=uus', but `orth` is
        `aaltomaisuus`, then this method will generate 'aaltomais=uus' as the
        segmentation of `orth`.
        '''
        split = Extract.DELIMITERS_P.split(compound)
        compound = []
        base = orth

        for comp in reversed(split):

            if comp in '=+-':
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

    def format_morpheme(self, headers, morph):
        '''Format the delimiters surrounding `morph` and say if it is affixal.

        This method does NOT take into consideration interfixes.

        This method preserves hyphens (-) before/after affixes and surrounds
        word stems with equal (=) signs.

        The method returns a 2-tuple, where the first element is the formatted
        morpheme and the second element is a boolean indicating if the morpheme
        is affixal.
        '''
        for label in headers:

            if label.text in self.affixes:
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

                # strip any modifiers or auxiliaries
                n = orth.count(' ')
                declensions = [
                    d.split(' ', d.count(' ') - n)[-1] for d in declensions]

                DECLENSIONS.extend(declensions)

            except AttributeError:
                pass

        DECLENSIONS = list(set(DECLENSIONS))

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
