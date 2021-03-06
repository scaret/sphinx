# -*- coding: utf-8 -*-
"""
    sphinx.directives.code
    ~~~~~~~~~~~~~~~~~~~~~~

    :copyright: Copyright 2007-2016 by the Sphinx team, see AUTHORS.
    :license: BSD, see LICENSE for details.
"""

import sys
import codecs
from difflib import unified_diff

from six import string_types

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import ViewList

from sphinx import addnodes
from sphinx.locale import _
from sphinx.util import parselinenos
from sphinx.util.nodes import set_source_info

if False:
    # For type annotation
    from typing import Any  # NOQA
    from sphinx.application import Sphinx  # NOQA


class Highlight(Directive):
    """
    Directive to set the highlighting language for code blocks, as well
    as the threshold for line numbers.
    """

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = {
        'linenothreshold': directives.unchanged,
    }

    def run(self):
        # type: () -> List[nodes.Node]
        if 'linenothreshold' in self.options:
            try:
                linenothreshold = int(self.options['linenothreshold'])
            except Exception:
                linenothreshold = 10
        else:
            linenothreshold = sys.maxsize
        return [addnodes.highlightlang(lang=self.arguments[0].strip(),
                                       linenothreshold=linenothreshold)]


def dedent_lines(lines, dedent):
    # type: (List[unicode], int) -> List[unicode]
    if not dedent:
        return lines

    new_lines = []
    for line in lines:
        new_line = line[dedent:]
        if line.endswith('\n') and not new_line:
            new_line = '\n'  # keep CRLF
        new_lines.append(new_line)

    return new_lines


def container_wrapper(directive, literal_node, caption):
    # type: (Directive, nodes.Node, unicode) -> nodes.container
    container_node = nodes.container('', literal_block=True,
                                     classes=['literal-block-wrapper'])
    parsed = nodes.Element()
    directive.state.nested_parse(ViewList([caption], source=''),
                                 directive.content_offset, parsed)
    if isinstance(parsed[0], nodes.system_message):
        raise ValueError(parsed[0])
    caption_node = nodes.caption(parsed[0].rawsource, '',
                                 *parsed[0].children)
    caption_node.source = parsed[0].source
    caption_node.line = parsed[0].line
    container_node += caption_node
    container_node += literal_node
    return container_node


class CodeBlock(Directive):
    """
    Directive for a code block with special highlighting or line numbering
    settings.
    """

    has_content = True
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = {
        'linenos': directives.flag,
        'dedent': int,
        'lineno-start': int,
        'emphasize-lines': directives.unchanged_required,
        'caption': directives.unchanged_required,
        'class': directives.class_option,
        'name': directives.unchanged,
    }

    def run(self):
        # type: () -> List[nodes.Node]
        code = u'\n'.join(self.content)

        linespec = self.options.get('emphasize-lines')
        if linespec:
            try:
                nlines = len(self.content)
                hl_lines = [x+1 for x in parselinenos(linespec, nlines)]
            except ValueError as err:
                document = self.state.document
                return [document.reporter.warning(str(err), line=self.lineno)]
        else:
            hl_lines = None

        if 'dedent' in self.options:
            lines = code.split('\n')
            lines = dedent_lines(lines, self.options['dedent'])
            code = '\n'.join(lines)

        literal = nodes.literal_block(code, code)
        literal['language'] = self.arguments[0]
        literal['linenos'] = 'linenos' in self.options or \
                             'lineno-start' in self.options
        literal['classes'] += self.options.get('class', [])
        extra_args = literal['highlight_args'] = {}
        if hl_lines is not None:
            extra_args['hl_lines'] = hl_lines
        if 'lineno-start' in self.options:
            extra_args['linenostart'] = self.options['lineno-start']
        set_source_info(self, literal)

        caption = self.options.get('caption')
        if caption:
            try:
                literal = container_wrapper(self, literal, caption)
            except ValueError as exc:
                document = self.state.document
                errmsg = _('Invalid caption: %s' % exc[0][0].astext())  # type: ignore
                return [document.reporter.warning(errmsg, line=self.lineno)]

        # literal will be note_implicit_target that is linked from caption and numref.
        # when options['name'] is provided, it should be primary ID.
        self.add_name(literal)

        return [literal]


