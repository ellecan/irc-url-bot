#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License version 2 for
# more details.
#
# You should have received a copy of the GNU General Public License version 2
# along with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import socket
import time
import re
import urllib2
import htmlentitydefs
from threading import Thread
from BeautifulSoup import BeautifulSoup
import os
import sys
import datetime
import ssl
import contextlib


html_pattern = re.compile("&(\w+?);")
html_pattern2 = re.compile("&#([0-9]+);")
html_pattern3 = re.compile("&#[xX]([0-9a-fA-F]+);")


def date():
    return datetime.datetime.now().isoformat()


def myprint(str):
    print "%s: %s" % (date(), str)
    sys.stdout.fileno()


def html_entity_decode_char(m):
    try:
        return unicode(htmlentitydefs.entitydefs[m.group(1)], "latin1")
    except KeyError:
        return m.group(0)


def html_entity_decode(string):
    string = html_pattern.sub(html_entity_decode_char, string)
    string = html_pattern2.sub(lambda x: unichr(int(x.group(1))), string)
    string = html_pattern3.sub(lambda x: unichr(int(x.group(1), 16)), string)
    return string


class Sender(object):
    def __init__(self, urlbot, to, url, at_time):
        self.thread = Thread(target=self.process)
        self.to = to
        self.url = url
        self.urlbot = urlbot
        self.at_time = at_time

    def start(self):
        self.thread.start()

    def join(self):
        self.thread.join()

    def test(self):
        return self.thread.is_alive()

    def process(self):
        while time.time() < self.at_time:
            time.sleep(1)
        myprint("process %r" % self.url)
        # initialize the title variable
        title = None
        try:
            # make sure we close the urlopen
            request = urllib2.Request(self.url, headers=self.urlbot.request_headers)
            with contextlib.closing(urllib2.urlopen(request)) as request:
                # only try to fetch title if the url point to text/html
                if request.headers.get("Content-Type", "").startswith("text/html"):
                    if "charset=" in request.headers["Content-Type"]:
                        charset = request.headers["Content-Type"].split(
                            "charset="
                        )[1].split(";")[0].strip()
                        soup = BeautifulSoup(
                            request.read(self.urlbot.max_page_size).decode(charset, errors="ignore")
                        )
                    else:
                        soup = BeautifulSoup(request.read(self.urlbot.max_page_size))
                    if len(soup.title.string) > self.urlbot.title_length:
                        title = soup.title.string[0:self.urlbot.title_length] + u'…'
                    else:
                        title = soup.title.string
        except urllib2.HTTPError as e:
            sys.stderr.write("HTTPError when fetching %s : %s\n" % (e.url, e))
            return
        # if title is not set and fallback_notitle is True
        if not title and self.urlbot.fallback_notitle:
            title = []
            # add type and format info
            if "Content-Type" in request.headers:
                try:
                    (typ, forma) = request.headers['Content-type'].split(";", 1)[0].split("/", 1)
                    title.append("Type: %s, Format: %s" % (typ, forma))
                except ValueError:
                    pass
            # add size info
            if "Content-Length" in request.headers:
                try:
                    length = int(request.headers["Content-Length"])
                    suffixs = ["B", "KB", "MB", "GB", "TB", "PB"]
                    for suffix in suffixs:
                        if length > 1024.0 * 4 / 3:
                            length = length / 1024.0
                        else:
                            break
                    length = round(length, 2)
                    title.append("Size: %.2f%s" % (length, suffix))
                except ValueError:
                    pass
            title = ", ".join(title)
        # only return title if defined and not empty
        if title:
            self.urlbot.say(self.to, html_entity_decode(title.replace('\n', ' ').strip()))


