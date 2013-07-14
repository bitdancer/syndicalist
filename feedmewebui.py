#!/usr/bin/env python3
import os
import operator
import functools
import contextlib
from wsgiref import simple_server, util
from util import Trie
import feedparser
import feedme
# Tempoary
import sys
sys.path.append('/home/rdmurray/src/dinsd/src')
import dinsd

# XXX: Fix this.
feedme.DBPATH = 'webtestdb.sqlite'
import dinsd.sqlite_pickle_db
feedme.db = dinsd.sqlite_pickle_db.Database(feedme.DBPATH)

def byte_me(iterator):
    for line in iterator:
        yield line.encode('utf-8') + b'\r\n'

paths = Trie()
def handles_path(path, args=False):
    def add_path(func):
        handler = func
        if not args:
            @functools.wraps(func)
            def no_args(environ, respond):
                if environ['PATH_REMAINDER']:
                    return notfound(environ, respond)
                return func(environ, respond)
            handler = no_args
        paths[path] = handler
        return handler
    return add_path

def app(environ, respond):
    path = environ['PATH_INFO']
    handler, remainder = paths.get_longest_match(path)
    # XXX: Should we be modifying PATH_INFO instead?
    environ['PATH_REMAINDER'] = remainder
    return handler(environ, respond)

@handles_path('', args=True)
def notfound(environ, respond):
    respond('404 Not Found', [('Content-Type', 'text/plain')])
    return byte_me(['Path {!r} not found'.format(environ['PATH_INFO'])])

@handles_path('/')
def feedlist(environ, respond):
    respond('200 OK', [('Content-Type', 'text/html')]) 
    yield from byte_me(page('Feedme Feed List', feedlist_content()))

@handles_path('/feed/', args=True)
def articlelist(environ, respond):
    showall = environ['QUERY_STRING']
    if showall and showall != 'showall':
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid query string {}'.format(showall)])
        return
    args = environ['PATH_REMAINDER']
    try:
        feedid = int(args)
    except ValueError:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid feed id {}'.format(args)])
        return
    with dinsd.ns(feedid=feedid):
        feed = feedme.db.r.feedlist.where('id == feedid')
        if not feed:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['Feed {} not found in DB'.format(feedid)])
            return
    respond('200 OK', [('Content-Type', 'text/html')]) 
    yield from byte_me(page('Article List for {}'.format((~feed).title),
                            articlelist_content(feedid, showall)))

@handles_path('/feed/refresh/', args=True)
def refresh_feed(environ, respond):
    args = environ['PATH_REMAINDER']
    try:
        feedid = int(args)
    except ValueError:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid feed id {}'.format(args)])
        return
    with dinsd.ns(feedid=feedid):
        feed = feedme.db.r.feedlist.where('id == feedid')
        if not feed:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['Feed {} not found in DB'.format(feedid)])
            return
    feedme.new_articles(feedid, feedparser.parse((~feed).url))
    respond('302 Redirect',
            [('Location', '/feed/{}'.format(feedid))])
    yield b''

@handles_path('/article/', args=True)
def article(environ, respond):
    args = environ['PATH_REMAINDER']
    try:
        feedid, seqno = map(int, args.split('/'))
    except ValueError:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid articleid id {}'.format(args)])
        return
    with dinsd.ns(fid=feedid, sno=seqno):
        feed = feedme.db.r.feedlist.where('id == fid')
        if not feed:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['Feed {} not found in DB'.format(feedid)])
            return
        article = feedme.db.r.articles.where('feedid==fid and seqno==sno')
        if not article:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['article {} not found in DB'.format(args)])
            return
    article = ~article
    respond('200 OK', [('Content-Type', article.data.content[0].type)]) 
    yield from byte_me(page('{}: {}'.format((~feed).title, article.title),
                            article_content(article)))

@handles_path('/article/nav/prev/', args=True)
def article_prev(environ, respond):
    return _article_nav(environ, respond, -1)

@handles_path('/article/nav/next/', args=True)
def article_prev(environ, respond):
    return _article_nav(environ, respond, 1)

def _article_nav(environ, respond, direction):
    args = environ['PATH_REMAINDER']
    try:
        feedid, seqno = map(int, args.split('/'))
    except ValueError:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid articleid id {}'.format(args)])
        return
    nextsno = seqno+direction
    with dinsd.ns(fid=feedid, sno=seqno, nextsno=nextsno):
        feed = feedme.db.r.feedlist.where('id == fid')
        if not feed:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['Feed {} not found in DB'.format(feedid)])
            return
        article = feedme.db.r.articles.where('feedid==fid and seqno==sno')
        if not article:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['article {} not found in DB'.format(args)])
            return
        article = feedme.db.r.articles.where('feedid==fid and seqno==nextsno')
        if article:
            nextpage = '/article/nav/markread/{}/{}'.format(feedid, nextsno)
        else:
            nextpage = '/feed/{}'.format(feedid)
    respond('302 Redirect', [('Location', nextpage)])
    yield b''

