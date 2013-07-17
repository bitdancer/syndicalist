syndicalist
===========

Syndicalist is a private news feed manager.  You have to have a server to run
it on.  It provides a very simple html (not javascript) UI for reading and
updating your feeds.  Read/unread state is held in the server, so you can
access the web interface from any Internet connected device and see the current
state of your read/unread lists.  The web pages use very simple HTML, and the
content provided by the feeds is sanitized, so the text looks reasonable on any
size device.  Currently articles are kept forever; eventually I'll have to add
a purge function.  Some of the functionality (such as adding feeds) is handled
by a CLI, which you have to stop the server to use.  Eventually I'll probably
add web UI hooks for all of those.

This tool is tailored to my news reading preferences, and is probably not of
interest to anyone else, but it is an example of using the dinsd_ SQL interface
to talk to a database, and is thus an interesting demonstration project for
that, if nothing else.

The code is very rough at this stage, for which I make no apologies.  The only
non-stdlib requirements are my dinsd_ package and the excellent feedparser_
package.  It serves pages using wsgiref, single threaded, which works fine
almost all the time since only one person at a time will ever be hitting the
server :).  Although it looks like a WSGI ap, I haven't learned enough about
WSGI yet to make it so you could actually include it in another site.

Given that I developed this for my personal use after the demise of Google
Reader, I'm not currently putting up any documentation about how to set it up
or use it.  If you'd nevertheless like to give it a try, please email me
questions.  If anyone else wants to use it, I will document it.

Oh, yeah, and syndicalist requires Python 3.4, which isn't even in Beta yet
as I write this...

.. _dinsd: http://github.com/bitdancer/dinsd
.. _feedparser: https://pypi.python.org/pypi/feedparser/