class LiteralInclude(Directive):
    """
    Like ``.. include:: :literal:``, but only warns if the include file is
    not found, and does not raise errors.  Also has several options for
    selecting what to include.
    """

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    option_spec = {
        'dedent': int,
        'linenos': directives.flag,
        'lineno-start': int,
        'lineno-match': directives.flag,
        'tab-width': int,
        'language': directives.unchanged_required,
        'encoding': directives.encoding,
        'pyobject': directives.unchanged_required,
        'lines': directives.unchanged_required,
        'start-after': directives.unchanged_required,
        'end-before': directives.unchanged_required,
        'start-at': directives.unchanged_required,
        'end-at': directives.unchanged_required,
        'prepend': directives.unchanged_required,
        'append': directives.unchanged_required,
        'emphasize-lines': directives.unchanged_required,
        'caption': directives.unchanged,
        'class': directives.class_option,
        'name': directives.unchanged,
        'diff': directives.unchanged_required,
    }

    def read_with_encoding(self, filename, document, codec_info, encoding):
        # type: (unicode, nodes.Node, Any, unicode) -> List
        try:
            with codecs.StreamReaderWriter(open(filename, 'rb'), codec_info[2],
                                           codec_info[3], 'strict') as f:
                lines = f.readlines()
                lines = dedent_lines(lines, self.options.get('dedent'))  # type: ignore
                return lines
        except (IOError, OSError):
            return [document.reporter.warning(
                'Include file %r not found or reading it failed' % filename,
                line=self.lineno)]
        except UnicodeError:
            return [document.reporter.warning(
                'Encoding %r used for reading included file %r seems to '
                'be wrong, try giving an :encoding: option' %
                (encoding, filename))]

    def run(self):
        # type: () -> List[nodes.Node]
        document = self.state.document
        if not document.settings.file_insertion_enabled:
            return [document.reporter.warning('File insertion disabled',
                                              line=self.lineno)]
        env = document.settings.env
        rel_filename, filename = env.relfn2path(self.arguments[0])

        if 'pyobject' in self.options and 'lines' in self.options:
            return [document.reporter.warning(
                'Cannot use both "pyobject" and "lines" options',
                line=self.lineno)]

        if 'lineno-match' in self.options and 'lineno-start' in self.options:
            return [document.reporter.warning(
                'Cannot use both "lineno-match" and "lineno-start"',
                line=self.lineno)]

        if 'lineno-match' in self.options and \
           (set(['append', 'prepend']) & set(self.options.keys())):
            return [document.reporter.warning(
                'Cannot use "lineno-match" and "append" or "prepend"',
                line=self.lineno)]

        if 'start-after' in self.options and 'start-at' in self.options:
            return [document.reporter.warning(
                'Cannot use both "start-after" and "start-at" options',
                line=self.lineno)]

        if 'end-before' in self.options and 'end-at' in self.options:
            return [document.reporter.warning(
                'Cannot use both "end-before" and "end-at" options',
                line=self.lineno)]

        encoding = self.options.get('encoding', env.config.source_encoding)
        codec_info = codecs.lookup(encoding)

        lines = self.read_with_encoding(filename, document,
                                        codec_info, encoding)
        if lines and not isinstance(lines[0], string_types):
            return lines

        diffsource = self.options.get('diff')
        if diffsource is not None:
            tmp, fulldiffsource = env.relfn2path(diffsource)

            difflines = self.read_with_encoding(fulldiffsource, document,
                                                codec_info, encoding)
            if not isinstance(difflines[0], string_types):
                return difflines
            diff = unified_diff(
                difflines,
                lines,
                diffsource,
                self.arguments[0])
            lines = list(diff)

        linenostart = self.options.get('lineno-start', 1)
        objectname = self.options.get('pyobject')
        if objectname is not None:
            from sphinx.pycode import ModuleAnalyzer
            analyzer = ModuleAnalyzer.for_file(filename, '')
            tags = analyzer.find_tags()
            if objectname not in tags:
                return [document.reporter.warning(
                    'Object named %r not found in include file %r' %
                    (objectname, filename), line=self.lineno)]
            else:
                lines = lines[tags[objectname][1]-1: tags[objectname][2]-1]
                if 'lineno-match' in self.options:
                    linenostart = tags[objectname][1]

        linespec = self.options.get('lines')
        if linespec:
            try:
                linelist = parselinenos(linespec, len(lines))
            except ValueError as err:
                return [document.reporter.warning(str(err), line=self.lineno)]

            if 'lineno-match' in self.options:
                # make sure the line list is not "disjoint".
                previous = linelist[0]
                for line_number in linelist[1:]:
                    if line_number == previous + 1:
                        previous = line_number
                        continue
                    return [document.reporter.warning(
                        'Cannot use "lineno-match" with a disjoint set of '
                        '"lines"', line=self.lineno)]
                linenostart = linelist[0] + 1
            # just ignore non-existing lines
            lines = [lines[i] for i in linelist if i < len(lines)]
            if not lines:
                return [document.reporter.warning(
                    'Line spec %r: no lines pulled from include file %r' %
                    (linespec, filename), line=self.lineno)]

        linespec = self.options.get('emphasize-lines')
        if linespec:
            try:
                hl_lines = [x+1 for x in parselinenos(linespec, len(lines))]
            except ValueError as err:
                return [document.reporter.warning(str(err), line=self.lineno)]
        else:
            hl_lines = None

        start_str = self.options.get('start-after')
        start_inclusive = False
        if self.options.get('start-at') is not None:
            start_str = self.options.get('start-at')
            start_inclusive = True
        end_str = self.options.get('end-before')
        end_inclusive = False
        if self.options.get('end-at') is not None:
            end_str = self.options.get('end-at')
            end_inclusive = True
        if start_str is not None or end_str is not None:
            use = not start_str
            res = []
            for line_number, line in enumerate(lines):
                if not use and start_str and start_str in line:
                    if 'lineno-match' in self.options:
                        linenostart += line_number + 1
                    use = True
                    if start_inclusive:
                        res.append(line)
                elif use and end_str and end_str in line:
                    if end_inclusive:
                        res.append(line)
                    break
                elif use:
                    res.append(line)
            lines = res

        prepend = self.options.get('prepend')
        if prepend:
            lines.insert(0, prepend + '\n')

        append = self.options.get('append')
        if append:
            lines.append(append + '\n')

        text = ''.join(lines)
        if self.options.get('tab-width'):
            text = text.expandtabs(self.options['tab-width'])
        retnode = nodes.literal_block(text, text, source=filename)
        set_source_info(self, retnode)
        if diffsource:  # if diff is set, set udiff
            retnode['language'] = 'udiff'
        if 'language' in self.options:
            retnode['language'] = self.options['language']
        retnode['linenos'] = 'linenos' in self.options or \
                             'lineno-start' in self.options or \
                             'lineno-match' in self.options
        retnode['classes'] += self.options.get('class', [])
        extra_args = retnode['highlight_args'] = {}
        if hl_lines is not None:
            extra_args['hl_lines'] = hl_lines
        extra_args['linenostart'] = linenostart
        env.note_dependency(rel_filename)

        caption = self.options.get('caption')
        if caption is not None:
            if not caption:
                caption = self.arguments[0]
            try:
                retnode = container_wrapper(self, retnode, caption)
            except ValueError as exc:
                document = self.state.document
                errmsg = _('Invalid caption: %s' % exc[0][0].astext())  # type: ignore
                return [document.reporter.warning(errmsg, line=self.lineno)]

        # retnode will be note_implicit_target that is linked from caption and numref.
        # when options['name'] is provided, it should be primary ID.
        self.add_name(retnode)

        return [retnode]


def setup(app):
    # type: (Sphinx) -> None
    directives.register_directive('highlight', Highlight)
    directives.register_directive('highlightlang', Highlight)  # old
    directives.register_directive('code-block', CodeBlock)
    directives.register_directive('sourcecode', CodeBlock)
    directives.register_directive('literalinclude', LiteralInclude)
