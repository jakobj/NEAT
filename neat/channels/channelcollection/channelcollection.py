import numpy as np
import sympy as sp

from neat import IonChannel
from neat import IonChannelSimplified


def sp_exp(x):
    return sp.exp(x, evaluate=False)

def sp_pow(x, y):
    return sp.Pow(x, y, evaluate=False)

# dictionary with suggested reversal potential for each channel
E_REV_DICT = {
                'TestChannel': -23.,
                'TestChannel2': -23.,
                'Na_Ta': 50.,
                'Kv3_1': -85.,
                'Kv3_1_simplified': -85.,
                'Na_Ta_simplified': 50.,
                'SK_simplified': -85.,
                'h_simplified': -43.,
                'h': -43.
             }


class TestChannel(IonChannel):
    """
    Simple channel to test basic functionality
    """
    def __init__(self):
        # always include this line, to define a sympy voltage symbol
        self.sp_v = sp.symbols('v')
        # basic factors to construct channel open probability
        self.factors = np.array([5.,1.])
        self.powers = np.array([[3,3,1],
                                [2,2,1]])
        self.varnames = np.array([['a00', 'a01', 'a02'],
                                  ['a10', 'a11', 'a12']])
        # asomptotic state variable functions
        self.varinf = np.array([[1./(1.+sp_exp((self.sp_v-30.)/100.)), 1./(1.+sp_exp((-self.sp_v+30.)/100.)), sp.Float(-10.)],
                                [2./(1.+sp_exp((self.sp_v-30.)/100.)), 2./(1.+sp_exp((-self.sp_v+30.)/100.)), sp.Float(-30.)]])
        # state variable relaxation time scale
        self.tauinf = np.array([[sp.Float(1.), sp.Float(2.), sp.Float(1.)],
                                [sp.Float(2.), sp.Float(2.), sp.Float(3.)]])
        # base class instructor
        super(TestChannel, self).__init__()


class TestChannel2(IonChannel):
    """
    Simple channel to test basic functionality
    """
    def __init__(self):
        # always include this line, to define a sympy voltage symbol
        self.sp_v = sp.symbols('v')
        # basic factors to construct channel open probability
        self.factors = np.array([.9,.1])
        self.powers = np.array([[3,2],
                                [2,1]])
        self.varnames = np.array([['a00', 'a01'],
                                  ['a10', 'a11']])
        # asomptotic state variable functions
        self.varinf = np.array([[sp.Float(.3), sp.Float(.5)],
                                [sp.Float(.4), sp.Float(.6)]])
        # state variable relaxation time scale
        self.tauinf = np.array([[1., 2.],
                                [2., 2.]])
        # base class instructor
        super(TestChannel2, self).__init__()


class Na_Ta(IonChannel):
    def __init__(self):
        """
        (Colbert and Pan, 2002)

        Used in (Hay, 2011)
        """
        self.ion = 'na'
        self.concentrations = []
        # always include this line, to define a sympy voltage symbol
        self.sp_v = sp.symbols('v')
        # state variables
        self.varnames = np.array([['m', 'h']])
        self.powers = np.array([[3,1]], dtype=int)
        self.factors = np.array([1.])
        # activation functions
        spalpham =   0.182 * (self.sp_v + 38.) / (1. - sp_exp(-(self.sp_v + 38.) / 6.)) # 1/ms
        spbetam  = - 0.124 * (self.sp_v + 38.) / (1. - sp_exp( (self.sp_v + 38.) / 6.)) # 1/ms
        spalphah = - 0.015 * (self.sp_v + 66.) / (1. - sp_exp( (self.sp_v + 66.) / 6.)) # 1/ms
        spbetah  =   0.015 * (self.sp_v + 66.) / (1. - sp_exp(-(self.sp_v + 66.) / 6.)) # 1/ms
        self.varinf = np.array([[spalpham / (spalpham + spbetam),
                                 spalphah / (spalphah + spbetah) ]])
        self.tauinf = np.array([[(1./2.95) / (spalpham + spbetam),
                                 (1./2.95) / (spalphah + spbetah)]]) # 1/ms
        # base class constructor
        super(Na_Ta, self).__init__()


