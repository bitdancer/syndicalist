# Copyright (c) 2013 by R. David Murray under an MIT license (LICENSE.txt).
class Trie:

    """A dict with the ability look up keys by longest prefix match."""

    # This Trie class was inspired by James Tauber's Trie class,
    # http://jtabuer.com/2005/02/trie.py.

    # The data structure is a dictionary tree, with the keys being letters.
    # The value of each node iis a two element list.  The first element is the
    # dictionary subtree.  The second element is the value of the node, which
    # is to say the value associated with the list of characters used to walk
    # down the tree to that point.  The default value is 'None', which means
    # there is no value for the string used to walk down to that node.

    def __init__(self):
        # The initial node represents the null string.
        self.root = [{}, None]

    def __setitem__(self, key, value):
        cur_node = self.root
        for ch in key:
            cur_node = cur_node[0].setdefault(ch, [{}, None])
        cur_node[1] = value

    def drop_value(self, key):
        self._drop_value(self.root, key)

    def _drop_value(self, node, remainder):
        if remainder:
            ch = remainder[0]
            subnode = node[0][ch]
            self._drop_value(subnode, remainder[1:])
            if not subnode[0].keys() and subnode[1] is None:
                del node[0][ch]
        else:
            assert node[1] is not None
            node[1] = None

    def _find_prefix_node(self, prefix):
        """Match the prefix in the tree, returning (subtrie, remainder).

        Subtrie is the portion of the Trie descendant from the node where
        the prefix match terminated.  If there were still characters left
        in the prefix, remainder is a string consisting of the remaining
        characters, otherwise it is the empty string.
        """
        node = self.root
        for (i, ch) in enumerate(prefix):
            try:
                node = node[0][ch]
            except KeyError:
                return node, prefix[i:]
        return node, ''

    def _subtrie_values(self, subtrie):
        """
        Return iterator over non-None values of the nodes in the given subtrie.
        """
        if subtrie[1] is not None:
            yield subtrie[1]
        for subsubtrie in subtrie[0].values():
            for value in self._subtrie_values(subsubtrie):
                yield value

    def get_values(self, prefix, min_length=0):
        """
        Return an iterator over the candidate values for the given prefix.

        If the node at which a prefix match is found has a value, an iterator
        containing only that value is returned.  If the node does not have
        a value, an iterator over all the values in the subtree is returned.
        
        If the prefix match is shorter than the minimum length, the returned
        iterator is empty.

            >>> t = Trie()
            >>> t['foo'] = 1
            >>> t['foobar'] = 2
            >>> t['fink'] = 3
            >>> t['bar'] = 4
            >>> list(t.get_values('foobar'))
            [2]
            >>> list(t.get_values('foo'))
            [1]
            >>> list(t.get_values('fi', min_length=3))
            []
            >>> list(t.get_values('fi', min_length=1))
            [3]
            >>> list(t.get_values('b', min_length=0))
            [4]
            >>> list(t.get_values('foobarbaz'))
            [2]
            >>> list(t.get_values('kapow', min_length=1))
            []

        When multiple values are returned the order of return is not
        deterministic since dictionary key hashing can affect the order in
        which the subtries are searched, and the search is depth first.

            >>> sorted(list(t.get_values('f', min_length=0)))
            [1, 2, 3]

        """
        node, remaining_chars = self._find_prefix_node(prefix)
        if len(prefix)-len(remaining_chars) < min_length:
            return iter([])
        if node[1] is not None:
            return iter([node[1]])
        return self._subtrie_values(node)

    def get_longest_match(self, key, default=None):
        """
        Return value of longest match in table and the unmatched substring.

        If there is no match with a value, return the default and the key.

        >>> t = Trie()
        >>> t['foo'] = 1
        >>> t['foobar'] = 2
        >>> t['foobaz'] = 3
        >>> t['foodo'] = 4
        >>> t.get_longest_match('notthere')
        (None, 'notthere')
        >>> t.get_longest_match('notthere', 'xx')
        ('xx', 'notthere')
        >>> t.get_longest_match('foo')
        (1, '')
        >>> t.get_longest_match('foocarana')
        (1, 'carana')
        >>> t.get_longest_match('f')
        (None, 'f')
        >>> t.get_longest_match('foobar')
        (2, '')
        >>> t.get_longest_match('foob')
        (1, 'b')
        >>> t.get_longest_match('foodooforfun')
        (4, 'oforfun')
        >>> t.get_longest_match('foobags')
        (1, 'bags')

        """
        i = 0
        node = self.root
        res = self._get_longest_match(key, 0, self.root)
        if res:
            return res
        return default, key

    def _get_longest_match(self, key, index, node):
        if index == len(key):
            done = True
        else:
            try:
                subnode = node[0][key[index]]
                done = False
            except KeyError:
                done = True
        if done:
            if node[1]:
                return node[1], key[index:]
            else:
                return
        res = self._get_longest_match(key, index+1, subnode)
        if res:
            return res
        if node[1]:
            return node[1], key[index:]
        return
