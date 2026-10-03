"""Original fixture: A is an ordered pair; A and B reuse session setup x."""

class TestA:
    def test_first(self, x):
        x.append('A-first')
        assert x == ['A-first']

    def test_second(self, x):
        assert x == ['A-first']
        x.append('A-second')


def test_b(x):
    assert isinstance(x, list)


def test_c():
    assert 2 + 3 == 5


def test_d():
    assert 'cairn'.upper() == 'CAIRN'
