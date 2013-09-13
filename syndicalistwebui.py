#!/usr/bin/env python3
# Copyright (c) 2013 by R. David Murray under an MIT license (LICENSE.txt).
import os
import operator
import functools
import contextlib
import mimetypes
import threading
import time
from wsgiref import simple_server
from wsgiref.util import FileWrapper
from urllib.parse import parse_qs, urlencode
from util import Trie
import feedparser
import syndicalist as syn
import dinsd

import dinsd.sqlite_pickle_db
# XXX: Fix this.
syn.DBPATH = 'webtestdb.sqlite'
syn.db = dinsd.sqlite_pickle_db.Database(syn.DBPATH)
#syn.db = dinsd.sqlite_pickle_db.Database(syn.DBPATH, debug_sql=True)
# Work around the fact that dinsd doesn't persist keys yet.  Having a key on
# this table is necessary because the feedparser hash function has a bug
# in it, so we can't depend on it when doing update and delete operations
# in sqlite (or indexing).
syn.db.set_key('articles', {'feedid', 'seqno'})
print(len(syn.db.r.articles), len(syn.db._system_ns.current['_sys_key_articles']))

class NotFound(Exception):
    pass

class Redirect(Exception):
    pass

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
                if environ['PATH_INFO']:
                    return notfound(environ, respond)
                return func(environ, respond)
            handler = no_args
        paths[path] = handler
        return handler
    return add_path

def refresh_feeds():
    for feed in syn.db.r.feedlist:
        try:
            syn.new_articles(feed.id, feedparser.parse(feed.url))
        except Exception as err:
            print("Error updating {}: {}".format(feed.url, err))

class UpdateThread(threading.Thread):
    def run(self):
        while True:
            time.sleep(60*60)
            refresh_feeds()
            # XXX Need 'clean_feeds' here too, to delete > N read articles

def app(environ, respond):
    path = environ['PATH_INFO']
    handler, remainder = paths.get_longest_match(path)
    environ['PATH_INFO'] = remainder
    try:
        return handler(environ, respond)
    except NotFound as err:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        return byte_me([str(err)])
    except Redirect as ex:
        respond('302 Redirect',
                [('Location', environ['SCRIPT_NAME'] + str(ex))])
        return [b'']

@handles_path('', args=True)
def notfound(environ, respond):
    raise NotFound('Path {!r} not found'.format(environ['PATH_INFO']))

@handles_path('/')
def feedlist(environ, respond):
    respond('200 OK', [('Content-Type', 'text/html; charset=utf-8')])
    yield from byte_me(page('Feedme Feed List', feedlist_content(environ)))

@handles_path('/refresh')
def refresh_all(environ, respond):
    refresh_feeds()
    raise Redirect('/')

def _get_feed_from_args(environ):
    args = environ['PATH_INFO']
    try:
        feedid = int(args)
    except ValueError as err:
        raise NotFound('Invalid feed id {}'.format(args)) from err
    with dinsd.ns(feedid=feedid):
        feed = syn.db.r.feedlist.where('id == feedid')
        if not feed:
            raise NotFound('Feed {} not found in DB'.format(feedid))
    return feedid, feed

@handles_path('/feed/', args=True)
def articlelist(environ, respond):
    showall = environ['QUERY_STRING']
    if showall and showall != 'showall':
        raise NotFound('Invalid query string {}'.format(showall))
    feedid, feed = _get_feed_from_args(environ)
    respond('200 OK', [('Content-Type', 'text/html; charset=utf-8')])
    return byte_me(page((~feed).title, articlelist_content(feedid, showall)))

@handles_path('/feed/refresh/', args=True)
def refresh_feed(environ, respond):
    feedid, feed = _get_feed_from_args(environ['PATH_INFO'])
    syn.new_articles(feedid, feedparser.parse((~feed).url))
    raise Redirect('/feed/{}'.format(feedid))

def _get_article_from_args(environ):
    args = environ['PATH_INFO']
    try:
        feedid, seqno = map(int, args.split('/'))
    except ValueError:
        raise NotFound('Invalid articleid id {}'.format(args))
    with dinsd.ns(fid=feedid, sno=seqno):
        feed = syn.db.r.feedlist.where('id == fid')
        if not feed:
            raise NotFound('Feed {} not found in DB'.format(feedid))
        article = ~syn.db.r.articles.where('feedid==fid and seqno==sno')
        if not article:
            raise NotFound('article {} not found in DB'.format(args))
    return feedid, seqno, feed, article

