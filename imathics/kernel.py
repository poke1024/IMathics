import sys
import traceback

from ipykernel.kernelbase import Kernel

from mathics.core.definitions import Definitions
from mathics.core.evaluation import Evaluation, Message, Result
from mathics.core.expression import Integer
from mathics.core.parser import parse_lines, IncompleteSyntaxError, TranslateError, MathicsScanner, ScanError
from mathics.builtin import builtins
from mathics import settings
from mathics.version import __version__
from mathics.doc.doc import Doc
import os
import base64
from datetime import datetime, timezone, timedelta


def _timestamp_micros():
    zero = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - zero) // timedelta(microseconds=1)

class MathicsKernel(Kernel):
    implementation = 'Mathics'
    implementation_version = '0.1'
    language_info = {
        'version': __version__,
        'name': 'Mathematica',
        'mimetype': 'text/x-mathematica',
    }
    banner = "Mathics kernel"   # TODO

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
        self.definitions = Definitions(add_builtin=True)        # TODO Cache
        self.definitions.set_ownvalue('$Line', Integer(0))  # Reset the line number

    def do_execute(self, code, silent, store_history=True, user_expressions=None,
                   allow_stdin=False):
        # TODO update user definitions

        response = {
            'payload': [],
            'user_expressions': {},
        }

        evaluation = Evaluation(self.definitions, result_callback=self.result_callback, out_callback=self.out_callback)
        try:
            results = evaluation.parse_evaluate(code, timeout=settings.TIMEOUT)
        except Exception as exc:
            # internal error
            response['status'] = 'error'
            response['ename'] = 'System:exception'
            response['traceback'] = traceback.format_exception(*sys.exc_info())
            results = []
        else:
            response['status'] = 'ok'
        response['execution_count'] = self.definitions.get_line_no()
        return response

    def out_callback(self, out):
        if out.is_message:
            content = {
                'name': 'stderr',
                'text': '{symbol}::{tag}: {text}\n'.format(**out.get_data()),
            }
        elif out.is_print:
            content = {
                'name': 'stdout',
                'text': out.text + '\n',
            }
        else:
            raise ValueError('Unknown out')
        self.send_response(self.iopub_socket, 'stream', content)

    def result_callback(self, result):
        html = result.data['text/html']

        anchor_name = 'output_anchor_' + str(_timestamp_micros())

        js = """
        <script>
            requirejs(['nbextensions/imathics/imathics'], function(imathics) {
                imathics.display('%s', '%s');
            }, function (err) {
                document.getElementById('%s').innerHTML = '<span style="color:red;">' +
                    'The Jupyter nbextension for Mathics was not found. Please reinstall imathics.</span>';
            });
        </script>
        """ % (anchor_name, base64.b64encode(html.encode('utf8')).decode('ascii'), anchor_name)

        content = {
            'execution_count': result.line_no,
            'data': {'text/html': ("<span id='%s'></span>" % anchor_name) + js},
            'metadata': result.metadata,
        }
        self.send_response(self.iopub_socket, 'execute_result', content)

    def do_inspect(self, code, cursor_pos, detail_level=0):
        start_pos, end_pos, name = self.find_symbol_name(code, cursor_pos)

        if name is None:
            return {'status': 'error'}

        if '`' not in name:
            name = 'System`' + name

        try:
            instance = builtins[name]
        except KeyError:
            return {'status': 'ok', 'found': False, 'data': {}, 'metadata': {}}

        doc = Doc(instance.__doc__ or '')
        data = {
            'text/plain': str(doc),
            # TODO latex
            # TODO html
        }
        return {'status': 'ok', 'found': True, 'data': data, 'metadata': {}}

    def do_complete(self, code, cursor_pos):
        start_pos, end_pos, name = self.find_symbol_name(code, cursor_pos)

        if name is None:
            return {'status': 'error'}

        remove_system = False
        system_prefix = 'System`'
        if '`' not in name:
            name = system_prefix + name
            remove_system = True

        matches = []
        for key in builtins:
            if key.startswith(name):
                matches.append(key)

        if remove_system:
            matches = [match[len(system_prefix):] for match in matches]

        return {
            'status': 'ok',
            'matches': matches,
            'cursor_start': start_pos,
            'cursor_end': end_pos,
            'metadata': {},
        }

    def do_is_complete(self, code):
        try:
            # list forces generator evaluation (parse all lines)
            list(parse_lines(code, self.definitions))
        except IncompleteSyntaxError:
            return {'status': 'incomplete', 'indent': ''}
        except TranslateError:
            return {'status': 'invalid'}
        else:
            return {'status': 'complete'}

    @staticmethod
    def find_symbol_name(code, cursor_pos):
        '''
        Given a string of code tokenize it until cursor_pos and return the final symbol name.
        returns None if no symbol is found at cursor_pos.

        >>> MathicsKernel.find_symbol_name('1 + Sin', 6)
        'System`Sin'

        >>> MathicsKernel.find_symbol_name('1 + ` Sin[Cos[2]] + x', 8)
        'System`Sin'

        >>> MathicsKernel.find_symbol_name('Sin `', 4)
        '''

        scanner = MathicsScanner()
        scanner.build()
        scanner.lexer.input(code)

        start_pos = None
        end_pos = None
        name = None
        while True:
            try:
                token = scanner.lexer.token()
            except ScanError:
                scanner.lexer.skip(1)
                continue
            if token is None:
                break   # ran out of tokens
            # find first token which contains cursor_pos
            if scanner.lexer.lexpos >= cursor_pos:
                if token.type == 'symbol':
                    name = token.value
                    start_pos = token.lexpos
                    end_pos = scanner.lexer.lexpos
                break
        return start_pos, end_pos, name
