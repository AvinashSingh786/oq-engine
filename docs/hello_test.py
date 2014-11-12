from openquake.commonlib.tests.calculators import CalculatorTestCase


class HelloTestCase(CalculatorTestCase):
    def test(self):
        out = self.run_calc(__file__, 'hello.ini')
        self.assertGot('hello world', out['hello'])