def _change_article_read(environ, respond, changefunc, successurl):
    feedid, seqno, _, _ = _get_article_from_args(environ)
    with dinsd.ns(fid=feedid, sno=seqno, changefunc=changefunc):
        syn.db.r.articles.update('feedid==fid and seqno==sno',
                                    read="changefunc(read)")
    raise Redirect(successurl.format(feedid=feedid, seqno=seqno))

@handles_path('/feed/nav/markread/', args=True)
def feed_mark_article_read(environ, respond):
    _change_article_read(environ, respond, lambda x: True, '/feed/{feedid}')

@handles_path('/article/', args=True)
def article(environ, respond):
    args = environ['PATH_INFO']
    try:
        feedid, seqno = map(int, args.split('/'))
    except ValueError:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid articleid id {}'.format(args)])
        return
    with dinsd.ns(fid=feedid, sno=seqno):
        feed = syn.db.r.feedlist.where('id == fid')
        if not feed:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['Feed {} not found in DB'.format(feedid)])
            return
        article = syn.db.r.articles.where('feedid==fid and seqno==sno')
        if not article:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['article {} not found in DB'.format(args)])
            return
    article = ~article
    if 'content' in article.data:
        content_type = article.data.content[0].type
    else:
        content_type = 'text/html'
    respond('200 OK', [('Content-Type', content_type + '; charset=utf-8')])
    yield from byte_me(page('{}: {}'.format((~feed).title, article.title),
                            article_content(article),
                            h1=(link((~feed).title, '/feed/{}'.format(feedid)) +
                                ':<br>' + link(article.title, article.link))))

@handles_path('/article/nav/prev/', args=True)
def article_prev(environ, respond):
    return _article_nav(environ, respond, -1)

@handles_path('/article/nav/next/', args=True)
def article_prev(environ, respond):
    return _article_nav(environ, respond, 1)

def _article_nav(environ, respond, direction):
    args = environ['PATH_INFO']
    try:
        feedid, seqno = map(int, args.split('/'))
    except ValueError:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        yield from byte_me(['Invalid articleid id {}'.format(args)])
        return
    nextsno = seqno+direction
    with dinsd.ns(fid=feedid, sno=seqno, nextsno=nextsno):
        feed = syn.db.r.feedlist.where('id == fid')
        if not feed:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['Feed {} not found in DB'.format(feedid)])
            return
        article = syn.db.r.articles.where('feedid==fid and seqno==sno')
        if not article:
            respond('404 Not Found', [('Content-Type', 'text/plain')])
            yield from byte_me(['article {} not found in DB'.format(args)])
            return
        article = syn.db.r.articles.where('feedid==fid and seqno==nextsno')
        if article:
            nextpage = '/article/nav/markread/{}/{}'.format(feedid, nextsno)
        else:
            nextpage = '/'
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
    _change_article_read(environ, respond, changefunc,
                         '/article/{feedid}/{seqno}')

@handles_path('/static/', args=True)
def static(environ, respond):
    fn = environ['PATH_INFO']
    mimetype = mimetypes.guess_type(fn)[0]
    if os.path.exists(fn):
        respond('200 OK', [('Content-Type', mimetype)])
        return FileWrapper(open(fn, "rb"))
    else:
        respond('404 Not Found', [('Content-Type', 'text/plain')])
        return ['not found']


# Layout Functions.

def page(title, content, h1=None):
    if h1 is None:
        h1 = title
    yield '<html>'
    yield '<head>'
    yield '  <title>'
    yield '    Feedme: ' + title
    yield '  </title>'
    yield '  <meta name="viewport" content="width=device-width">'
    yield '  <script language="JavaScript" src="/static/swipesense.js"></script>'
    yield '</head>'
    yield '<body bgcolor="#000000" text="#FFFFFF" link="#FFFFFF" vlink="#FFFFFF"'
    yield '      id="body" ontouchstart="touchStart(event, \'body\');"'
    yield '                ontouchend="touchEnd(event);"'
    yield '                ontouchmove="touchMove(event);"'
    yield '                ontouchcancel="touchCancel(event);">'
    yield '  <h1 style="max-width: 8in">{}</h1>'.format(h1)
    yield '  <table>'
    for part in content:
        yield '    <tr><td>'
        for line in part:
            yield '      ' + line
        yield '    </td></tr>'
    yield '  </table>'
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