class Na_Ta_simplified(IonChannelSimplified):
    def define(self):
        """
        (Colbert and Pan, 2002)

        Used in (Hay, 2011)
        """
        self.ion = 'na'
        # concentrations the ion channel depends on
        self.conc = {}
        # define channel open probability
        self.p_open = 'h * m ** 3'
        # define activation functions
        self.alpha, self.beta = {}, {}
        self.alpha['m'] =  '0.182 * (v + 38.) / (1. - exp(-(v + 38.) / 6.))' # 1/ms
        self.beta['m']  = '-0.124 * (v + 38.) / (1. - exp( (v + 38.) / 6.))' # 1/ms
        self.alpha['h'] = '-0.015 * (v + 66.) / (1. - exp( (v + 66.) / 6.))' # 1/ms
        self.beta['h']  =  '0.015 * (v + 66.) / (1. - exp(-(v + 66.) / 6.))' # 1/ms
        # temperature factor for time-scale
        self.q10 = 2.95

        # # temperature factor for time-scales
        # self.q10 = '2.3**((temp - 23.)/10.)'
        # # default parameters
        # self.t = 36. # [deg Celsius]
        # self.e = 50. # [mV]

class SK_simplified(IonChannelSimplified):
    def define(self):
        '''
        SK-type calcium-activated potassium current (Kohler et al., 1996)
        used in (Hay et al., 2011)
        '''
        self.ion = 'k'
        self.conc = ['ca']
        # define channel open probability
        self.p_open = 'z'
        # activation functions
        self.varinf = {'z': '1. / (1. + (0.00043 / ca)**4.8)'}
        self.tauinf = {'z': '1.'} # ms


class h_simplified(IonChannelSimplified):
    def define(self):
        """
        Hcn channel from (Bal and Oertel, 2000)
        """
        # define channel open probability
        self.p_open = '.8 * hf + .2 * hs'
        # define activation functions
        self.varinf, self.tauinf = {}, {}
        self.varinf['hf'] = '1. / (1. + exp((v + 82.) / 7.))'
        self.varinf['hs'] = '1. / (1. + exp((v + 82.) / 7.))'
        self.tauinf['hf'] = '40.'
        self.tauinf['hs'] = '300.'

class Kv3_1_simplified(IonChannelSimplified):
    def define(self):
        self.ion = 'k'
        # define channel open probability
        self.p_open = 'm'
        # define activation functions
        self.varinf = {'m': '1. / (1. + exp(-(v - 18.70) /  9.70))'}
        self.tauinf = {'m': '4. / (1. + exp(-(v + 46.56) / 44.14))'} # ms


class Kv3_1(IonChannel):
    def __init__(self):
        """
        Shaw-related potassium channel (Rettig et al., 1992)

        Used in (Hay et al., 2011)
        """
        self.ion = 'k'
        self.concentrations = []
        # always include this line, to define a sympy voltage symbol
        self.sp_v = sp.symbols('v')
        # state variables
        self.varnames = np.array([['m']])
        self.powers = np.array([[1]], dtype=int)
        self.factors = np.array([1.])
        # activation functions
        self.varinf = np.array([[1. / (1. + sp_exp(-(self.sp_v - 18.7) / 9.7))]])
        self.tauinf = np.array([[4. / (1. + sp_exp(-(self.sp_v + 46.56) / 44.14))]]) # ms
        # base class constructor
        super(Kv3_1, self).__init__()


class h(IonChannel):
    def __init__(self, ratio=0.2):
        """
        Hcn channel from (Bal and Oertel, 2000)
        """
        self.ion = ''
        self.concentrations = []
        self.ratio = ratio
        self.tauf = 40. # ms
        self.taus = 300. # ms
        # always include this line, to define a sympy voltage symbol
        self.sp_v = sp.symbols('v')
        # basic factors to construct channel open probability
        self.varnames = np.array([['hf'],
                                  ['hs']])
        self.powers = np.array([[1],
                                [1]], dtype=int)
        self.factors = np.array([1.-self.ratio, self.ratio])
        # asomptotic state variable functions
        self.varinf = np.array([[1./(1.+sp_exp((self.sp_v+82.)/7.))],
                                [1./(1.+sp_exp((self.sp_v+82.)/7.))]])
        # state variable relaxation time scales
        self.tauinf = np.array([[sp.Float(self.tauf)],
                                [sp.Float(self.taus)]])
        # base class constructor
        super(h, self).__init__()



