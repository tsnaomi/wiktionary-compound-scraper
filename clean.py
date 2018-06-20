import re


def clean_data(data_fn='data/fi.data'):
    '''Clean the data in `data_fn` and write it to a '.cleaned' file.

    This function removes all duplicate lines of data and all blank lines
    (which initially separate declension sets). It then sorts the data
    alphabetically and writes it to a file named '<data_fn>.cleaned', where
    '<data_fn>' is the name of the file passed into the function.
    '''
    with open(data_fn, 'r+') as f:
        data = f.readlines()

    data = sorted(list(set([line for line in data if line != '\n'])))

    with open(data_fn + '.cleaned', 'w+') as f:
        f.write(''.join(data))


def clean_errors(errors_fn='data/fi.errors'):
    '''Clean the errors in `errors_fn` and write them to a '.cleaned' file.

    This function groups the errors in `errors_fn` by error type/message. It
    then writes the grouped errors to a file named '<errors_fn>.cleaned', where
    '<errors_fn>' is the name of the file passed into the function. Unintended
    errors (i.e., non-ExtractionErrors) are listed first, then
    ExtractionErrors.
    '''
    with open(errors_fn, 'r+') as f:
        errors = f.readlines()

    splitter = re.compile(r'(\w+(?:Error|Warning))')
    specifics = re.compile(r"'[^']+'")
    errors = [splitter.split(e) for e in errors]
    uncaught = []
    extraction = []

    # separate intended `extraction` errors (i.e., ExtractionErrors) from
    # unintended `uncaught` errors encountered during scraping (e.g.,
    # AttributeErrors, IndexErrors)
    for error in errors:
        if error[1] == 'ExtractionError':
            extraction.append(error)

        else:
            uncaught.append(error)

    # sort `uncaught` errors by error type, error message, then by `orth`
    uncaught.sort(key=lambda x: (x[1], x[2], x[0].lower()))

    # sort `extraction` errors by error message, then by `orth`
    extraction.sort(key=lambda x: (x[2], x[0].lower()))

    # separate groups of errors with a newline
    errors = ''
    prev = uncaught[0][1]

    for error in uncaught:
        error_type = error[1]

        if prev != error_type:
            errors += '\n'

        errors += ''.join(error)
        prev = error_type

    for error in extraction:
        msg = error[2]

        if specifics.sub('', prev) != specifics.sub('', msg):
            errors += '\n'

        errors += ''.join(error)
        prev = msg

    with open(errors_fn + '.cleaned', 'w+') as f:
        f.write(''.join(errors))


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--data_fn')
    parser.add_argument('-e', '--errors_fn')
    args = parser.parse_args()

    if args.data_fn:
        clean_data(args.data_fn)

    if args.errors_fn:
        clean_errors(args.errors_fn)