def linktable(*links):
    yield '<table width="100%">'
    yield '  <tr>'
    yield '    <td align="left">{}</td>'.format(links[0])
    for link in links[1:-1]:
        yield '    <td align="center">{}</td>'.format(link)
    if len(links) > 1:
        yield '    <td align="right">{}</td>'.format(links[-1])
    yield '  </tr>'
    yield '</table>'

def link(text, url, settings=None, style=None):
    style = ' style="{}" '.format(style) if style else ' '
    if settings:
        url = url + '?' + urlencode(settings)
    return '<a{}href="{}">{}</a>'.format(style, url, text)

def feedlist_content(environ):
    settings = parse_qs(environ['QUERY_STRING'])
    showall = settings.get('showall', False)
    with dinsd.ns(articles=syn.db.r.articles):
        feedlist = syn.db.r.feedlist.extend(unread=
            'len(articles.where("feedid=={} and not read".format(id)))')
    selectfunc = (lambda x: True) if showall else (lambda x: x)
    feedlist = [(x.unread, x.title, x.id, x.url)
                for x in feedlist if selectfunc(x.unread)]
    feedlist.sort(key=operator.itemgetter(1))
    feedlist = [(u, link(t, '/feed/{}'.format(i)), url)
                for (u, t, i, url) in feedlist]
    yield table(('Unread', 'Title', 'URL'), feedlist)
    yield linktable(
       link('Refresh All', '/refresh'),
       link('Hide Read' if showall else 'Show All',
            '/' + '' if showall else '?showall=1'))

def articlelist_content(feedid, showall):
    with dinsd.ns(id=feedid):
        articles = syn.db.r.articles.where(
            'feedid == id' + ('' if showall else ' and not read'))
    yield linktable(
        link('Refresh', '/feed/refresh/{}'.format(feedid)),
        link('Hide Read' if showall else 'Show All',
                  '/feed/{}'.format(feedid) + '' if showall else '?showall'),
        link('Feed List', '/'))
    if articles:
            articles = [(x.title, x.seqno, x.pubdate,
                         x.data.author_detail.get('name', '')
                            if 'author_detail' in x.data else '')
                        for x in articles]
            articles.sort(key=operator.itemgetter(1))
            articles = [(link(t,
                              '/article/nav/markread/{}/{}'.format(feedid, n)),
                         a,
                         '{:%Y-%m-%d %H:%M}'.format(p),
                         link('X',
                              '/feed/nav/markread/{}/{}'.format(feedid, n)))
                        for (t, n, p, a) in articles]
            yield table(('Title', 'Author', 'Published', ''), articles)
    yield linktable(
        link('Refresh', '/feed/refresh/{}'.format(feedid)),
        link('Hide Read' if showall else 'Show All',
                  '/feed/{}'.format(feedid) + '' if showall else '?showall'),
        link('Feed List', '/'))

def article_content(article):
    feedid = article.feedid
    seqno = article.seqno
    readstate = 'Mark Unread' if article.read else 'Mark Read'
    aid = str(feedid) + '/' + str(seqno)
    yield article_body(article)
    yield linktable(
        link('Prev', '/article/nav/prev/' + aid),
        link(readstate, '/article/nav/toggleread/' + aid),
        link('Next', '/article/nav/next/' + aid))

def article_body(article):
    with dinsd.ns(fid=article.feedid):
        unreadcount = len(syn.db.r.articles.where('feedid==fid and not read'))
    unreadlabel = '({} unread)'.format(unreadcount)
    yield '<div style="max-width:8in">'
    # XXX: Do 'today' and 'yesterday' and weekdays
    if 'author_detail' in article.data and 'name' in article.data.author_detail:
        author = ' by ' + article.data.author_detail.name
    else:
        author = ''
    byline = 'Posted {:%Y-%m-%d %H:%M}{}'.format(article.pubdate, author)
    for line in linktable(byline, '', unreadlabel):
        yield '  ' + line
    if 'content' in article.data:
        if (len(article.data.summary) < 200
                and not '<img' in article.data.summary):
            yield '  <em>{}</em>'.format(article.data.summary)
        for line in article.data.content[0].value.splitlines():
            yield '  ' + line
    else:
        for line in article.data.summary.splitlines():
            yield '  ' + line
    yield '</div>'


syn_server = simple_server.make_server('', 8080, app)
try:
    update_thread = UpdateThread(daemon=True)
    update_thread.start()
    syn_server.serve_forever()
except KeyboardInterrupt:
    syn.db.close()
