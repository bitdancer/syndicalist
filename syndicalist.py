# Copyright (c) 2013 by R. David Murray under an MIT license (LICENSE.txt).
import os
import sys
import argparse
import functools
import feedparser
from datetime import datetime
from dinsd import rel, row, ns
from dinsd.sqlite_pickle_db import Database


class FeedmeError(Exception):
    pass

#
# Helpers
#

def new_articles(feedid, feedblob):
    new = rel(db.r.articles.header)()
    with ns(fid=feedid):
        ids = db.r.articles.where('feedid == fid').compute('seqno')
    nextid = functools.reduce(max, ids, next(ids, 0)) + 1
    for a in reversed(feedblob.entries):
        with ns(a=a):
            if db.r.articles.where('guid == a.id'):
                # Do we need to check pubdate in case of update?
                continue
            if 'published_parsed' in a:
                pubdate = datetime(*a.published_parsed[:7])
            else:
                pubdate = datetime(1900, 1, 1)
            new_article = row(guid=a.id,
                              feedid=feedid,
                              seqno=nextid,
                              title=a.title,
                              link=a.link,
                              data=a,
                              pubdate=pubdate,
                              read=False)
            db.r.articles.insert(~new_article)
            new = new | ~new_article
            nextid += 1
    print(new >> {'title', 'pubdate'})

#
# Commands
#

def init(args):
    re = ''
    if args.reinitialize:
        db.close()
        os.remove(DBPATH)
        globals()['db'] = Database(DBPATH)
        re = 're'
        print('Database cleared')
    db['feedlist']  = rel(id=int, url=str, title=str, subtitle=str)
    db.set_key('feedlist', {'id'})
    # Ideally we'd normalize title and subtitle, too, but later for that.
    db['published'] = rel(id=int, published=datetime)
    db.set_key('published', {'id'})
    db['published_unknown'] = rel(id=int)
    db['articles'] = rel(guid=str,
                         feedid=int,
                         seqno=int,
                         title=str,
                         link=str,
                         data=feedparser.FeedParserDict,
                         pubdate=datetime,
                         read=bool)
    db.set_key('articles', {'feedid', 'seqno'})
    print('Database {}initialized'.format(re))

def wipe(args):
    db.close()
    os.remove(DBPATH)

def addfeed(args):
    with ns(newurl=args.url):
        if db.r.feedlist.where('url == newurl'):
            print("Feed already exists in database:", args.url)
            return
    ids = db.r.feedlist.compute('id')
    newid = functools.reduce(max, ids, next(ids, 0)) + 1
    try:
        f = feedparser.parse(args.url)
    except Exception as err:
        print("Unable to read feed {}: {}".format(args.url, err))
        return
    title = f.feed.get('title', '**Unknown Title**')
    subtitle = f.feed.get('subtitle')
    if subtitle is None:
        subtitle = f.feed.get('description', '')
    db.r.feedlist.insert(~row(id=newid,
                              url=args.url,
                              title=title,
                              subtitle=subtitle))
    pubtuple = f.feed.get('published_parsed')
    if pubtuple:
        published = datetime(*pubtuple[:7])
        db.r.published.insert(~row(id=newid, published=published))
    else:
        db.r.published_unknown.insert(~row(id=newid))
    
    print('Added new feed:')
    print((~row(id=newid,
                url=args.url,
                title=title,
                subtitle=subtitle,
                published=str(published) if pubtuple else '',
                )
           ).display('id',
                     'title',
                     'subtitle',
                     'published',
                     'url',
                     )
          )
    new_articles(newid, f)

def listfeeds(args):
    p = db.r.published.extend(
            rel(pubdate=str), pubdate='str(published)') << {'published'}
    np = db.r.published_unknown.extend(pubdate="''")
    feeds = db.r.feedlist & (p | np)
    if args.all:
        cols = ('id', 'title', 'subtitle', 'pubdate', 'url')
    else:
        cols = ('id', 'title', 'url')
    print((feeds >> cols).display(*cols, sort=('title')))

def listarticles(args):
    with ns(wanted=args.feedid):
        articles = db.r.articles.where('feedid == wanted')
        if not articles and not db.r.feedlist.where('id == wanted'):
            raise FeedmeError("Unknown feed id {}".format(args.feedid))
    if args.all:
        cols = ('guid', 'title', 'link', 'pubdate', 'read')
    else:
        cols = ('pubdate', 'title', 'read')
    print((articles >> cols).display(*cols, sort=('pubdate')))

def pollfeed(args):
    with ns(wanted=args.feedid):
        feed = db.r.feedlist.where("id == wanted")
        if not feed:
            raise FeedmeError("Unknown feed id {}".format(args.feedid))
    url = (~feed).url
    try:
        feedblob = feedparser.parse(url)
    except Exception as err:
        print("Unable to read feed {}: {}".format(url, err))
        return
    new_articles(args.feedid, feedblob)

#
# Command parsing
#

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('-D', '--debug', action='store_true',
                        help='turn on debugging')
    parser.add_argument('-d', '--database', default='testdb.sqlite',
                        help='path to sqlite database file')

    sub_parsers = parser.add_subparsers(
        help='Enter <subcommand> --help for subcommand help')

    sub = sub_parsers.add_parser('init', help='initialize database')
    sub.set_defaults(subfunc=init)
    sub.add_argument('-r', '--reinitialize', action='store_true',
                             help='wipe existing database and reinitialize it')

    sub = sub_parsers.add_parser('addfeed', help='add a new rss/atom feed')
    sub.set_defaults(subfunc=addfeed)
    sub.add_argument('url', help='URL of new feed')

    sub = sub_parsers.add_parser('listfeeds', help='list feeds in database')
    sub.set_defaults(subfunc=listfeeds)
    sub.add_argument('-a', '--all', action='store_true', default=False,
                     help='Show all columns')

    sub = sub_parsers.add_parser('listarticles', help='list articles in feed')
    sub.set_defaults(subfunc=listarticles)
    sub.add_argument('feedid', type=int, help='id of feed to list')
    sub.add_argument('-a', '--all', action='store_true', default=False,
                     help='Show all columns')

    sub = sub_parsers.add_parser('pollfeed', help='look for new articles in feed')
    sub.set_defaults(subfunc=pollfeed)
    sub.add_argument('feedid', type=int, help='id of feed to poll')

    args = parser.parse_args()

    if args.debug:
        import dinsd
        dinsd._debug = True

    # XXX The default needs to move to a config file.
    global db, DBPATH
    DBPATH = os.path.abspath(args.database)
    db = Database(DBPATH)

    return args.subfunc(args)