class UrlBot(object):
    def __init__(
      self, network, chans, nick, port=6667, debug=0, title_length=300, max_page_size=1048576,
      irc_timeout=360.0, message_delay=3, charset='utf-8', nickserv_pass=None, blacklist=None,
      ignore=None, cafile=None, tls=False, fallback_notitle=True, request_headers=None
    ):
        self.chans = chans
        self.nick = nick
        self.title_length = title_length
        self.max_page_size = max_page_size
        nick_int = 0
        nick_bool = False
        nick_next = 0
        connected = False
        self.charset = charset
        self.irc = None
        self.idler = None
        self.M = None
        self.debug = debug
        self.last_message = 0
        self.message_delay = message_delay
        if blacklist is None:
            self.blacklist = []
        else:
            self.blacklist = [re.compile(bl) for bl in blacklist]
        if ignore is None:
            self.ignore = []
        else:
            self.ignore = [re.compile(bl) for bl in ignore]
        self.fallback_notitle = fallback_notitle
        if request_headers is None:
            self.request_headers = {"Accept-Language": "en-US,en;q=0.5,*;q=0.3"}
        else:
            self.request_headers = request_headers

        self.url_regexp = re.compile(
            """((?:[a-z][\\w-]+:(?:/{1,3}|[a-z0-9%])|www\\d{0,3}[.]|[a-z0-9.\\-]+[.][a-z]{2,4}/"""
            """)(?:[^\\s()<>]+|\\(([^\\s()<>]+|(\\([^\\s()<>]+\\)))*\\))+(?:\\(([^\\s()<>]+|(\\"""
            """([^\\s()<>]+\\)))*\\)|[^\\s`!()\\[\\]{};:'".,<>?«»""'']))"""
        )

        while True:
            try:
                self.irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if tls is True:
                    context = ssl.create_default_context(cafile=cafile)
                    self.irc = context.wrap_socket(self.irc, server_hostname=network)
                self.irc.settimeout(irc_timeout)
                myprint("Connection to irc")
                self.irc.connect((network, port))
                # print(self.irc.recv ( 4096 ))
                self.send(u'USER %s %s %s :Python IRC' % (nick, nick, nick))
                self.send(u'NICK %s' % nick)
                while True:
                    data = self.irc.recv(4096)
                    if len(data) == 0:
                        break
                    data = data.split("\n")
                    for data in data:
                        if self.debug != 0:
                            try:
                                myprint(data)
                            except:
                                pass
                        data_split = data.split(' ', 4)
                        if len(data_split) > 1:
                            code = data_split[1]
                        else:
                            code = 0

                        if data.find(b'PING') != -1:
                            self.irc.send(b'PONG ' + data.split()[1] + b'\r\n')

                        if code in ['004', '376'] and not connected:
                            connected = True
                            if nickserv_pass:
                                self.say(u'nickserv', u'IDENTIFY %s' % nickserv_pass)
                                time.sleep(0.5)
                            for chan in self.chans:
                                myprint(u"Join %r" % chan)
                                self.send(u'JOIN %s' % chan)
                        elif code == '433':  # Nickname is already in use
                            if not connected:
                                self.send(u'NICK %s%s' % (nick, nick_int))
                                nick_int += 1
                            else:
                                nick_next = time.time() + 10
                            nick_bool = True
                        elif code == 'INVITE':
                            chan = unicode(data.split(':', 2)[2].strip(), self.charset)
                            myprint("Invited on %s." % chan)
                            if chan.lower() in [
                              chan.lower().split(' ', 1)[0].strip() for chan in self.chans
                            ]:
                                myprint(u"Join %r" % chan)
                                self.send(u'JOIN %s' % chan)
                        elif code == 'PRIVMSG':
                            dest = data_split[2]
                            src = data_split[0][1:]
                            if dest.startswith('#'):
                                if not any(bl.match(src) for bl in self.ignore):
                                    to = dest
                                    to = unicode(to, self.charset)

                                    for url in self.url_regexp.findall(data):
                                        url = url[0]
                                        if not url.startswith('http'):
                                            url = 'http://'+url
                                        if not any(bl.match(url) for bl in self.blacklist):
                                            Sender(self, to, url, self.last_message).start()
                                            self.last_message = (
                                                max(
                                                    time.time(),
                                                    self.last_message
                                                ) + self.message_delay
                                            )

                        if connected:
                            if nick_bool and time.time() > nick_next:
                                self.send(u'NICK %s' % nick)
                                nick_bool = False

            finally:
                if self.irc:
                    try:
                        self.irc.close()
                    except:
                        pass
                connected = False
                time.sleep(2)

    def say(self, chan, str):
        msg = u'PRIVMSG %s :%s\r\n' % (chan, str)
        if self.debug != 0:
            myprint(msg.encode(self.charset))
        self.irc.send(msg.encode(self.charset))

    def notice(self, chan, str):
        msg = u'NOTICE %s :%s\r\n' % (chan, str)
        if self.debug != 0:
            myprint(msg.encode(self.charset))
        self.irc.send(msg.encode(self.charset))

    def send(self, str):
        msg = u'%s\r\n' % str
        if self.debug != 0:
            myprint(msg.encode(self.charset))
        self.irc.send(msg.encode(self.charset))


if __name__ == '__main__':
    import imp

    params_name = UrlBot.__init__.func_code.co_varnames[:UrlBot.__init__.func_code.co_argcount][1:]
    default_args = UrlBot.__init__.func_defaults
    argc = len(params_name) - len(default_args)
    params = dict(
        [
            (
                params_name[i],
                None if i < argc else default_args[i - argc]
            ) for i in range(0, len(params_name))
        ]
    )

    def get_param(str):
        ret = None
        if str in sys.argv:
            i = sys.argv.index(str)
            if len(sys.argv) > i:
                ret = sys.argv[i+1]
                del(sys.argv[i+1])
            del(sys.argv[i])
        return ret

    def check_params(arg):
        if params[arg]:
            return None
        else:
            raise ValueError("Parameter %s is mandatory" % arg)

    confdir = get_param('--confdir') or os.path.dirname(os.path.realpath(__file__))
    pidfile = get_param('--pidfile')

    if len(sys.argv) > 1:
        module = imp.load_source('config', confdir + "/" + sys.argv[1])
        params.update(module.params)

    try:
        map(check_params, params_name[:argc])
    except (ValueError,) as error:
        sys.stderr.write("%s\n" % error)
        exit(1)

    if pidfile:
        f = open(pidfile, 'w')
        f.write(os.getpid())
        f.close()

    try:
        UrlBot(**params)
    except (KeyboardInterrupt,):
        exit(0)