@handles_path('/article/nav/toggleread/', args=True)
def article_toggleread(environ, respond):
    return _article_setread(environ, respond, lambda x: not x)

@handles_path('/article/nav/markread/', args=True)
def article_markread(environ, respond):
    return _article_setread(environ, respond, lambda x: True)

@handles_path('/article/nav/markunread/', args=True)
def article_markunread(environ, respond):
    return _article_setread(environ, respond, lambda x: False)

def _article_setread(environ, respond, changefunc):
    args = environ['PATH_REMAINDER']
    try:
        feedid, seqno = map(int, args.split('/'))
    except ValueError:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid articleid id {}'.format(args)])
        return
    with dinsd.ns(fid=feedid, sno=seqno, changefunc=changefunc):
        feed = feedme.db.r.feedlist.where('id == fid')
        if not feed:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['Feed {} not found in DB'.format(feedid)])
            return
        article = ~feedme.db.r.articles.where('feedid==fid and seqno==sno')
        if not article:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['article {} not found in DB'.format(args)])
            return
        feedme.db.r.articles.update('feedid==fid and seqno==sno',
                                    read="changefunc(read)")
    respond('302 Redirect',
            [('Location', '/article/{}/{}'.format(feedid, seqno))])
    yield b''


# Layout Functions.

def page(title, content):
    yield '<html>'
    yield '<head>'
    yield '  <title>'
    yield '    ' + title
    yield '  </title>'
    yield '</head>'
    yield '<body>'
    yield '  <h1>{}</h1>'.format(title)
    for line in content:
        yield '  ' + line
    yield '</body>'
    yield '</html>'

def table(titlerow, content_rows):
    yield '<table border=1>'
    yield '  <tr>'
    for title in titlerow:
        yield '    <th style="max-width: 8in">{}</th>'.format(title)
    yield '  </tr>'
    for row in content_rows:
        yield '  <tr>'
        for item in row:
            yield '    <td style="max-width: 8in">{}</td>'.format(item)
        yield '  </tr>'
    yield '</table>'

def link(text, url, style=None):
    style = ' style="{}" '.format(style) if style else ' '
    return '<a{}href="{}">{}</a>'.format(style, url, text)

def feedlist_content():
    with dinsd.ns(articles=feedme.db.r.articles):
        feedlist = feedme.db.r.feedlist.extend(unread=
            'len(articles.where("feedid=={} and not read".format(id)))')
    feedlist = [(x.unread, x.title, x.id) for x in feedlist]
    feedlist.sort(key=operator.itemgetter(1))
    feedlist = [(u, link(t, '/feed/{}'.format(i))) for (u, t, i) in feedlist]
    yield from table(('Unread', 'Title'), feedlist)

def articlelist_content(feedid, showall):
    with dinsd.ns(id=feedid):
        articles = feedme.db.r.articles.where(
            'feedid == id' + ('' if showall else ' and not read'))
    articles = [(x.title, x.seqno, x.data.summary, x.pubdate) for x in articles]
    articles.sort(key=operator.itemgetter(3))
    articles = [(link(t, '/article/nav/markread/{}/{}'.format(feedid, n)), s, p)
                for (t, n, s, p) in articles]
    yield from table(('Title', 'Summary', 'Published'), articles)
    yield '<p style="text-align: center">'
    yield '  ' + link('Refresh', '/feed/refresh/{}'.format(feedid), style='float: left')
    yield '  ' + link('Show Unread' if showall else 'Show All',
                      '/feed/{}'.format(feedid) + '' if showall else '?showall')
    yield '  ' + link('Feed List', '/', style='float: right')
    yield '</p>'

def article_content(article):
    feedid = article.feedid
    seqno = article.seqno
    readstate = 'Mark Unread' if article.read else 'Mark Read'
    yield '<div style="max-width:8.5in">'
    for line in article.data.content[0].value.splitlines():
        yield '  ' + line
    yield '  <p></p>'
    yield '  <p style="text-align:center">'
    yield ('    <a style="float:left" href="/article/nav/prev/{}/{}">'
                    'Prev</a>'.format(feedid, seqno))
    yield ('    <a href="/article/nav/toggleread/{}/{}">'
                    '{}</a>'.format(feedid, seqno, readstate))
    yield ('    <a style="float:right" href="/article/nav/next/{}/{}">'
                    'Next</a>'.format(feedid, seqno))
    yield '  </p>'
    yield '</div>'


feedme_server = simple_server.make_server('', 8080, app)
feedme_server.serve_forever()
