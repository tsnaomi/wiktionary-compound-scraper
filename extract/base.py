# -*- coding: utf-8 -*-

import json
import re

from datetime import datetime
from pytz import timezone, utc
from sys import stderr, stdout
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
    DELIMITERS_P = re.compile(r'([=+\- ]+)')
    OPEN_DELIM_P = re.compile(r'([\- ]+)')
    CLOSED_DELIM_P = re.compile(r'([=+]+)')
    CHAR_DELIM_P = re.compile(r'[^=+\- ][=+\- ]*')

    # for requiring that words begin with an alphabetic character and consist
    # of only alphanumeric characters, plus apostrophes and hyphens
    MIN_WORD_P = re.compile(r'^\w[\w\d\-\' ]*$')

    # for extracting parts of speech in the target language
    NON_POS_P = re.compile(
        r'^(?!(?:Decl|Etymo|Pronunci|Conjugat|[\w ]+s(?: \d)?$|See also'
        r'|Inflection|Hyponym|Hypernym|Antonym|Synonym|Reference|Further'
        r'|Alternative|Usage|Note|Compound.+|Holonym|Meronym)).')

    # for extracting comparitive and superlative forms
    ADJ_FORMS_P = re.compile(
        r'\((?:compar|superl)ative ([\w\d\-\' ]+)'
        r'(?:, (?:compar|superl)ative ([\w\d\-\' ]+))?\)')

    # for extracting bad reconciliations
    TOO_SHORT_P = re.compile(r'(?:^|=|\+)\w{1,2}(?:$|=|\+)')

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
        self.native_lang = grammar['native_language']

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

        # set printer methods...
        if stdout.encoding == 'UTF-8':
            self.print_error = self._print_error
            self.print_annotation = self._print_annotation

        else:
            self.print_error = self._buffer_error
            self.print_annotation = self._buffer_annotation

    # scrape ------------------------------------------------------------------

    def walk(self, url):
        '''Walk through Wiktionary, beginning with `url`.'''
        if not url:
            url = self.start_url

            # print timestamp (e.g., '# Fri Jul 13 00:29:57 PDT 2018')
            timestamp = datetime.now(tz=utc).astimezone(timezone('US/Pacific'))
            timestamp = timestamp.strftime('%a %b %d %H:%M:%S %Z %Y\n')
            self.print_annotation(timestamp)

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

                # some errors aren't worth mentioning
                except (HiccupError, SilentError):
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

        for compound in compounds:
            # use an asterisk to indicate that the word is in its
            # Wiktionary dictionary for,
            self.print_annotation(orth + '*', pos, compound)

            if '=' not in compound and '+' not in compound:
                # if `compound` is not a closed compound, then `orth` is
                # already a properly segmented (open) compound
                for _orth in declensions:
                    self.print_annotation(_orth, pos, _orth.lower())

            else:
                for _orth in declensions:

                    try:
                        _compound = self.split_declension(_orth, compound)
                        self.print_annotation(_orth, pos, _compound)

                    except ExtractionError as error:
                        self.print_error(orth, url, error)
                        continue

        if not compounds:
            self.print_annotation(orth + '*', pos)

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
            raise HiccupError('No soup.')

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

                self.print_annotation('')

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

    def parse_etymologies(self, orth, soup):
        '''Extract and parse the etymolgoies of `orth` provided in `soup.`

        This methods yields lists of tuples, where each list represents an
        etymology given for `orth`. Each tuple therein includes a constituent
        word or affix of `orth`, a (potential) link to that consituent's page
        on Wiktionary, as well as the language of that Wiktionary page.

        # e.g., if `orth` is 'aakkoshakemisto', then this method will yield
        something akin to the following:
            [
                ('aakkos-', 'en.wiktionary.org/wiki/aakkoset', 'Finnish'),
                ('hakemisto', 'en.wiktionary.org/wiki/hakemist', 'Finnish')
            ]
        '''
        etymology_soup = soup.find_all(
            class_='mw-headline', string=Extract.ETYMOLOGY_P)

        # without any etymology, can't confirm if `orth` is simplex or complex
        if not etymology_soup:
            raise SilentError('No etymology. Boo.')

        for etym in etymology_soup:
            etym = etym.find_parent(['h3', 'h4']).find_next_sibling(['p'])

            try:
                for span in etym.find_all('span'):
                    span.decompose()

            except AttributeError:
                continue

            etym_html = str(etym).replace('\u200e', '')

            for split in Extract.BIG_KAHUNA_P.findall(etym_html):
                split = Extract.WORDS_P.findall(split)

                for i, comp in enumerate(split):
                    a_tag = etym.find('a', string=comp)

                    if not a_tag or 'new' in a_tag.get('class', []):
                        url = self.wiki + quote(comp)
                        lang = self.native_lang

                    else:
                        url = WIKI_EN_URL + a_tag.get('href')
                        lang = self.lang

                    split[i] = (comp, url, lang)

                yield split

    def get_compounds(self, orth, soup):
        '''Identify the various compound segmentations for `orth` (if any).'''
        compounds = []
        error = None

        for split in self.parse_etymologies(orth, soup):
            try:
                compounds.append(self.get_compound(orth, split))

            # raised by `self.verify_compound()` if `etym` indicates a
            # simplex word and not a compound
            except SilentError:
                continue

            except ExtractionError as err:
                error = error or err  # keep first error

        # if no compound structures were successfully derived...
        if not compounds:
            open_delim = orth.count(' ') + orth.count('-')

            # if `orth` is purely an open compound (i.e., it has no unmarked
            # word boundaries), include `orth` as a compound structure
            if open_delim and (not error or len(split) == open_delim + 1):
                compounds.append(orth.lower())

            # otherwise, raise `error` if one was encountered
            elif error:
                raise error

        # return any successfully derived compound structures or an empty list
        # in the event of zero errors and no compounds
        return compounds

    def get_compound(self, orth, split):
        '''Identify the word boundaries in `orth` from the word's etymology.

        Note that `split` is a list of strings derived from `etymology_soup`,
        the BeautifulSoup-parsed HTML containing the etymology of `orth`.
        '''
        affixes = 0
        error = None

        for i, (morph, url, lang) in enumerate(split):
            try:
                morph, is_affix = self.format_morpheme(morph, url, lang)
                affixes += is_affix

                # if `morph` is a hyphenless affix, this makes it difficult to
                # discern which side(s) of `morph` can border a word boundary
                if is_affix and '-' not in morph:
                    morph = '-' + morph + '-'
                    error = ExtractionError(
                        "Affix not otherwise specified: '%s'." % morph)

            # thrown in `get_finnish_soup()` when `url` is invalid
            except (HTTPError, URLError):
                error = HiccupError(
                    "Could not verify '%s' due to invalid URL." % morph)

            # raised when no "Finnish" soup is found in `get_finnish_soup()`
            except ExtractionError as err:
                error = err

            split[i] = morph

        # if `split` contains all affixes and only one UNK, it is
        # necessarily simplex; otherwise, raise an error
        if error and affixes != len(split) - 1:
            raise error

        return self.verify_compound(orth, self.format_compound(''.join(split)))

    def verify_compound(self, orth, compound):
        '''Ensure that `compound` is a fair segmentation of `orth.`'''
        # toss simplex words
        if '=' not in compound:
            raise SilentError('False alarm. Not a compound.')

        goal = self.basify(orth)

        if self.basify(compound) != goal:
            compound = self.reconcile(goal, compound)

        if ' ' in orth or '-' in orth:
            compound = self.preserve_delimiters(orth, compound)

        return compound

    # reconcile ---------------------------------------------------------------

    def reconcile_lemma(self, lemma, compound):
        '''Split `lemma` based on the split of `compound`.

        This method is invoked when the orthography of`lemma` does not match
        the orthography or "basified" form of its etymology (`compound`). This
        method attempts to reconcile their differences to split `lemma`
        appropriately.

        E.g., if the compound's etymology is 'aaltomainen=uus', but `lemma` is
        `aaltomaisuus`, then this method will generate 'aaltomais=uus' as the
        segmentation of `lemma`.
        '''
        split = []
        base = lemma
        error = None

        for comp in reversed(Extract.CLOSED_DELIM_P.split(compound)):

            if comp in '=+':
                split.append(comp)

            else:
                while len(comp):
                    try:
                        i = base.rindex(comp)
                        base, comp = base[:i], base[i:]
                        split.append(comp)
                        break

                    except ValueError:
                        comp = comp[:-1]

                else:
                    error = True
                    break

        split = ''.join(split[::-1])

        if error or self.basify(split) != lemma:
            raise ExtractionError(
                "Could not reconcile '%s' and '%s'." % (lemma, compound))

        if Extract.TOO_SHORT_P.search(split):
            raise ExtractionError(
                "Could not SAFELY reconcile '%s' and '%s': '%s'." %
                (lemma, compound, split))

        return split

    def reconcile_declension(self, declension, compound):
        '''Split `declension` based on the split of `compound`.

        This method attempts to reconcile a declension (`declension`) with its
        lemma's segmentation (`compound`).
        '''
        i = max(compound.rfind('='), compound.rfind('+'), 0)

        if i:
            prefix = compound[:i + 1]
            basified_prefix = self.basify(prefix)

            if basified_prefix in declension:
                return declension.replace(basified_prefix, prefix)

        try:
            return self.reconcile_lemma(declension, compound)

        except Exception:
            raise ExtractionError(
                "Could not reconcile declension '%s' and '%s'." %
                (declension, compound))

    # format ------------------------------------------------------------------

    def format_morpheme(self, morph, url, lang):
        '''Format the delimiters surrounding `morph` and say if it is affixal.

        This method does NOT take into consideration interfixes.

        This method preserves hyphens (-) before/after affixes and surrounds
        word stems with equal (=) signs.

        The method returns a 2-tuple, where the first element is the formatted
        morpheme and the second element is a boolean indicating if the morpheme
        is affixal.
        '''
        soup = self.get_finnish_soup(url, lang)

        # determine if `morph` is an affix...
        for label in soup.find_all('span', class_='mw-headline'):
            if label.text in self.affixes:
                return morph, True

        # otherwise, if `morph` is a word, temporarily represent all word
        # boundaries as '='
        morph = Extract.OPEN_DELIM_P.sub('=', morph)

        if not morph.startswith('='):
            morph = '=' + morph

        if not morph.endswith('='):
            morph += '='

        return morph, False

    def format_compound(self, compound):
        '''Format the delimiters in `compound`.'''
        if compound.startswith('='):
            compound = compound[1:]

        if compound.endswith('='):
            compound = compound[:-1]

        return compound.lower() \
            .replace('=+', '+') \
            .replace('+=', '+') \
            .replace('==', '=') \
            .replace('=-', '') \
            .replace('-=', '') \
            .replace('-', '')

    def preserve_delimiters(self, orth, compound):
        '''Format the delimiters in `orth` according to those in `compound`.'''
        orth_split = Extract.CHAR_DELIM_P.findall(orth)
        compound_split = Extract.CHAR_DELIM_P.findall(compound)
        compound = ''

        for o, c in zip(orth_split, compound_split):
            compound += c if len(c) > len(o) else o

        return compound

    def basify(self, text):
        '''Strip `text` of delimiters and make it lowercase.'''
        return Extract.DELIMITERS_P.sub('', text).lower()

    # declensions -------------------------------------------------------------

    def get_declensions(self, soup, orth, pos):
        '''Extract the various conjugations of `orth` from `soup`.'''
        declensions = set()

        simplex = ' ' not in orth
        word = orth.rsplit(' ', 1)[-1]
        n = orth.count(' ')

        # for adjectives, include comparative and superlative forms
        if 'ADJ' in pos:
            for tup in Extract.ADJ_FORMS_P.findall(soup.text):
                declensions.update(tup)

        for table in soup.find_all('table', class_='inflection-table'):
            try:
                for d in table.find_all(
                        'span', class_='Latn', string=Extract.MIN_WORD_P):
                    d = d.text

                    # trim auxiliaries, modifiers, etc., and ignore declensions
                    # that do not fully inflect `orth` (e.g., 'olen ajanut' is
                    # not a complete 1.sg. conjugation of the compound
                    # 'ajaa partansa', since 'partansa' is missing)
                    if word in d or simplex:
                        declensions.add(d.split(' ', d.count(' ') - n)[-1])

            except AttributeError:
                pass

        try:
            declensions.remove(orth)

        except KeyError:
            pass

        return list(declensions)

    def split_declension(self, declension, compound):
        '''Split and format `declension` given its lemma `compound`.'''
        goal = self.basify(declension)
        compound = self.reconcile_declension(goal, compound)

        if ' ' in declension or '-' in declension:
            compound = self.preserve_delimiters(declension, compound)

        return compound

    # print -------------------------------------------------------------------

    def _print_error(self, orth, url, error):
        '''Print an informative error message for `orth` to `sys.stderr`.'''
        print('%s (%s) %s: %s' % (
            orth, url, type(error).__name__, str(error)), file=stderr)

    def _buffer_error(self, orth, url, error):
        '''Buffer an informative error message for `orth` to `sys.stderr`.'''
        stderr.buffer.write(('%s (%s) %s: %s\n' % (
            orth, url, type(error).__name__, str(error))).encode('utf-8'))

    def _print_annotation(self, *annotation):
        '''Format and print `annotation` to `sys.stdout`.'''
        print(' : '.join(annotation))

    def _buffer_annotation(self, *annotation):
        '''Format and buffer `annotation` to `sys.stdout`.'''
        stdout.buffer.write((' ; '.join(annotation) + '\n').encode('utf-8'))


class ExtractionError(Exception):
    pass


class HiccupError(ExtractionError):
    pass


class SilentError(ExtractionError):
    pass
