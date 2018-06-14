import re

from os.path import commonprefix
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

CHANGES = {
    'fi': [
        lambda x: re.sub(r'(nen)=', 's', x),  # nen -> s
        lambda x: re.sub(r'(si)=', 's', x),  # si -> s
    ],
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
        self.errors = []
        self.pos = set()

        self.walk()
        self.write_errors()
        self.write_pos()

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

                except Exception as error:
                    # self.errors.append('%s ( %s ) %s: %s' % (
                    #     a.text,                     # word
                    #     WIKI_URL + a.get('href'),   # full href
                    #     str(type(error))[8:-2],     # error type
                    #     str(error),                 # error message
                    #     ))
                    msg = '%s (%s) %s: %s' % (
                        a.text,                     # word
                        WIKI_URL + a.get('href'),   # full href
                        str(type(error))[8:-2],     # error type
                        str(error),                 # error message
                        )
                    print(msg)
                    # import pdb; pdb.set_trace()
                    self.errors.append(msg)

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

    def get_compound(self, orth, soup):
        '''Indicate the word boundaries in `orth` with an equal (=) sign.'''
        # extract the compound constituents from `soup`
        etymology = soup.find_all(string='Etymology')[-1] \
            .find_parent(['h3', 'h4']).find_next_sibling(['p'])
        length = etymology.text.count('+') + 1  # the number of constituents
        split = [i.text for i in etymology.find_all('i', limit=length)]
        compound = '='.join(split).replace('-', '').lower()

        # orig = compound  # for debugging
        test = self.strip_delimiters(compound)
        gold = self.strip_delimiters(orth).lower()

        if test == gold:
            return compound

        compound = self.repair_compound(split, test, gold, compound)
        test = self.strip_delimiters(compound)

        if test == gold:
            return compound

        print(orth, split, compound)
        import pdb; pdb.set_trace()
        print()
        pass


        # # return the compound split (`compound`) if the undelimited compound is
        # # equivalent to the undelimited orthography (`gold`)
        # if test == gold:
        #     return compound

        # n = 0

        # while test != gold:
        #     compound = self.repair_compound(orth, test, gold, compound)
        #     test = self.strip_delimiters(compound)

        #     if n == 4:
        #         print(orth, orig, compound)
        #         import pdb; pdb.set_trace()

        #     n += 1

        # return compound

        # new = self.repair_compound(orth, test, gold, compound)
        # test = self.strip_delimiters(new)

        # if test == gold:
        #     return compound

        # print(orth, compound, new)
        # import pdb; pdb.set_trace()

        # # # attempt to repair the compound split so that its undelimited form is
        # # # equivalent to the undelimited orthography; repairs are made through
        # # # rule-based morphological alternations approximated in `CHANGES`
        # # for change in CHANGES[self.code]:
        # #     new = change(compound)

        # #     if self.strip_delimiters(new) == gold:
        # #         return new

        # # if it was not possible to repair the compound split...
        # raise ValueError('%s != %s' % (orth, compound))

    def repair_compound(self, split, test, gold, compound):
        ''' '''
        x = re.findall(r'(=\S{3})', compound)
        y = [i.replace('=', '') for i in x]

        new = gold

        for i, j in zip(x, y):
            new = new.replace(j, i, 1)

        print(gold, new, compound)
        return new

    def adfad_repair_compound(self, split, test, gold, compound):
        ''' '''
        prefix = commonprefix([gold, test])
        suffix = commonsuffix([gold, test])
        alternation = gold[len(prefix):-len(suffix)]
        indices = [0, ] + [i for i, w in enumerate(compound) if w == '=']
        pre = '='.join([prefix[i:j] for i, j in zip(indices, indices[1:])])
        new = pre + alternation + '=' + suffix
        test = prefix + alternation + suffix

        if test != gold or new.count('=') != compound.count('='):
            import pdb; pdb.set_trace()

        return new
        pass
        pass
        pass
        pass

    def bas_repair_compound(self, split, test, gold, compound):
        ''' '''
        prefix = commonprefix([gold, test])
        suffix = commonsuffix([gold, test])
        alternation = gold[len(prefix):-len(suffix)]
        indices = [0, ] + [i for i, x in enumerate(compound) if x == '=']
        prefix = '='.join([prefix[i:j] for i, j in zip(indices, indices[1:])])
        compound = prefix + alternation + suffix
        last = - len(split[-1])
        compound = compound[:last] + '=' + compound[last:]

        return compound
 
    def _repair_compound(self, orth, test, gold, compound):
        ''' '''
        # if orth == 'aikasytytyksinen':
        #     import pdb; pdb.set_trace()
        prefix = commonprefix([gold, test])
        suffix = commonsuffix([gold, test])
        former = test[len(prefix):-len(suffix)]

        if former:
            former += '='
            replacement = gold[len(prefix):-len(suffix)] + '='

        else:
            print(orth, compound)
            import pdb; pdb.set_trace()
            former = test[:-len(suffix)] + '='
            replacement = gold[:-len(suffix)] + '='

        return compound.replace(former, replacement)

        # suffix = commonsuffix([gold, test])
        # test_prefix = test[:-len(suffix)] + '='
        # gold_prefix = gold[:-len(suffix)] + '='

        # return compound.replace(test_prefix, gold_prefix)

    def __repair_compound(self, orth, test, gold, compound):
        ''' '''
        split = compound.split('=')
        compound = []

        for i, word in enumerate(split):
            try:
                index = len(commonprefix([word, gold]))
                index += gold[index:].index(split[i + 1])
                word, gold = gold[:index], gold[index:]
                compound.append(word)

            except IndexError:
                compound.append(word)

            except ValueError:
                print('uh oh here...')
                import pdb; pdb.set_trace()

        compound = '='.join(compound)
        print(orth, compound, split)

        return '='.join(compound)

    def strip_delimiters(self, text):
        '''Strip `text` of any delimiters.'''
        return re.sub(r'[=\- ]+', '', text)

    # part of speech ----------------------------------------------------------

    def get_pos(self, soup, header='h3'):
        ''' '''
        for a in soup.find_all(header):
            if not a.text.startswith(('Alternative forms', 'Etymology', 'Pronunciation')):
                pos = a.text

                try:
                    pos = pos[:pos.index('[')].lower()

                except ValueError:
                    pos = self.get_pos(soup, 'h4') if header != 'h4' else ''

                self.pos.add(pos)
                return pos

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

    def write_errors(self):
        ''' '''
        filename = './%s.errors' % self.code

        with open(filename, 'w+') as f:
            f.write('\n'.join(self.errors))

    def write_pos(self):
        ''' '''
        filename = './%s.pos' % self.code

        with open(filename, 'w+') as f:
            f.write('\n'.join(list(self.pos)))


if __name__ == '__main__':
    Extract('Finnish')
