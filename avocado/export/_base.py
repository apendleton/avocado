import functools
from multiprocessing.pool import ThreadPool
from avocado.models import DataView
from avocado.formatters import registry as formatters
from cStringIO import StringIO


class BaseExporter(object):
    "Base class for all exporters"
    short_name = 'base'
    file_extension = 'txt'
    content_type = 'text/plain'
    preferred_formats = ()

    def __init__(self, concepts=None, preferred_formats=None):
        if preferred_formats is not None:
            self.preferred_formats = preferred_formats

        if concepts is None:
            concepts = ()
        elif isinstance(concepts, DataView):
            node = concepts.parse()
            concepts = node.get_concepts_for_select()

        self.params = []
        self.row_length = 0
        self.concepts = concepts

        self._header = []

        for concept in concepts:
            formatter_class = formatters.get(concept.formatter)
            self.add_formatter(formatter_class, concept=concept)

        self._format_cache = {}

    def __repr__(self):
        return u'<{0}: {1}/{2}>'.format(self.__class__.__name__,
                                        len(self.params), self.row_length)

    def add_formatter(self, formatter_class, concept=None, keys=None,
                      index=None):

        # Initialize a formatter instance.
        formatter = formatter_class(concept=concept,
                                    keys=keys,
                                    formats=self.preferred_formats)

        length = len(formatter.field_names)

        params = (formatter, length)
        self.row_length += length

        if index is not None:
            self.params.insert(index, params)
        else:
            self.params.append(params)

        # Get the expected fields from this formatter to build
        # up the header.
        meta = formatter.get_meta(exporter=self.short_name.lower())
        header = meta['header']

        if index is not None:
            self._header = (self._header[:index] +
                            list(header) +
                            self._header[index:])
        else:
            self._header.extend(header)

    @property
    def header(self):
        return tuple(self._header)

    def get_file_obj(self, name=None):
        if name is None:
            return StringIO()

        if isinstance(name, basestring):
            return open(name, 'w+')

        return name

    def _format_row(self, row, kwargs=None):
        _row = []

        for formatter, length in self.params:
            values, row = row[:length], row[length:]

            _row.extend(formatter(values, kwargs=kwargs))

        return tuple(_row)

    def _cache_format_row(self, row, kwargs=None):
        _row = []

        for formatter, length in self.params:
            values, row = row[:length], row[length:]

            key = (formatter, values)

            if key not in self._format_cache:
                segment = formatter(values, kwargs=kwargs)

                self._format_cache[key] = segment
            else:
                segment = self._format_cache[key]

            _row.extend(segment)

        return tuple(_row)

    def read(self, iterable, *args, **kwargs):
        "Reads an iterable and generates formatted rows."
        for row in iterable:
            yield self._format_row(row, kwargs=kwargs)

    def cached_read(self, iterable, *args, **kwargs):
        """Reads an iterable and generates formatted rows.

        This read implementation caches the output segments of the input
        values and can significantly speed up formatting at the expense of
        memory.

        The benefit of this method is dependent on the data. If there is
        high variability in the data, this method may not perform well.
        """
        self._format_cache = {}

        for row in iterable:
            yield self._cache_format_row(row, kwargs=kwargs)

    def threaded_read(self, iterable, threads=None, *args, **kwargs):
        """Reads an iterable and generates formatted rows.

        This read implementation starts a pool of worker threads to format
        the data in parallel.
        """
        pool = ThreadPool(threads)

        f = functools.partial(self._format_row,
                              kwargs=kwargs)

        for row in pool.map(f, iterable):
            yield row

    def cached_threaded_read(self, iterable, threads=None, *args, **kwargs):
        """Reads an iterable and generates formatted rows.

        This read implementation combines the `cached_read` and `threaded_read`
        methods.
        """
        self._format_cache = {}

        pool = ThreadPool(threads)

        f = functools.partial(self._cache_format_row,
                              kwargs=kwargs)

        for row in pool.map(f, iterable):
            yield row

    def manual_read(self, iterable, force_distinct=True, offset=None,
                    limit=None, *args, **kwargs):
        """Reads an iterable and generates formatted rows.

        This method must be used if columns were added to the query to get
        particular ordering, but are not part of the concepts being handled.

        If `force_distinct` is true, rows will be filtered based on the slice
        of the row that is going to be formatted.

        If `offset` is defined, only rows that are produced after the offset
        index are returned.

        If `limit` is defined, once the limit has been reached (or the
        iterator is exhausted), the loop will exit.
        """
        emitted = 0
        unique_rows = set()

        for i, row in enumerate(iterable):
            if limit is not None and emitted >= limit:
                break

            _row = row[:self.row_length]

            if force_distinct:
                _row_hash = hash(tuple(_row))

                if _row_hash in unique_rows:
                    continue

                unique_rows.add(_row_hash)

            if offset is None or i >= offset:
                emitted += 1

                yield self._format_row(_row, kwargs=kwargs)

    def write(self, iterable, *args, **kwargs):
        for row in iterable:
            yield row
