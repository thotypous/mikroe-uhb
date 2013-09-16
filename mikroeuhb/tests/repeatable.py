import unittest

class TestSuite(unittest.TestSuite):
    """Modified TestSuite which supports repeating multiple times
       TestCases containing a count attribute. Useful for randomly
       generated test cases."""
    def __iter__(self):
        for test in self._tests:
            count = test.count if hasattr(test, 'count') else 1
            for i in xrange(count):
                yield test

def make_load_tests(test_cases):
    """Return a load_tests function suitable for using test discovery
    with our modified TestSuite class"""
    def load_tests(loader, tests, pattern):
        suite = TestSuite()
        for test_class in test_cases:
            tests = loader.loadTestsFromTestCase(test_class)
            suite.addTests(tests)
        return suite
    return load_tests