import os
from wsgiref import simple_server, util

examples_path = os.path.join(os.path.split(__file__)[0], 'testdata')

def app(environ, respond):
    fn = os.path.join(examples_path, environ['PATH_INFO'][1:])
    if '.' not in fn.split(os.path.sep)[-1]:
        fn = os.path.join(fn, 'index.html')
    type = mimetypes.guess_type(fn)[0]
    if os.path.exists(fn):
        respond('200 OK', [('Content-Type', type)])
        return util.FileWrapper(open(fn, "rb"))
    else:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        return ['not found']

examples_server = simple_server.make_server('', 0, app)
