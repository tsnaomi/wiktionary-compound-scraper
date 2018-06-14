import re

from os.path import commonprefix
from sys import stderr
from urllib.request import urlopen

from bs4 import BeautifulSoup


WIKI_URL = 'https://en.wiktionary.org'

LANGUAGES = {
    'Finnish': 'fi',
    'Afrikaans': 'af',
    'German': 'de',
    'English': 'en',
}

GRAMMAR = {
    # number
    'singular': 'sg',
    'plural': 'pl',

    # case
    'nominative': 'nom',
    'genitive': 'gen',
    'accusative': 'acc',
    'partitive': 'part',
    'inessive': 'ine',
    'elative': 'ela',
    'illative': 'ill',
    'adessive': 'ade',
    'ablative': 'abl',
    'allative': 'all',
    'essive': 'ess',
    'abessive': 'abe',
    'comitative': 'com',
    'translative': 'transl',
    'instructive': 'instruct',
}

AFFIXES = [
    'prefix',
    'suffix',
    'infix',
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

ETYMOLOGY_P = r'(?:^(?:Compound of )?|\+\u200e )(\S+)'


def commonsuffix(texts):
    ''' '''
    return commonprefix([t[::-1] for t in texts])[::-1]


class Extract:
    ''' '''

    def __init__(self, lang):
        self.lang = lang.title()
        self.code = LANGUAGES[self.lang]
        self.walk()

    # extraction --------------------------------------------------------------

    def walk(self, url=None):
        ''' '''
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

                except IndexError as error:  # TODO
                    raise error

                except Exception as error:
                    print('%s (%s) %s: %s' % (
                        a.text,                     # word
                        WIKI_URL + a.get('href'),   # full href
                        str(type(error))[8:-2],     # error type
                        str(error),                 # error message
                        ), file=stderr)

        if page.text == 'next page':
            return self.walk(WIKI_URL + page.get('href'))

    def extract(self, orth, href):
        ''' '''
        soup = BeautifulSoup(urlopen(WIKI_URL + href), 'html.parser')
        compound = self.get_compound(orth, soup)

        if compound:

            pos = self.get_pos(soup)

            if pos in ['noun', 'proper noun', 'adjective']:

                try:

                    declensions = self.get_declensions(compound, soup, orth)

                    for orth, split, msd, num in declensions:
                        annotation = ' ; '.join([orth, split, pos, msd, num])
                        # print(annotation)

                    # TODO: superlatives, comparatives

                    # TODO: get_gradation

                    return

                except AttributeError:
                    pass

            # print(orth, pos)
            annotation = ' ; '.join([orth, compound, pos, '*'])
            # print(annotation)

    # compound segmentation ---------------------------------------------------

    # def _get_compound(self, orth, soup):
        # '''Indicate the word boundaries in `orth` with an equal (=) sign.'''
        # etymology = soup.find_all(string='Etymology')[-1] \
        #     .find_parent(['h3', 'h4']).find_next_sibling(['p'])
        # length = etymology.text.count('+') + 1  # the max. number of words
        # compound = []

        # for i in etymology.find_all('i', class_='Latn', limit=length):
        #     a = i.find('a')

        #     if a and ('-' not in a.text or self.is_word(a)):
        #         text = a.text.replace('-', '')

        #     else:
        #         text = i.text

        #     if ' ' in text:
        #         import pdb; pdb.set_trace()

        #     compound.append(text)

        # compound = '='.join(compound).lower()
        # compound = re.sub(r'=-|-=', '-', compound)

        # test = self.strip_delimiters(compound)
        # gold = self.strip_delimiters(orth).lower()

        # if test == gold:
        #     return compound.replace('-', '')

        # split = re.split(r'([=\-]+)', compound)

        # compound = self.repair_compound(split, test, gold, compound)
        # test = self.strip_delimiters(compound)

        # if test == gold:
        #     return compound

        # print('**** %s != %s' % (orth, compound))
        # raise ValueError('%s != %s' % (orth, compound))

    def get_compound(self, orth, soup):
        '''Indicate the word boundaries in `orth` with an equal (=) sign.'''
        etymology = self.get_etymology(orth, soup)
        # compound = re.sub(r'=-|-=', '-', '='.join(etymology).lower())  # TODO
        compound = etymology

        test = self.strip_delimiters(compound)
        gold = self.strip_delimiters(orth).lower()

        if test == gold:
            return compound.replace('-', '')

        split = re.split(r'([=\-]+)', compound)

        compound = self.repair_compound(split, gold)
        test = self.strip_delimiters(compound)

        if test == gold:
            return compound

        raise ValueError('%s != %s' % (orth, compound))

    def _get_etymology(self, orth, soup):
        ''' '''
        pattern = r'([\w\d\-äöÄÖ]+)(?: +\+ +([\w\d\-äöÄÖ]+)+)'
        candidates = []
        errors = []

        for etym in soup.find_all(
                class_='mw-headline',
                string=re.compile(r'^Etymology')):

            etym = etym.find_parent(['h3', 'h4']).find_next_sibling(['p'])

            for span in etym.find_all('span'):
                span.decompose()

            text = etym.text.replace('\u200e', '')
            candidates = re.findall(pattern, text)

            for split in candidates:
                split = list(split)

                if '-' in ''.join(split):

                    for i, comp in enumerate(split):
                        if '-' in comp:
                            a_tag = etym.find('i', string=comp).find('a')

                            if not a_tag or self._is_word(a_tag):
                                split[i] = comp.replace('-', '')

                compound = '='.join(split).lower()
                compound = re.sub(r'(?:=-)|(?:-=)', '-', compound)

                return compound

    def _is_word(self, a_tag):  # TODO: Finnish Wiktionary
        ''' '''
        url = WIKI_URL + a_tag.get('href')

        if 'new' in a_tag.get('class', []):
            raise ValueError('Could not verify word: %s' % url)

        soup = BeautifulSoup(urlopen(url), 'html.parser')
        headers = soup.find_all('span', class_='mw-headline')

        return all([h.text not in AFFIXES for h in headers])

    def get_etymology(self, orth, soup):
        ''' '''
        candidates = []
        errors = []
        etymologies = soup.find_all(
                class_='mw-headline',
                string=re.compile(r'^Etymology'))

        for etym in etymologies:
            etym = etym.find_parent(['h3', 'h4']).find_next_sibling(['p'])

            for span in etym.find_all('span'):
                span.decompose()

            etym_ = [e for e in re.split(r',|(?: or )', str(etym)) if '+' in e]

            for e in etym_:
                compound = []
                soup = BeautifulSoup(e, 'html.parser')
                n = soup.text.count('+') + 1

                try:
                    for i in soup.find_all('i', class_='Latn', limit=n):
                        # import pdb; pdb.set_trace()
                        if '+' in str(i.previous_sibling) or '+' in str(i.next_sibling):
                            a = i.find('a')

                            if not a or ('-' not in a.text or self.is_word(a)):
                                text = i.text.replace('-', '')

                            else:
                                text = i.text

                            compound.append(text.lower())

                    compound = '='.join(compound)
                    if '-' in compound:
                        import pdb; pdb.set_trace()
                    compound = re.sub(r'(?:=-)|(?:-=)', '-', compound)
                    candidates.append(compound)

                except ValueError as error:
                    errors.append(error)

            if candidates:
                break

        # print(orth, candidates)

        try:
            compound = candidates[0]

            if len(candidates) > 1:
                print(candidates)
                import pdb; pdb.set_trace()

            return compound

        except IndexError:
            raise errors[0]

    # def _get_etymology(self, orth, soup):
        # '''Return the etymology of `orth` as a list of morphemes/words.'''
        # try:
        #     etymology = soup.find(
        #         class_='mw-headline',
        #         string=re.compile(r'^Etymology(?: 1)?'),
        #         ).find_parent(['h3', 'h4']).find_next_sibling(['p'])

        # except IndexError:
        #     raise ValueError('Could not locate etymology.')

        # length = etymology.text.count('+') + 1  # the max. number of words
        # split = []

        # for i in etymology.find_all('i', class_='Latn', limit=length):
        #     a = i.find('a')

        #     if a and ('-' not in a.text or self.is_word(a)):
        #         text = a.text.replace('-', '')

        #     else:
        #         text = i.text

        #     split.append(text)

        # return split

    def is_word(self, a_tag):  # TODO: Finnish Wiktionary
        ''' '''
        url = WIKI_URL + a_tag.get('href')

        if 'new' in a_tag.get('class', []):
            raise ValueError('Could not verify word: %s' % url)

        soup = BeautifulSoup(urlopen(url), 'html.parser')
        headers = soup.find_all('span', class_='mw-headline')

        return all([h.text not in AFFIXES for h in headers])

    def repair_compound(self, split, gold):
        '''Reconcile the etymology and surface form of a compound.'''
        compound = []
        base = gold

        for comp in reversed(split):

            if comp in '-=':
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
                    # import pdb; pdb.set_trace()
                    raise ValueError(
                        'Could not reconcile: %s & %s' % (split, gold))

        return ''.join(reversed(compound))

    def strip_delimiters(self, text):
        '''Strip `text` of any delimiters.'''
        return re.sub(r'[=\- *]+', '', text)

    # part of speech ----------------------------------------------------------

    def get_pos(self, soup):
        '''Return the (first) part of speech listed in `soup`.'''
        for header in soup.find_all('span', class_='mw-headline'):
            header = header.text.lower()

            if header in POS[self.code]:
                return header

        raise ValueError('Could not identify part of speech.')

    # orthographies -----------------------------------------------------------

    def get_adjectives(self, soup):
        ''' '''
        pass

    def get_declensions(self, compound, soup, orth):
        ''' '''
        table = soup.find('table', attrs={'class': 'inflection-table'})
        prefix, pivot = self.get_prefix(compound, table, orth)

        try:

            rows = table.find_all('tr', attrs={'class': 'vsHide'})
            rows = [[td for td in tr.find_all('td')] for tr in rows]

            for i, row in enumerate(filter(None, rows)):
                for j, words in enumerate(row):
                    for a in words.find_all('span', attrs={'class': 'Latn'}):
                        word = re.sub(r'(—*\n)', '', a.text)

                        # try:
                        #     assert re.sub(r'[=\-]+', '', self.split(prefix, pivot, word)) == re.sub(r'[=\-]+', '', word)
                        # except AssertionError:
                        #     import pdb; pdb.set_trace()
                        #     pass

                        yield (
                            word,
                            self.split(prefix, pivot, word),
                            self.msd[i],
                            self.num[j],
                            )

        except AttributeError:
            self.build_grammar(table)
            self.get_declensions(orth, compound, soup)

    def split(self, prefix, pivot, orth):
        ''' '''
        return prefix + orth[pivot:]

    def get_prefix(self, compound, table, orth):
        ''' '''
        # if orth == 'aaltomaisuus':
        #     import pdb; pdb.set_trace()
        try:
            declensions = table.find_all('span', attrs={'class': 'Latn'})
            declensions = list(set([i.text for i in declensions]))
            prefix = commonprefix(declensions)
            declensions.remove(orth)

        except ValueError:
            declensions = table.find_all('a')
            declensions = list(set([i.text for i in declensions]))
            prefix = commonprefix(declensions)
            declensions.remove(orth)

        i = len(prefix)
        j = len(orth)

        # if orth == 'aaltomaisuus':
        #     import pdb; pdb.set_trace()

        prefix = compound[:-(j - i)] if j > i else compound

        # try:
        #     assert prefix in compound
        # except AssertionError:
        #     import pdb; pdb.set_trace()
        #     pass

        return prefix, i

    def repair_prefix(self, compound, table, orth):
        ''' '''

    def build_grammar(self, table):
        ''' '''
        rows = table.find_all('th', attrs={'colspan': '2'})
        rows = re.sub(r'\n', '', ' '.join([th.text for th in rows]))
        rows = rows[rows.index('  '):].split()
        rows = [GRAMMAR[th] for th in rows]

        if self.code == 'fi':
            rows = ['nom', 'acc-' + rows[0], 'acc-' + rows[1]] + rows[1:]
            self.msd = {k: v for k, v in zip(range(len(rows)), rows)}
            self.num = {0: 'sg', 1: 'pl'}


class ExtractionError(Exception):  # TODO
    ''' '''
    pass


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--lang', default='Finnish')
    args = parser.parse_args()

    Extract(args.lang)
