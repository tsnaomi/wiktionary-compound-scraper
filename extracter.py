import argparse

import extract

from lang import get_lang_and_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--lang', default='Finnish')
    parser.add_argument('-g', '--grammar_fn', default=None)
    parser.add_argument('-d', '--debug_li', nargs='*', default=[])
    parser.add_argument('-D', '--debug_fn', default='')
    parser.add_argument('-u', '--url', default=None)
    parser.add_argument('-p', '--find_likely_pos', action='store_true')
    args = parser.parse_args()

    lang, code = get_lang_and_code(args.lang)
    Extract = getattr(extract, code, extract).Extract
    E = Extract(lang=lang, code=code, grammar_fn=args.grammar_fn)

    # if `debug_li` is given, only extract the words listed in `debug_li`...
    if args.debug_li:
        E.debug(debug_li=args.debug_fn if args.debug_fn else args.debug_li)

    # if `find_likely_pos` is given, only extract potential parts of speech...
    elif args.find_likely_pos:
        E.find_likely_pos()

    # otherwise, scrape Wiktionary for all relevant simplex and complex words
    # in the target language (`lang`)
    else:
        E.walk(url=args.url)


if __name__ == '__main__':
    main()
